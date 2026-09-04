#!/usr/bin/env python3
"""Validate a Mnemox release candidate without publishing it.

The normal mode checks application-version consistency and is safe to run on
every commit.  ``--release`` additionally verifies the public update manifest
and release notes.  ``--artifacts`` validates electron-builder output,
including the SHA-512 recorded in ``latest.yml``.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


class PreflightError(RuntimeError):
    pass


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot read JSON {path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreflightError(f"expected an object in {path.relative_to(ROOT)}")
    return value


def _match(path: Path, pattern: str, label: str) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PreflightError(f"cannot read {path.relative_to(ROOT)}: {exc}") from exc
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise PreflightError(f"cannot find {label} in {path.relative_to(ROOT)}")
    return match.group(1)


def application_versions() -> dict[str, str]:
    frontend = _read_json(ROOT / "frontend/package.json")
    frontend_lock = _read_json(ROOT / "frontend/package-lock.json")
    desktop = _read_json(ROOT / "desktop/package.json")
    desktop_lock = _read_json(ROOT / "desktop/package-lock.json")
    return {
        "backend_package": _match(
            ROOT / "backend/app/__init__.py", r'^__version__\s*=\s*["\']([^"\']+)["\']', "__version__"
        ),
        "backend_settings": _match(
            ROOT / "backend/app/config.py", r'^\s*APP_VERSION:\s*str\s*=\s*["\']([^"\']+)["\']', "APP_VERSION"
        ),
        "frontend_package": str(frontend.get("version") or ""),
        "frontend_lock": str(frontend_lock.get("version") or ""),
        "frontend_lock_root": str((frontend_lock.get("packages") or {}).get("", {}).get("version") or ""),
        "desktop_package": str(desktop.get("version") or ""),
        "desktop_lock": str(desktop_lock.get("version") or ""),
        "desktop_lock_root": str((desktop_lock.get("packages") or {}).get("", {}).get("version") or ""),
        "root_env_example": _match(ROOT / ".env.example", r"^APP_VERSION=(\S+)$", "APP_VERSION"),
    }


def validate_application_version(expected: str | None) -> tuple[str, dict[str, str]]:
    versions = application_versions()
    candidate = expected or versions["backend_package"]
    if not SEMVER.fullmatch(candidate):
        raise PreflightError(f"invalid semantic version: {candidate!r}")
    mismatches = {name: version for name, version in versions.items() if version != candidate}
    if mismatches:
        detail = ", ".join(f"{name}={value or '<missing>'}" for name, value in sorted(mismatches.items()))
        raise PreflightError(f"version mismatch; expected {candidate}: {detail}")
    return candidate, versions


def validate_release_metadata(version: str) -> dict[str, str]:
    manifest_path = ROOT / "release-manifest/latest.json"
    manifest = _read_json(manifest_path)
    expected_tag = f"v{version}"
    installer_name = f"Mnemox-Setup-{version}.exe"
    errors: list[str] = []
    if manifest.get("latest_version") != version:
        errors.append(f"latest_version={manifest.get('latest_version')!r}")
    if not str(manifest.get("release_page") or "").endswith(f"/tag/{expected_tag}"):
        errors.append("release_page tag does not match")
    windows_url = str((manifest.get("downloads") or {}).get("windows") or "")
    if f"/download/{expected_tag}/{installer_name}" not in windows_url:
        errors.append("Windows download URL does not match version/artifact name")
    if not str(manifest.get("published_at") or "").strip():
        errors.append("published_at is missing")

    notes_path = ROOT / f"release-notes-v{version}.md"
    if not notes_path.is_file():
        errors.append(f"missing {notes_path.name}")
    else:
        notes = notes_path.read_text(encoding="utf-8")
        if expected_tag not in notes:
            errors.append("release notes do not mention the version tag")
        if installer_name not in notes:
            errors.append("release notes do not mention the installer")
    if errors:
        raise PreflightError("release metadata invalid: " + "; ".join(errors))
    return {"manifest": str(manifest_path.relative_to(ROOT)), "release_notes": notes_path.name}


def _latest_yml_value(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*['\"]?([^'\"\r\n]+)['\"]?\s*$", text, re.MULTILINE)
    if not match:
        raise PreflightError(f"latest.yml is missing {key}")
    return match.group(1).strip()


def validate_artifacts(version: str, directory: Path) -> dict[str, str | int]:
    artifact_dir = directory.resolve()
    installer_name = f"Mnemox-Setup-{version}.exe"
    installer = artifact_dir / installer_name
    blockmap = artifact_dir / f"{installer_name}.blockmap"
    latest_yml = artifact_dir / "latest.yml"
    missing = [path.name for path in (installer, blockmap, latest_yml) if not path.is_file()]
    if missing:
        raise PreflightError("missing release artifact(s): " + ", ".join(missing))
    empty = [path.name for path in (installer, blockmap, latest_yml) if path.stat().st_size == 0]
    if empty:
        raise PreflightError("empty release artifact(s): " + ", ".join(empty))

    metadata = latest_yml.read_text(encoding="utf-8")
    if _latest_yml_value(metadata, "version") != version:
        raise PreflightError("latest.yml version does not match candidate")
    if _latest_yml_value(metadata, "path") != installer_name:
        raise PreflightError("latest.yml path does not match installer name")
    expected_sha512 = _latest_yml_value(metadata, "sha512")
    actual_sha512 = base64.b64encode(hashlib.sha512(installer.read_bytes()).digest()).decode("ascii")
    if expected_sha512 != actual_sha512:
        raise PreflightError("latest.yml SHA-512 does not match installer bytes")
    return {
        "installer": installer.name,
        "installer_bytes": installer.stat().st_size,
        "blockmap": blockmap.name,
        "latest_yml": latest_yml.name,
    }


def validate_git(
    require_clean: bool,
    require_tag: bool,
    reject_reused_tag: bool,
    version: str,
) -> dict[str, str | bool]:
    result: dict[str, str | bool] = {}
    if require_clean:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        if status:
            raise PreflightError("working tree is not clean")
        result["clean"] = True
    if require_tag:
        tag = f"v{version}"
        tagged = subprocess.run(
            ["git", "tag", "--points-at", "HEAD"],
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.splitlines()
        if tag not in tagged:
            raise PreflightError(f"HEAD is not tagged {tag}")
        result["tag"] = tag
    elif reject_reused_tag:
        tag = f"v{version}"
        tag_commit = subprocess.run(
            ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if tag_commit.returncode == 0:
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            existing = tag_commit.stdout.strip()
            if existing != head:
                raise PreflightError(
                    f"tag {tag} already points to {existing[:12]}; choose a new version for this candidate"
                )
            result["tag"] = tag
        else:
            result["tag_available"] = True
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="expected candidate version; defaults to backend package version")
    parser.add_argument("--release", action="store_true", help="also validate public manifest and release notes")
    parser.add_argument("--artifacts", type=Path, help="electron-builder output directory to validate")
    parser.add_argument("--require-clean", action="store_true", help="fail if the Git working tree is dirty")
    parser.add_argument("--require-tag", action="store_true", help="require v<version> to point at HEAD")
    parser.add_argument(
        "--reject-reused-tag",
        action="store_true",
        help="fail if v<version> already points at another commit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        version, versions = validate_application_version(args.version)
        report: dict[str, object] = {"ok": True, "version": version, "versions": versions}
        if args.release:
            report["release"] = validate_release_metadata(version)
        if args.artifacts:
            report["artifacts"] = validate_artifacts(version, args.artifacts)
        if args.require_clean or args.require_tag or args.reject_reused_tag:
            report["git"] = validate_git(
                args.require_clean,
                args.require_tag,
                args.reject_reused_tag,
                version,
            )
    except (PreflightError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
