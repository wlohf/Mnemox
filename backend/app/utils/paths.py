"""路径工具：统一 project_root/data/uploads 的定位。

Windows 下如果用相对路径，很容易把文件写到 backend/data/ 而不是根目录 data/。
"""

from __future__ import annotations

from pathlib import Path


def get_project_root() -> Path:
    """
    返回仓库根目录（StudyAssitant）。

    当前文件位于：backend/app/utils/paths.py
    parents:
      0 utils
      1 app
      2 backend
      3 project_root
    """

    return Path(__file__).resolve().parents[3]


def get_data_dir() -> Path:
    return get_project_root() / "data"


def get_uploads_dir() -> Path:
    return get_data_dir() / "uploads"


def get_images_dir() -> Path:
    return get_uploads_dir() / "images"


def get_chromadb_dir() -> Path:
    return get_data_dir() / "chromadb"


def ensure_data_dirs() -> None:
    get_uploads_dir().mkdir(parents=True, exist_ok=True)
    get_images_dir().mkdir(parents=True, exist_ok=True)
    get_chromadb_dir().mkdir(parents=True, exist_ok=True)


def to_repo_relative(path: Path) -> str:
    """将绝对路径转成相对项目根目录的路径（用于入库保存）。"""

    try:
        return str(path.resolve().relative_to(get_project_root()))
    except Exception:
        # 回退：直接保存字符串
        return str(path)


def from_repo_relative(rel_path: str) -> Path:
    """将数据库里保存的相对路径，解析成绝对路径。"""

    p = Path(rel_path)
    if p.is_absolute():
        return p
    return get_project_root() / p

