"""文件内容提取（用于预览/后续切分）。"""

from __future__ import annotations

import multiprocessing
from pathlib import Path
from typing import Any, Callable, Optional

# Bounded plain-text reads cannot hang, so they skip the process start-up cost.
_IN_PROCESS_EXTENSIONS = {".txt", ".md"}


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


def _isolated_call_worker(connection, function: Callable[..., Any], args: tuple) -> None:
    try:
        result = ("ok", function(*args))
    except BaseException as exc:  # a crashed child must still answer its parent
        result = ("error", type(exc).__name__)
    try:
        connection.send(result)
    finally:
        connection.close()


def run_in_killable_subprocess(function: Callable[..., Any], args: tuple, timeout_seconds: float) -> Any:
    """Run a picklable ``function(*args)`` in a child process killed on timeout.

    A timed-out thread keeps parsing and competing for the GIL with the event
    loop; a child process can actually be terminated. Blocking: call it from a
    worker thread. Frozen desktop builds need ``multiprocessing.freeze_support``.
    """
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_isolated_call_worker, args=(sender, function, args), daemon=True)
    process.start()
    sender.close()
    try:
        if not receiver.poll(timeout_seconds):
            raise TimeoutError(f"subprocess exceeded {timeout_seconds:g}s")
        status, payload = receiver.recv()
    except EOFError:
        raise RuntimeError("subprocess exited without a result") from None
    finally:
        receiver.close()
        if process.is_alive():
            process.kill()
        process.join(timeout=5)
    if status != "ok":
        raise RuntimeError(f"subprocess failed: {payload}")
    return payload


def extract_text_isolated(file_path: Path, max_chars: int, timeout_seconds: float) -> Optional[str]:
    """Extract text under a hard deadline; raises ``TimeoutError`` when exceeded."""
    if file_path.suffix.lower() in _IN_PROCESS_EXTENSIONS:
        return extract_text(file_path, max_chars)
    return run_in_killable_subprocess(extract_text, (file_path, max_chars), timeout_seconds)
