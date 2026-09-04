import base64
import hashlib
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "mnemox_release_preflight",
    ROOT / "scripts/release_preflight.py",
)
assert SPEC and SPEC.loader
release_preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_preflight)


def test_application_release_versions_are_synchronized():
    version, sources = release_preflight.validate_application_version(None)

    assert release_preflight.SEMVER.fullmatch(version)
    assert set(sources.values()) == {version}


def test_release_metadata_matches_current_public_version():
    version, _ = release_preflight.validate_application_version(None)
    metadata = release_preflight.validate_release_metadata(version)

    assert metadata["manifest"] == "release-manifest/latest.json"
    assert metadata["release_notes"] == f"release-notes-v{version}.md"


def test_artifact_preflight_verifies_electron_builder_sha512(tmp_path: Path):
    installer = tmp_path / "Mnemox-Setup-1.3.0.exe"
    installer.write_bytes(b"synthetic-installer")
    (tmp_path / "Mnemox-Setup-1.3.0.exe.blockmap").write_bytes(b"blockmap")
    digest = base64.b64encode(hashlib.sha512(installer.read_bytes()).digest()).decode("ascii")
    (tmp_path / "latest.yml").write_text(
        "version: 1.3.0\n"
        "path: Mnemox-Setup-1.3.0.exe\n"
        f"sha512: {digest}\n",
        encoding="utf-8",
    )

    result = release_preflight.validate_artifacts("1.3.0", tmp_path)

    assert result["installer_bytes"] == len(b"synthetic-installer")

    installer.write_bytes(b"tampered")
    with pytest.raises(release_preflight.PreflightError, match="SHA-512"):
        release_preflight.validate_artifacts("1.3.0", tmp_path)

    (tmp_path / "Mnemox-Setup-1.3.0.exe.blockmap").write_bytes(b"")
    with pytest.raises(release_preflight.PreflightError, match="empty release artifact"):
        release_preflight.validate_artifacts("1.3.0", tmp_path)
