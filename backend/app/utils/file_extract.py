"""文件内容提取（用于预览/后续切分/也可供 AnythingLLM 之外的流程）。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def extract_text(file_path: Path) -> Optional[str]:
    ext = file_path.suffix.lower()

    if ext in {".txt", ".md"}:
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # 兼容部分 Windows 文本
            return file_path.read_text(encoding="gbk", errors="ignore")

    if ext == ".pdf":
        try:
            from PyPDF2 import PdfReader
        except Exception:
            return None

        try:
            reader = PdfReader(str(file_path))
            texts: list[str] = []
            for page in reader.pages:
                t = page.extract_text() or ""
                if t.strip():
                    texts.append(t)
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
            paras = [p.text for p in d.paragraphs if p.text and p.text.strip()]
            return "\n".join(paras) if paras else None
        except Exception:
            return None

    # 其他格式暂不处理
    return None

