"""文件内容提取（用于预览/后续切分）。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def _trim_text(value: str, max_chars: int) -> str:
    return value[:max_chars] if max_chars > 0 else value


def extract_text(file_path: Path, max_chars: int = 2_000_000) -> Optional[str]:
    ext = file_path.suffix.lower()

    if ext in {".txt", ".md"}:
        try:
            with file_path.open("r", encoding="utf-8") as source:
                return _trim_text(source.read(max_chars + 1), max_chars)
        except UnicodeDecodeError:
            # 兼容部分 Windows 文本
            with file_path.open("r", encoding="gbk", errors="ignore") as source:
                return _trim_text(source.read(max_chars + 1), max_chars)

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except Exception:
            return None

        try:
            reader = PdfReader(str(file_path))
            texts: list[str] = []
            total = 0
            for page in reader.pages:
                t = page.extract_text() or ""
                if t.strip():
                    remaining = max_chars - total
                    if remaining <= 0:
                        break
                    piece = t[:remaining]
                    texts.append(piece)
                    total += len(piece)
            return "\n\n".join(texts) if texts else None
        except Exception:
            return None

    if ext in {".docx"}:
        try:
            import docx  # python-docx
        except Exception:
            return None

        try:
            d = docx.Document(str(file_path))
            paras: list[str] = []
            total = 0
            for paragraph in d.paragraphs:
                text = paragraph.text
                if not text or not text.strip():
                    continue
                remaining = max_chars - total
                if remaining <= 0:
                    break
                piece = text[:remaining]
                paras.append(piece)
                total += len(piece)
            return "\n".join(paras) if paras else None
        except Exception:
            return None

    # 其他格式暂不处理
    return None
