from pathlib import Path

path = Path(__file__).resolve().parents[1] / "backend/app/agents/chat_agent.py"
text = path.read_text(encoding="utf-8")
old = '''                        "memory_key": hit.title,\n                        "memory_value": hit.excerpt,\n                        "category": hit.metadata.get("category"),\n                        "confidence": hit.metadata.get("confidence"),\n                        "is_locked": hit.metadata.get("locked"),\n                        "review_status": hit.metadata.get("review_status"),\n'''
new = '''                        "key": hit.title,\n                        "value_preview": hit.excerpt[:240],\n                        "locked": hit.metadata.get("locked"),\n                        "memory_key": hit.title,\n                        "memory_value": hit.excerpt,\n                        "category": hit.metadata.get("category"),\n                        "confidence": hit.metadata.get("confidence"),\n                        "is_locked": hit.metadata.get("locked"),\n                        "review_status": hit.metadata.get("review_status"),\n'''
if text.count(old) != 1:
    raise RuntimeError(f"expected one memory adapter block, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
