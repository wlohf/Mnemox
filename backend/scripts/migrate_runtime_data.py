"""Copy a saved legacy /data tree to the durable runtime root, without overwrites.

Dry-run by default. Stop the old backend before taking the source snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path


def digest(path: Path) -> bytes:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").digest()


def migrate(source: Path, destination: Path, *, apply: bool = False) -> int:
    source, destination = source.resolve(), destination.resolve()
    if not source.is_dir() or source == destination or source in destination.parents:
        raise ValueError("源目录必须存在，目标不能位于源目录内")
    pending: list[tuple[Path, Path]] = []
    # Validate the entire plan before copying anything. Never merge conflicting
    # Chroma databases or silently overwrite an upload with different contents.
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"源目录包含符号链接：{item.relative_to(source)}")
        if not item.is_file():
            continue
        target = destination / item.relative_to(source)
        if not target.resolve().is_relative_to(destination):
            raise ValueError("目标路径越界")
        if target.exists():
            if not target.is_file() or digest(item) != digest(target):
                raise ValueError(f"目标存在不同内容，未覆盖：{item.relative_to(source)}")
        else:
            pending.append((item, target))
    if apply:
        for item, target in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation also protects against an unexpected concurrent writer.
            with item.open("rb") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            if digest(item) != digest(target):
                raise RuntimeError(f"复制校验失败：{item.relative_to(source)}")
    return len(pending)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", default=Path("/app/data"), type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    count = migrate(args.source, args.destination, apply=args.apply)
    print(f"{'已复制并校验' if args.apply else '待复制'} {count} 个文件；已有相同文件保留。")
