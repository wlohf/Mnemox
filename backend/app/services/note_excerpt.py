"""笔记摘录纯文本工具：供激励与自引服务共用（无 DB / 无外部依赖）。"""
from __future__ import annotations

import hashlib
import re

GENERIC_NOTE_TITLES = {"", "新笔记", "学习摘录", "无标题", "私有笔记"}
NOTE_SIGNAL_KEYWORDS = (
    "坚持",
    "行动",
    "专注",
    "复习",
    "方法",
    "习惯",
    "输出",
    "复盘",
    "不要",
    "先",
    "理解",
)


def compact_text(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def clean_markdown_line(line: str) -> str:
    text = line.strip()
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = re.sub(r"^\s*[-*+]\s*", "", text)
    text = re.sub(r"^\s*\d+[.)]\s*", "", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip(" >\t")


def extract_note_excerpt(content: str, limit: int = 96) -> str:
    if not content:
        return ""
    text = re.sub(r"```.*?```", " ", content, flags=re.S)
    candidates: list[str] = []
    for raw_line in text.splitlines():
        clean = clean_markdown_line(raw_line)
        if len(clean) < 10:
            continue
        candidates.append(clean)
        if len(candidates) >= 8:
            break
    if not candidates:
        return ""
    for item in candidates:
        if any(keyword in item for keyword in NOTE_SIGNAL_KEYWORDS):
            return compact_text(item, limit)
    return compact_text(candidates[0], limit)


def normalize_note_title(title: str) -> str:
    clean = compact_text(title or "", 40)
    return clean or "未命名笔记"


def should_reference_title(title: str) -> bool:
    return (title or "").strip() not in GENERIC_NOTE_TITLES


def excerpt_hash(excerpt: str) -> str:
    """摘录去重/冷却指纹：忽略大小写与空白差异。"""
    normalized = re.sub(r"\s+", " ", (excerpt or "").strip()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
