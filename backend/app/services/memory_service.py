"""AI 记忆服务：摘要与长期记忆提炼"""
import json
import logging
import random
import re
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatConversation
from app.models.memory import ConversationSummary, UserMemory
from app.utils.prompt_safety import wrap_untrusted_context

logger = logging.getLogger(__name__)


def _safe_json_loads(text: str, fallback):
    try:
        return json.loads(text)
    except Exception:
        return fallback


def _heuristic_extract_facts(user_text: str) -> List[dict]:
    """不依赖模型的轻量提炼，作为兜底。"""
    facts = []
    if not user_text:
        return facts

    patterns = [
        (r"我喜欢(.{1,30})", "preference_like", "preference", 0.7),
        (r"我不喜欢(.{1,30})", "preference_dislike", "preference", 0.75),
        (r"我正在学(.{1,30})", "current_learning", "goal", 0.72),
        (r"我想要(.{1,40})", "current_goal", "goal", 0.7),
        (r"我薄弱在(.{1,30})", "weak_topic", "weakness", 0.8),
    ]

    for idx, (pat, key, category, conf) in enumerate(patterns):
        m = re.search(pat, user_text)
        if m:
            value = m.group(1).strip(" ，。,.!?！？")
            if value:
                facts.append(
                    {
                        "memory_key": f"{key}_{idx}",
                        "memory_value": value,
                        "category": category,
                        "confidence": conf,
                    }
                )
    return facts


def _parse_llm_memories(raw: str) -> List[dict]:
    """解析模型输出的 JSON 列表。"""
    text = (raw or "").strip()
    if not text:
        return []

    # 兼容 ```json ... ```
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    data = _safe_json_loads(text, None)
    if not isinstance(data, list):
        return []

    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        key = str(item.get("memory_key", "")).strip()
        val = str(item.get("memory_value", "")).strip()
        cat = str(item.get("category", "preference")).strip() or "preference"
        conf = item.get("confidence", 0.7)
        try:
            conf_f = float(conf)
        except Exception:
            conf_f = 0.7
        conf_f = max(0.0, min(1.0, conf_f))
        if key and val:
            out.append(
                {
                    "memory_key": key,
                    "memory_value": val,
                    "category": cat,
                    "confidence": conf_f,
                }
            )
    return out


async def _extract_facts_with_llm(
    user_message: str,
    assistant_reply: str,
    db: AsyncSession,
    user_id: int,
) -> List[dict]:
    """使用 LLM 做结构化记忆提炼；失败时返回空列表。"""
    # 避免极短无信息消息也请求模型
    if len((user_message or "").strip()) < 6:
        return []

    prompt = (
        "你是一个信息提炼器。请从以下对话中提取‘稳定且可复用’的用户记忆。"
        "只输出 JSON 数组，不要输出任何解释文字。\n"
        "每个元素格式："
        "{\"memory_key\":\"...\",\"memory_value\":\"...\",\"category\":\"preference|goal|weakness|style\",\"confidence\":0~1}\n"
        "要求：\n"
        "1) memory_key 用 snake_case，语义稳定且可覆盖更新，如 preferred_explanation_style。\n"
        "2) 仅提取明确事实，不要猜测。\n"
        "3) 最多输出 5 条。\n\n"
        f"用户消息：{user_message}\n"
        f"AI回复：{assistant_reply[:500]}\n"
    )

    try:
        from app.ai.factory import AIProviderFactory

        provider = await AIProviderFactory.create_provider(
            db=db,
            scenario="memory_extract",
            user_id=user_id,
        )
        raw = await provider.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是结构化信息提炼器，只输出 JSON。",
            temperature=0.1,
        )
        return _parse_llm_memories(raw)
    except Exception:
        return []


async def build_memory_prompt_fragment(
    db: AsyncSession,
    limit: int = 10,
    topic_hint: str = "",
    material_ids: Optional[List[int]] = None,
    user_id: int = 1,
) -> str:
    """构建可注入 system prompt 的长期记忆片段。"""
    # 顺带触发记忆衰减（低频，不阻塞）
    try:
        await decay_old_memories(db, user_id=user_id)
    except Exception:
        pass
    query = select(UserMemory).where(
        UserMemory.status == "active",
        UserMemory.user_id == user_id,
    ).order_by(UserMemory.last_seen_at.desc(), UserMemory.updated_at.desc()).limit(50)
    result = await db.execute(query)
    rows = result.scalars().all()
    if not rows:
        return ""

    # Score memories by relevance
    hint_lower = (topic_hint or "").lower()

    def _score(mem: UserMemory) -> float:
        score = 0.0
        val = (mem.memory_value or "").lower()
        key = (mem.memory_key or "").lower()
        # Topic keyword match
        if hint_lower:
            for word in hint_lower.split():
                if len(word) >= 2 and (word in val or word in key):
                    score += 10.0
        # Material-scoped scoring
        mem_material_id = getattr(mem, "material_id", None)
        if material_ids and mem_material_id:
            if mem_material_id in material_ids:
                score += 15.0  # Boost matching material
            else:
                score -= 5.0  # Penalize cross-subject
        # Episodic recency boost
        mem_type = getattr(mem, "memory_type", "semantic") or "semantic"
        if mem_type == "episodic":
            last_seen = getattr(mem, "last_seen_at", None)
            if last_seen and (datetime.now() - last_seen).days <= 3:
                score += 3.0
        # Category boost for weakness
        cat = (mem.category or "").lower()
        if cat == "weakness":
            score += 5.0
        elif cat == "goal":
            score += 3.0
        elif cat == "style":
            score += 2.0
        # Confidence boost
        score += float(mem.confidence or 0.5) * 2.0
        return score

    scored = sorted(rows, key=_score, reverse=True)
    top = scored[:limit]

    # Group by category with Chinese labels
    category_labels = {
        "preference": "偏好",
        "goal": "学习目标",
        "weakness": "薄弱点",
        "style": "学习风格",
        "misconception": "错误理解",
        "confusion": "困惑点",
    }
    groups: dict = {}
    for r in top:
        cat = r.category or "preference"
        label = category_labels.get(cat, cat)
        groups.setdefault(label, []).append(r.memory_value)

    lines = []
    for label, values in groups.items():
        lines.append(f"【{label}】")
        for v in values:
            lines.append(f"  - {v}")

    return wrap_untrusted_context("用户长期记忆（个性化参考）", "\n".join(lines), source="user_memory")


async def decay_old_memories(db: AsyncSession, user_id: int = 1) -> None:
    """对超过7天未访问的记忆降低 confidence（每次衰减5%，低于0.2则归档）。"""
    from sqlalchemy import update
    cutoff = datetime.now() - timedelta(days=7)
    result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.is_locked != 1,
            UserMemory.last_seen_at < cutoff,
        )
    )
    rows = result.scalars().all()
    for mem in rows:
        new_conf = max(0.0, (mem.confidence or 0.5) * 0.95)
        mem.confidence = new_conf
        if new_conf < 0.2:
            mem.status = "ignored"
    if rows:
        await db.flush()

async def get_relevant_memories(
    db: AsyncSession,
    topic: str = "",
    limit: int = 10,
    user_id: int = 1,
) -> List[dict]:
    """Return topic-scored memories for frontend display / SSE indicators."""
    result = await db.execute(
        select(UserMemory)
        .where(UserMemory.status == "active", UserMemory.user_id == user_id)
        .order_by(UserMemory.last_seen_at.desc(), UserMemory.updated_at.desc())
        .limit(50)
    )
    rows = result.scalars().all()
    if not rows:
        return []

    hint_lower = (topic or "").lower()

    def _score(mem: UserMemory) -> float:
        score = 0.0
        val = (mem.memory_value or "").lower()
        key = (mem.memory_key or "").lower()
        if hint_lower:
            for word in hint_lower.split():
                if len(word) >= 2 and (word in val or word in key):
                    score += 10.0
        cat = (mem.category or "").lower()
        if cat == "weakness":
            score += 5.0
        elif cat == "goal":
            score += 3.0
        score += float(mem.confidence or 0.5) * 2.0
        return score

    scored = sorted(rows, key=_score, reverse=True)
    return [
        {
            "id": m.id,
            "category": m.category or "preference",
            "value": m.memory_value,
            "memory_type": getattr(m, "memory_type", "semantic") or "semantic",
        }
        for m in scored[:limit]
    ]


async def get_conversation_summary_text(conversation_id: int, db: AsyncSession, user_id: int = 1) -> str:
    result = await db.execute(
        select(ConversationSummary).where(
            ConversationSummary.conversation_id == conversation_id,
            ConversationSummary.user_id == user_id,
        )
    )
    item = result.scalar_one_or_none()

    parts = []
    if item and item.summary:
        parts.append(f"该对话已有摘要：{item.summary}")

    # Inject review_prompts from recent *other* conversations to carry forward insights
    review_result = await db.execute(
        select(ConversationSummary)
        .where(
            ConversationSummary.conversation_id != conversation_id,
            ConversationSummary.review_prompts.is_not(None),
            ConversationSummary.user_id == user_id,
        )
        .order_by(ConversationSummary.updated_at.desc())
        .limit(3)
    )
    recent_summaries = review_result.scalars().all()
    prompts_collected = []
    for s in recent_summaries:
        prompts = _safe_json_loads(s.review_prompts or "[]", [])
        for p in prompts:
            if isinstance(p, str) and p.strip():
                prompts_collected.append(p.strip())
        if len(prompts_collected) >= 5:
            break

    if prompts_collected:
        parts.append("基于之前对话的复习提示（可适当引导用户回顾）：")
        for p in prompts_collected[:5]:
            parts.append(f"  - {p}")

    if not parts:
        return ""
    return wrap_untrusted_context(
        "对话摘要与复习提示",
        "\n".join(parts),
        source=f"conversation_summary:{conversation_id}",
        max_chars=3000,
    )


async def upsert_conversation_summary(conversation_id: int, db: AsyncSession, user_id: int = 1) -> None:
    """对指定对话做滚动摘要（轻量启发式）。"""
    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.id.desc())
        .limit(20)
    )
    messages = list(reversed(msg_result.scalars().all()))
    if not messages:
        return

    user_msgs = [m.content for m in messages if m.role == "user"]
    ai_msgs = [m.content for m in messages if m.role == "assistant"]

    recent_user = user_msgs[-3:] if user_msgs else []
    recent_ai = ai_msgs[-2:] if ai_msgs else []

    summary_text = "；".join([s[:80] for s in recent_user])
    if recent_ai:
        summary_text += f"。AI近期回答重点：{recent_ai[-1][:120]}"

    key_points = [s[:60] for s in recent_user[:3]]
    todos = []
    for t in recent_user:
        if any(k in t for k in ["计划", "下一步", "复习", "整理", "完成"]):
            todos.append(t[:60])

    sum_result = await db.execute(
        select(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id)
    )
    row = sum_result.scalar_one_or_none()
    last_msg_time = messages[-1].created_at if messages else datetime.now()

    if not row:
        row = ConversationSummary(
            user_id=user_id,
            conversation_id=conversation_id,
            summary=summary_text[:500],
            key_points=json.dumps(key_points, ensure_ascii=False),
            todo_items=json.dumps(todos, ensure_ascii=False),
            message_count=len(messages),
            last_message_at=last_msg_time,
        )
        db.add(row)
    else:
        row.summary = summary_text[:500]
        row.key_points = json.dumps(key_points, ensure_ascii=False)
        row.todo_items = json.dumps(todos, ensure_ascii=False)
        row.message_count = len(messages)
        row.last_message_at = last_msg_time


async def upsert_user_memories_from_turn(
    conversation_id: int,
    user_message: str,
    assistant_reply: str,
    db: AsyncSession,
    user_id: int = 1,
) -> None:
    """从本轮对话提炼长期记忆：优先 LLM，失败回退启发式。"""
    facts = await _extract_facts_with_llm(user_message, assistant_reply, db, user_id=user_id)
    if not facts:
        facts = _heuristic_extract_facts(user_message)
    if not facts:
        return

    for fact in facts:
        key = fact["memory_key"]
        existing_result = await db.execute(
            select(UserMemory).where(UserMemory.memory_key == key, UserMemory.user_id == user_id)
        )
        row = existing_result.scalar_one_or_none()
        if not row:
            row = UserMemory(
                user_id=user_id,
                memory_key=key,
                memory_value=fact["memory_value"],
                category=fact["category"],
                confidence=fact["confidence"],
                source_conversation_id=conversation_id,
                status="active",
                is_locked=0,
                last_seen_at=datetime.now(),
            )
            db.add(row)
        else:
            if int(getattr(row, "is_locked", 0) or 0) == 1:
                # 锁定记忆不自动覆盖，仅刷新最近时间
                row.last_seen_at = datetime.now()
                continue
            if str(getattr(row, "status", "active")) == "ignored":
                # 忽略记忆不自动恢复
                row.last_seen_at = datetime.now()
                continue
            row.memory_value = fact["memory_value"]
            row.category = fact["category"]
            row.confidence = max(float(row.confidence or 0.0), float(fact["confidence"]))
            row.source_conversation_id = conversation_id
            row.last_seen_at = datetime.now()


async def list_memories(db: AsyncSession, user_id: int = 1) -> List[dict]:
    result = await db.execute(
        select(UserMemory)
        .where(UserMemory.user_id == user_id)
        .order_by(UserMemory.last_seen_at.desc(), UserMemory.id.desc())
        .limit(200)
    )
    rows = result.scalars().all()
    out = []
    for r in rows:
        out.append(
            {
                "id": r.id,
                "memory_key": r.memory_key,
                "memory_value": r.memory_value,
                "category": r.category,
                "confidence": r.confidence,
                "status": getattr(r, "status", "active"),
                "is_locked": int(getattr(r, "is_locked", 0) or 0),
                "source_conversation_id": r.source_conversation_id,
                "material_id": getattr(r, "material_id", None),
                "memory_type": getattr(r, "memory_type", "semantic") or "semantic",
                "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
            }
        )
    return out


async def list_summaries(db: AsyncSession, user_id: int = 1) -> List[dict]:
    result = await db.execute(
        select(ConversationSummary)
        .where(ConversationSummary.user_id == user_id)
        .order_by(ConversationSummary.updated_at.desc(), ConversationSummary.id.desc())
        .limit(200)
    )
    rows = result.scalars().all()
    out = []
    for r in rows:
        out.append(
            {
                "id": r.id,
                "conversation_id": r.conversation_id,
                "summary": r.summary,
                "key_points": _safe_json_loads(r.key_points or "[]", []),
                "todo_items": _safe_json_loads(r.todo_items or "[]", []),
                "message_count": r.message_count,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
        )
    return out


def _parse_reflection_json(raw: str) -> Optional[dict]:
    """Parse LLM reflection output as a JSON dict."""
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    data = _safe_json_loads(text, None)
    if isinstance(data, dict):
        return data
    return None


async def run_conversation_reflection(conversation_id: int, db: AsyncSession, user_id: int = 1) -> None:
    """Analyze conversation to extract structured learning insights.

    Triggered when message_count >= previous reflection_turn_count + 10.
    """
    from sqlalchemy import func as sa_func

    # Query actual total message count (not capped by LIMIT)
    count_result = await db.execute(
        select(sa_func.count()).select_from(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
    )
    total_msg_count = count_result.scalar() or 0
    if total_msg_count == 0:
        return

    # Load existing summary for reflection_turn_count (check gate early)
    sum_result = await db.execute(
        select(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id)
    )
    existing_summary = sum_result.scalar_one_or_none()
    prev_turn_count = int(getattr(existing_summary, "reflection_turn_count", 0) or 0)

    # Gate: require at least 10 new messages since last reflection
    if total_msg_count < prev_turn_count + 10:
        return

    # Load last 20 messages as context window for LLM
    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.id.desc())
        .limit(20)
    )
    messages = list(reversed(msg_result.scalars().all()))

    # Build conversation text for LLM
    conv_lines = []
    for m in messages:
        role_label = "用户" if m.role == "user" else "AI"
        conv_lines.append(f"{role_label}: {(m.content or '')[:300]}")
    conv_text = "\n".join(conv_lines)

    prompt = (
        "你是学习分析器。分析以下对话，提取结构化的学习洞察。\n\n"
        "要求：\n"
        "1. summary: 30-80字概述对话主题和用户学习进展\n"
        "2. questions_asked: 用户提出的关键学科问题（非闲聊），最多5条\n"
        "3. confusions: 用户表现出困惑的知识点（如反复追问、表示不理解），最多3条\n"
        "4. misconceptions: 用户暴露的错误理解（AI做了纠正的部分），最多3条\n"
        "5. memory_candidates: 值得长期记住的用户特征（薄弱点、学习偏好、目标等），最多5条\n"
        '   - 对于明确的用户偏好/目标，设 memory_type="semantic"\n'
        '   - 对于本次会话发现的临时困惑/薄弱点，设 memory_type="episodic"\n'
        "6. review_prompts: 下次对话时可以主动问用户的复习问题，最多3条\n\n"
        "输出格式（只输出 JSON，不要解释）：\n"
        "{\n"
        '  "summary": "...",\n'
        '  "questions_asked": ["..."],\n'
        '  "confusions": ["..."],\n'
        '  "misconceptions": ["..."],\n'
        '  "memory_candidates": [\n'
        '    {"memory_key": "...", "memory_value": "...", "category": "weakness|goal|style|preference", "confidence": 0.8, "memory_type": "episodic|semantic"}\n'
        "  ],\n"
        '  "review_prompts": ["..."]\n'
        "}\n\n"
        f"对话内容：\n{conv_text}\n"
    )

    try:
        from app.ai.factory import AIProviderFactory

        provider = await AIProviderFactory.create_provider(
            db=db,
            scenario="reflection",
            user_id=user_id,
        )
        raw = await provider.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是结构化学习分析器，只输出 JSON。",
            temperature=0.1,
        )
    except Exception:
        return

    data = _parse_reflection_json(raw)
    if not data:
        return

    # Upsert ConversationSummary with structured fields
    summary_text = str(data.get("summary", ""))[:500]
    questions_asked = data.get("questions_asked", [])
    confusions = data.get("confusions", [])
    misconceptions = data.get("misconceptions", [])
    review_prompts = data.get("review_prompts", [])
    memory_candidates = data.get("memory_candidates", [])

    if existing_summary:
        existing_summary.summary = summary_text or existing_summary.summary
        existing_summary.questions_asked = json.dumps(questions_asked, ensure_ascii=False)
        existing_summary.confusions = json.dumps(confusions, ensure_ascii=False)
        existing_summary.misconceptions = json.dumps(misconceptions, ensure_ascii=False)
        existing_summary.review_prompts = json.dumps(review_prompts, ensure_ascii=False)
        existing_summary.reflection_turn_count = total_msg_count
        existing_summary.message_count = total_msg_count
    else:
        new_summary = ConversationSummary(
            conversation_id=conversation_id,
            summary=summary_text,
            key_points=json.dumps([], ensure_ascii=False),
            todo_items=json.dumps([], ensure_ascii=False),
            questions_asked=json.dumps(questions_asked, ensure_ascii=False),
            confusions=json.dumps(confusions, ensure_ascii=False),
            misconceptions=json.dumps(misconceptions, ensure_ascii=False),
            review_prompts=json.dumps(review_prompts, ensure_ascii=False),
            reflection_turn_count=total_msg_count,
            message_count=total_msg_count,
            last_message_at=messages[-1].created_at if messages else datetime.now(),
        )
        db.add(new_summary)

    # Get material_ids from conversation (via project materials)
    conv_material_ids: List[int] = []
    try:
        from app.models.chat import ChatProjectMaterial
        conv_result = await db.execute(
            select(ChatConversation).where(ChatConversation.id == conversation_id)
        )
        conv = conv_result.scalar_one_or_none()
        if conv and conv.project_id:
            assoc_result = await db.execute(
                select(ChatProjectMaterial.material_id).where(
                    ChatProjectMaterial.project_id == conv.project_id
                )
            )
            conv_material_ids = [row[0] for row in assoc_result.all()]
    except Exception as e:
        logger.warning("读取会话关联资料失败 conversation_id=%s err=%s", conversation_id, e)

    # Store memory candidates
    if memory_candidates and isinstance(memory_candidates, list):
        await _upsert_reflection_memories(memory_candidates, conversation_id, conv_material_ids, db, user_id=user_id)

    # Create review schedules from misconceptions
    if misconceptions or review_prompts:
        await _create_review_schedules_from_reflection(misconceptions, review_prompts, db, user_id=user_id)


async def _upsert_reflection_memories(
    memories: List[dict],
    conversation_id: int,
    material_ids: List[int],
    db: AsyncSession,
    user_id: int = 1,
) -> None:
    """Store memory candidates from reflection, deduplicating by memory_key."""
    first_material_id = material_ids[0] if material_ids else None

    for item in memories:
        if not isinstance(item, dict):
            continue
        key = str(item.get("memory_key", "")).strip()
        val = str(item.get("memory_value", "")).strip()
        if not key or not val:
            continue

        cat = str(item.get("category", "preference")).strip() or "preference"
        try:
            conf = float(item.get("confidence", 0.7))
        except (TypeError, ValueError):
            conf = 0.7
        conf = max(0.0, min(1.0, conf))
        mem_type = str(item.get("memory_type", "semantic")).strip()
        if mem_type not in ("semantic", "episodic"):
            mem_type = "semantic"

        existing_result = await db.execute(
            select(UserMemory).where(UserMemory.memory_key == key, UserMemory.status == "active", UserMemory.user_id == user_id)
        )
        row = existing_result.scalar_one_or_none()

        if row:
            if int(getattr(row, "is_locked", 0) or 0) == 1:
                row.last_seen_at = datetime.now()
                continue
            row.memory_value = val
            row.category = cat
            row.confidence = max(float(row.confidence or 0.0), conf)
            row.source_conversation_id = conversation_id
            row.last_seen_at = datetime.now()
            if first_material_id:
                row.material_id = first_material_id
            if mem_type:
                row.memory_type = mem_type
        else:
            new_mem = UserMemory(
                user_id=user_id,
                memory_key=key,
                memory_value=val,
                category=cat,
                confidence=conf,
                status="active",
                is_locked=0,
                source_conversation_id=conversation_id,
                material_id=first_material_id,
                memory_type=mem_type,
                last_seen_at=datetime.now(),
            )
            db.add(new_mem)


async def _create_review_schedules_from_reflection(
    misconceptions: List[str],
    review_prompts: List[str],
    db: AsyncSession,
    user_id: int = 1,
) -> None:
    """Create ReviewSchedule entries for misconceptions detected by reflection.

    Each misconception is stored as a UserMemory (category="misconception", type="episodic"),
    and the ReviewSchedule.item_id points to that memory's id for label retrieval.
    """
    from app.models.question import ReviewSchedule

    now = datetime.now()
    due_date = now + timedelta(days=1)

    # Check existing pending reflection reviews to avoid flooding
    existing = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.item_type == "reflection",
            ReviewSchedule.status == "pending",
            ReviewSchedule.user_id == user_id,
        )
    )
    existing_count = len(existing.scalars().all())
    if existing_count >= 10:
        return  # Limit total pending reflection reviews

    for text in (misconceptions or []):
        if not isinstance(text, str) or not text.strip():
            continue
        text = text.strip()[:200]

        # Create or find a memory entry for this misconception
        mem_key = f"misconception_{hash(text) % 100000}"
        existing_mem = await db.execute(
            select(UserMemory).where(UserMemory.memory_key == mem_key, UserMemory.user_id == user_id)
        )
        mem_row = existing_mem.scalar_one_or_none()
        if not mem_row:
            mem_row = UserMemory(
                user_id=user_id,
                memory_key=mem_key,
                memory_value=text,
                category="misconception",
                confidence=0.8,
                status="active",
                is_locked=0,
                memory_type="episodic",
                last_seen_at=now,
            )
            db.add(mem_row)
            await db.flush()  # Get mem_row.id

        review = ReviewSchedule(
            user_id=user_id,
            item_type="reflection",
            item_id=mem_row.id,
            scheduled_date=due_date,
            interval_days=1,
            ease_factor=250,
            repetitions=0,
            status="pending",
        )
        db.add(review)


_UNDERSTANDING_TEMPLATES = [
    "你对这个概念的理解很到位！继续保持这种思考方式。",
    "很好的思路，这说明你正在建立清晰的知识框架。",
    "回答得不错，看得出你在认真思考。",
]

_PERSISTENCE_TEMPLATES = [
    "你已经持续学习了一段时间，坚持本身就是很大的进步。",
    "你的专注力很棒，适当休息也是高效学习的一部分哦。",
    "持续学习的你真的很棒，记得劳逸结合。",
]

_CORRECTION_ACCEPTED_TEMPLATES = [
    "能够接受新观点并调整理解，这是非常好的学习品质。",
    "纠正之前的理解需要勇气，你做得很好。",
    "从错误中学习是进步最快的方式，你的态度很棒。",
]

_MILESTONE_TEMPLATES = [
    "你在这个领域的知识积累越来越丰富了！",
    "随着学习的深入，你的知识体系正在不断完善。",
]

_ACCEPTANCE_PATTERNS = [
    "明白了", "懂了", "原来如此", "我理解了", "了解了", "我知道了",
    "学到了", "受教了", "有道理", "说得对", "确实",
]

_UNDERSTANDING_MARKERS = [
    "正确", "没错", "很好的理解", "理解得很好", "you're right",
    "说得对", "完全正确", "理解到位", "分析得很好",
]


async def detect_progress_feedback(
    user_message: str,
    assistant_reply: str,
    db: AsyncSession,
) -> Optional[dict]:
    """Detect if the current exchange shows progress worth acknowledging.

    Returns dict with feedback_type and message, or None.
    Types: "understanding" | "persistence" | "correction_accepted" | "milestone"
    """
    if not user_message or not assistant_reply:
        return None

    user_lower = user_message.lower()
    reply_lower = assistant_reply.lower()

    # correction_accepted: user acknowledges a correction
    if any(p in user_lower for p in _ACCEPTANCE_PATTERNS):
        return {
            "feedback_type": "correction_accepted",
            "message": random.choice(_CORRECTION_ACCEPTED_TEMPLATES),
            "emoji": "🌟",
        }

    # understanding: AI confirms user's understanding is correct
    if any(m in reply_lower for m in _UNDERSTANDING_MARKERS):
        return {
            "feedback_type": "understanding",
            "message": random.choice(_UNDERSTANDING_TEMPLATES),
            "emoji": "💡",
        }

    # persistence: every ~5 messages (heuristic via message length as proxy)
    # Check total user messages in recent context
    if len(user_message) > 30 and len(assistant_reply) > 200:
        # Roughly indicates substantive exchange; use randomness for ~20% trigger rate
        if random.random() < 0.15:
            return {
                "feedback_type": "persistence",
                "message": random.choice(_PERSISTENCE_TEMPLATES),
                "emoji": "💪",
            }

    return None


async def decay_episodic_memories(db: AsyncSession) -> int:
    """Mark stale episodic memories as ignored.

    Targets episodic memories not seen in 7+ days that are active and unlocked.
    Returns the number of decayed memories. Caller is responsible for commit.
    """
    cutoff = datetime.now() - timedelta(days=7)
    result = await db.execute(
        select(UserMemory).where(
            UserMemory.status == "active",
            UserMemory.is_locked == 0,
        )
    )
    rows = result.scalars().all()
    count = 0
    for mem in rows:
        mem_type = getattr(mem, "memory_type", "semantic") or "semantic"
        if mem_type != "episodic":
            continue
        last_seen = getattr(mem, "last_seen_at", None)
        if last_seen and last_seen < cutoff:
            mem.status = "ignored"
            count += 1

    return count
