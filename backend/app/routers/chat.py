"""AI 对话路由"""
import asyncio
import json
import logging
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.exc import OperationalError
from pydantic import BaseModel
from typing import Any, AsyncIterator, List, Optional, cast

from app.database import get_db
from app.ai.factory import AIProviderFactory
from app.ai.rag_service import get_rag_service
from app.models.material import Material
from app.models.chat import (
    ChatConversation,
    ChatMessage as ChatMessageModel,
    ChatProject,
    ChatProjectMaterial,
)
from app.models.session import Conversation as StudyConversation, StudySession
from app.services.memory_service import (
    build_memory_prompt_fragment,
    detect_progress_feedback,
    get_conversation_summary_text,
    get_relevant_memories,
    upsert_conversation_summary,
    upsert_user_memories_from_turn,
)
from app.services.search_settings_service import get_search_settings_dict
from app.services.web_search import SearchProviderSettings, WebSearchResult, search_web

from app.config import settings
from app.auth import get_current_user
from app.models.user import User
from app.utils.ai_errors import format_ai_provider_error
from app.utils.prompt_safety import wrap_untrusted_context

logger = logging.getLogger(__name__)

_SQLITE_LOCK_RETRY_DELAYS = (0.25, 0.75, 1.5, 3.0)
WEB_SEARCH_MODE_AUTO = "auto"
WEB_SEARCH_MODE_PROVIDER_HOSTED = "provider_hosted"
WEB_SEARCH_MODE_APP_SEARCH = "app_search"
WEB_SEARCH_MODE_GROK_SUMMARY = "grok_summary"
WEB_SEARCH_MODE_TAVILY = "tavily"
WEB_SEARCH_MODE_LOCAL_FALLBACK = "local_fallback"
_WEB_SEARCH_MODES = {
    WEB_SEARCH_MODE_AUTO,
    WEB_SEARCH_MODE_PROVIDER_HOSTED,
    WEB_SEARCH_MODE_APP_SEARCH,
    WEB_SEARCH_MODE_GROK_SUMMARY,
    WEB_SEARCH_MODE_TAVILY,
    WEB_SEARCH_MODE_LOCAL_FALLBACK,
}
_DEFAULT_GROK_SEARCH_PROVIDER_NAME = "openai-grok"
_URL_PATTERN = re.compile(r"https?://[^\s<>()\"']+")


# Correction markers that suggest the user made a mistake
_CORRECTION_MARKERS = [
    # 中文纠正标识
    "不正确", "不对", "错了", "纠正", "更正", "准确地说", "应该是",
    "正确的是", "其实", "不太准确", "需要注意", "请注意",
    "让我纠正", "让我重新解释", "这里有个误解",
    "常见误解", "常见错误", "不完全正确",
    "有一点偏差", "不够准确", "并非如此",
    "事实上", "实际上", "严格来说",
    # 英文纠正标识
    "not correct", "actually", "incorrect", "wrong",
    "misconception", "let me correct", "let me clarify",
    "that's not quite", "not exactly", "not quite right",
    "common mistake", "be careful", "important to note",
]


async def _detect_and_create_wrong_questions(
    user_msg: str,
    ai_reply: str,
    conversation_id: int,
    db: AsyncSession,
    user_id: int = None,
) -> None:
    """Heuristic + LLM detection of wrong answers in chat, auto-create WrongQuestion records."""
    from app.models.question import Question, WrongQuestion
    from app.models.material import Chapter

    # Heuristic check: does AI reply contain correction markers?
    reply_lower = ai_reply.lower()
    if not any(marker in reply_lower for marker in _CORRECTION_MARKERS):
        return

    # Use LLM to extract wrong questions
    prompt = (
        "你是错题检测器。请分析以下对话，判断用户是否犯了知识性错误。"
        "如果有错误，提取最多2条错题，输出 JSON 数组：\n"
        "[{\"content\":\"用户错误的问题/概念\",\"answer\":\"正确答案\",\"explanation\":\"错误原因\"}]\n"
        "如果没有明确的知识性错误，输出空数组 []\n"
        "只输出 JSON，不要解释。\n\n"
        f"用户消息：{user_msg[:500]}\n"
        f"AI回复：{ai_reply[:800]}\n"
    )

    try:
        from app.ai.factory import AIProviderFactory
        import re as _re

        provider = await AIProviderFactory.create_provider(
            db=db,
            scenario="wrong_detect",
            user_id=user_id,
        )
        raw = await provider.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是错题检测器，只输出 JSON 数组。",
            temperature=0.1,
        )

        # Parse JSON
        text = (raw or "").strip()
        if text.startswith("```"):
            text = _re.sub(r"^```(?:json)?", "", text, flags=_re.IGNORECASE).strip()
            if text.endswith("```"):
                text = text[:-3].strip()

        items = json.loads(text)
        if not isinstance(items, list) or not items:
            return

        # 获取当前用户的章节，避免归属到其他用户的章节
        from app.models.material import Material
        chapter_result = await db.execute(
            select(Chapter)
            .join(Material, Chapter.material_id == Material.id)
            .where(Material.user_id == user_id)
            .limit(1)
        )
        chapter = chapter_result.scalar_one_or_none()
        if not chapter:
            # 用户无章节，使用错题本的默认章节创建逻辑
            from app.routers.wrong_questions import _ensure_default_chapter
            chapter_id = await _ensure_default_chapter(db, user_id=user_id)
            ch_result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
            chapter = ch_result.scalar_one_or_none()
            if not chapter:
                return

        from datetime import datetime
        now = datetime.now()

        for item in items[:2]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            if not content:
                continue

            question = Question(
                chapter_id=chapter.id,
                question_type="short_answer",
                content=content,
                answer=str(item.get("answer", "")),
                explanation=str(item.get("explanation", "")),
                difficulty=2,
            )
            if user_id:
                question.user_id = user_id
            db.add(question)
            await db.flush()

            wrong = WrongQuestion(
                question_id=question.id,
                first_wrong_at=now,
                last_wrong_at=now,
                wrong_count=1,
                mastery_status="not_mastered",
                next_review_at=now,
                review_count=0,
            )
            if user_id:
                wrong.user_id = user_id
            db.add(wrong)
            await db.flush()

            # Also create ReviewSchedule for the wrong question
            from app.models.question import ReviewSchedule
            review = ReviewSchedule(
                item_type="question",
                item_id=wrong.id,
                scheduled_date=now,
                interval_days=1,
                ease_factor=250,
                repetitions=0,
                status="pending",
            )
            if user_id:
                review.user_id = user_id
            db.add(review)

        await db.flush()
    except Exception as e:
        logger.warning("自动检测错题失败: %s", e)


router = APIRouter()

BASE_SYSTEM_PROMPT = (
    "你是一个专业的学习助手，帮助用户理解和掌握各种学科知识。"
    "请用清晰、简洁的中文回答问题。如果涉及公式或代码，请使用 Markdown 格式。"
)

COACH_SYSTEM_PROMPT = (
    "【内嵌学习教练策略】\n"
    "你是一位学习教练，但不要把苏格拉底式提问或费曼学习法做成孤立模式。\n"
    "1. 普通事实性问题：先给清晰简洁的答案，再视情况给 1 个启发问题。\n"
    "2. 概念理解、推理、知识关联或用户明显困惑时：用苏格拉底式追问帮助用户说出自己的理解。\n"
    "3. 每日复盘、总结、学习结束时：使用费曼技巧，引导用户用自己的话讲给初学者听。\n"
    "4. 用户卡住时先给渐进式提示，不要直接替用户完成全部思考。\n"
    "5. 每次最多追问 1-2 个关键问题，避免打断学习节奏。\n"
)

WARM_COACH_PERSONALITY = (
    "\n\n【沟通风格】\n"
    "你是一位温暖、耐心的学习伙伴。请遵循：\n"
    "1. 语气亲切自然，像朋友间的讨论，避免居高临下的说教。\n"
    "2. 当用户理解正确时，给予具体的肯定（说明哪里理解得好）。\n"
    "3. 当用户犯错时，先肯定思考过程，再温和地纠正。\n"
    "4. 适当使用鼓励性语言，但要真诚，不要过度。\n"
    "5. 偶尔可以分享一个相关的学习小贴士或有趣的知识关联。\n"
)

MAX_TOTAL_CHARS = 30000
AUTO_MATERIAL_LIMIT = 8


def _looks_like_read_materials_intent(message: str) -> bool:
    """判断用户是否在请求"读取资料库内容"类意图。"""
    text = (message or "").lower()
    if not text:
        return False

    material_words = [
        "资料",
        "资料库",
        "文档",
        "文件",
        "笔记",
        "教材",
        "material",
    ]
    action_words = [
        "读",
        "读取",
        "结合",
        "根据",
        "参考",
        "总结",
        "梳理",
        "讲解",
        "解释",
        "复习",
    ]

    has_material = any(w in text for w in material_words)
    has_action = any(w in text for w in action_words)
    return has_material and has_action


async def _detect_materials_from_message(message: str, db: AsyncSession, user_id: int = None) -> List[dict]:
    """从用户消息中自动检测提到的资料名称。

    返回 [{"id": int, "title": str}, ...] 按标题长度降序排列。
    """
    query = select(Material.id, Material.title)
    if user_id:
        query = query.where(Material.user_id == user_id)
    result = await db.execute(query)
    rows = result.all()

    msg_lower = message.lower()
    matched = []
    for row in rows:
        title = row.title or ""
        if len(title) < 2:
            continue
        if title.lower() in msg_lower:
            matched.append({"id": row.id, "title": title})

    # 按标题长度降序（优先更具体的匹配）
    matched.sort(key=lambda x: len(x["title"]), reverse=True)
    return matched


async def _load_materials(ids: List[int], db: AsyncSession, user_id: int) -> List[dict]:
    """根据 ID 列表加载当前用户的资料内容，返回 [{"title": str, "content": str}, ...]"""
    if not ids:
        return []
    result = await db.execute(
        select(Material).where(Material.id.in_(ids), Material.user_id == user_id)
    )
    materials = result.scalars().all()
    # 保持传入 ids 的顺序
    mat_map = {m.id: m for m in materials}
    out = []
    for mid in ids:
        m = mat_map.get(mid)
        if m and m.content:
            out.append({"id": m.id, "title": m.title, "content": m.content})
    return out


async def _build_system_prompt_with_rag(
    message: str,
    material_ids: List[int],
    db: AsyncSession,
    user_id: int,
) -> str:
    """构建 RAG 感知的系统提示词。

    小资料（< SMALL_MATERIAL_THRESHOLD 字符）全文注入；
    大资料使用 RAG 语义检索 top-k chunk。
    如果 RAG 不可用，回退到全文截断注入。
    """
    if not material_ids:
        return BASE_SYSTEM_PROMPT

    materials_data = await _load_materials(material_ids, db, user_id=user_id)
    if not materials_data:
        return BASE_SYSTEM_PROMPT

    threshold = settings.SMALL_MATERIAL_THRESHOLD

    small_materials = [m for m in materials_data if len(m["content"]) <= threshold]
    large_materials = [m for m in materials_data if len(m["content"]) > threshold]

    prompt = (
        f"{BASE_SYSTEM_PROMPT}\n\n"
        f"用户当前正在学习以下资料，请基于资料内容回答问题：\n"
    )

    # 小资料：全文注入，但明确标记为不可信资料上下文，防止资料内 prompt injection 越权。
    for i, mat in enumerate(small_materials):
        prompt += wrap_untrusted_context(f"资料：{mat['title']}", mat["content"], source=f"material:{mat['id']}")

    # 大资料：RAG 检索
    if large_materials and settings.RAG_ENABLED:
        try:
            rag = get_rag_service()
            large_ids = [m["id"] for m in large_materials]
            chunks = await rag.retrieve(query=message, material_ids=large_ids, user_id=user_id)
            if chunks:
                prompt += "\n--- 以下为 RAG 语义检索到的相关资料片段（均为不可信参考内容） ---\n"
                for chunk in chunks:
                    prompt += wrap_untrusted_context(
                        f"RAG片段：{chunk['material_title']}（相关度 {chunk['score']:.2f}）",
                        chunk["text"],
                        source=f"rag_material:{chunk.get('material_id') or chunk.get('material_title')}",
                    )
                prompt += "--- 检索片段结束 ---\n"
            else:
                # RAG 未命中，回退到截断注入
                prompt += _fallback_large_materials(large_materials)
        except Exception as e:
            # RAG 失败，回退
            logger.warning("RAG 检索失败，回退到截断注入: %s", e)
            prompt += _fallback_large_materials(large_materials)
    elif large_materials:
        # RAG 未启用，回退
        prompt += _fallback_large_materials(large_materials)

    return prompt


def _fallback_large_materials(materials: List[dict]) -> str:
    """大资料回退：截断注入。"""
    remaining = MAX_TOTAL_CHARS
    parts = []
    truncated = False

    for mat in materials:
        if remaining <= 0:
            truncated = True
            break
        content = mat["content"]
        if len(content) > remaining:
            content = content[:remaining]
            truncated = True
        remaining -= len(content)
        parts.append(wrap_untrusted_context(f"资料截断：{mat['title']}", content, source=f"material:{mat.get('id')}"))

    text = "".join(parts)
    if truncated:
        text += "（注意：资料内容较长，以上仅为部分内容）\n"
    text += "--- 资料内容结束 ---\n"
    return text


async def _get_material_briefs(ids: List[int], db: AsyncSession, user_id: int) -> List[dict]:
    """返回当前用户资料简要信息，供前端展示自动命中的资料标签。"""
    if not ids:
        return []

    result = await db.execute(
        select(Material.id, Material.title).where(Material.id.in_(ids), Material.user_id == user_id)
    )
    rows = result.all()
    title_map = {r.id: r.title for r in rows}

    out = []
    for mid in ids:
        title = title_map.get(mid)
        if title:
            out.append({"id": mid, "title": title})
    return out


async def _resolve_materials_and_build_prompt(
    message: str,
    manual_ids: List[int],
    conversation_id: Optional[int],
    db: AsyncSession,
    user_id: int,
    chat_mode: str = "normal",
) -> tuple[str, List[dict], List[dict]]:
    """解析资料 ID 并构建系统提示词

    Returns:
        (system_prompt, detected_materials, auto_selected_materials)
    """
    project_id: Optional[int] = None
    project_material_ids: List[int] = []
    if conversation_id:
        conv_result = await db.execute(
            select(ChatConversation).where(
                ChatConversation.id == conversation_id,
                ChatConversation.user_id == user_id,
            )
        )
        conv = conv_result.scalar_one_or_none()
        if conv and conv.project_id:
            project_id = conv.project_id
            assoc_result = await db.execute(
                select(ChatProjectMaterial.material_id)
                .join(Material, ChatProjectMaterial.material_id == Material.id)
                .where(
                    ChatProjectMaterial.project_id == conv.project_id,
                    Material.user_id == user_id,
                )
            )
            project_material_ids = [row[0] for row in assoc_result.all()]

    # 自动检测消息中提到的资料
    detected = await _detect_materials_from_message(message, db, user_id=user_id)
    detected_ids = [d["id"] for d in detected]

    if project_id is not None:
        allowed_ids = set(project_material_ids)
        manual_ids = [mid for mid in manual_ids if mid in allowed_ids]
        detected_ids = [did for did in detected_ids if did in allowed_ids]

    # 合并去重
    all_ids = list(manual_ids)
    for did in detected_ids:
        if did not in all_ids:
            all_ids.append(did)

    # 自动注入：项目绑定资料
    auto_selected: List[dict] = []
    if not all_ids and project_id is not None:
        for pid in project_material_ids:
            if pid not in all_ids:
                all_ids.append(pid)
        if project_material_ids:
            auto_selected.extend(await _get_material_briefs(project_material_ids, db, user_id=user_id))

    # 自动注入：读取资料库意图
    if not all_ids and _looks_like_read_materials_intent(message):
        recent_ids = await _get_recent_material_ids(db, user_id=user_id, project_id=project_id)
        for rid in recent_ids:
            if rid not in all_ids:
                all_ids.append(rid)
        if recent_ids:
            auto_selected.extend(await _get_material_briefs(recent_ids, db, user_id=user_id))

    # 构建 RAG 感知的系统提示
    system_prompt = await _build_system_prompt_with_rag(message, all_ids, db, user_id=user_id)

    # 根据 chat_mode 注入对应的用户自定义或默认 prompt
    try:
        from app.routers.prompt_templates import get_user_prompt, DEFAULT_PROMPTS
        mode_prompt = ""
        if chat_mode == "coach":
            mode_prompt = await get_user_prompt(db, user_id, "coach")
            system_prompt = mode_prompt + "\n" + system_prompt
        elif chat_mode in DEFAULT_PROMPTS:
            mode_prompt = await get_user_prompt(db, user_id, chat_mode)
            system_prompt = mode_prompt + "\n" + system_prompt
        elif chat_mode == "normal":
            # normal 模式用 coach prompt 作为基础人格
            mode_prompt = await get_user_prompt(db, user_id, "coach")
            system_prompt = mode_prompt + "\n" + system_prompt
    except Exception as _mpe:
        logger.warning("模式 prompt 注入失败: %s", _mpe)
        # fallback 到原来的 coach 逻辑
        if chat_mode == "coach":
            system_prompt = COACH_SYSTEM_PROMPT + "\n" + system_prompt

    # 记忆和摘要
    try:
        system_prompt += await build_memory_prompt_fragment(
            db, topic_hint=message, material_ids=all_ids, user_id=user_id
        )
        if conversation_id:
            system_prompt += await get_conversation_summary_text(
                conversation_id, db, user_id=user_id
            )
    except Exception as e:
        logger.warning("构建记忆/摘要提示失败: %s", e)

    system_prompt += WARM_COACH_PERSONALITY

    # 项目默认指令
    if conversation_id:
        conv_result = await db.execute(
            select(ChatConversation).where(
                ChatConversation.id == conversation_id,
                ChatConversation.user_id == user_id,
            )
        )
        conv = conv_result.scalar_one_or_none()
        if conv and conv.project_id:
            proj_result = await db.execute(
                select(ChatProject).where(
                    ChatProject.id == conv.project_id,
                    ChatProject.user_id == user_id,
                )
            )
            proj = proj_result.scalar_one_or_none()
            if proj and proj.default_instructions:
                system_prompt += "\n\n" + wrap_untrusted_context(
                    "项目自定义指令",
                    str(proj.default_instructions),
                    source=f"project:{proj.id}",
                    max_chars=2000,
                )

    # 注入用户学习画像（个性化建议上下文）
    try:
        from app.services.profile_service import get_or_compute_profile, build_profile_prompt_snippet
        _profile = await get_or_compute_profile(db, user_id)
        _snippet = build_profile_prompt_snippet(_profile)
        if _snippet:
            system_prompt += "\n\n" + _snippet
    except Exception as _pe:
        logger.warning("用户画像注入失败: %s", _pe)

    # 注入自主 Agent 简报：让对话具备主动规划、风险提醒和下一步建议意识
    try:
        from app.services.agent_service import build_agent_brief, build_agent_prompt_snippet
        _agent_brief = await build_agent_brief(db, user_id)
        _agent_snippet = build_agent_prompt_snippet(_agent_brief)
        if _agent_snippet:
            system_prompt += "\n\n" + _agent_snippet
    except Exception as _ae:
        logger.warning("自主 Agent 简报注入失败: %s", _ae)

    return system_prompt, detected, auto_selected


async def _get_project_material_ids(conversation_id: int, db: AsyncSession, user_id: int) -> List[int]:
    """获取对话所属项目绑定的资料 ID 列表。"""
    conv_result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user_id,
        )
    )
    conv = conv_result.scalar_one_or_none()
    if not conv or not conv.project_id:
        return []

    assoc_result = await db.execute(
        select(ChatProjectMaterial.material_id)
        .join(Material, ChatProjectMaterial.material_id == Material.id)
        .where(
            ChatProjectMaterial.project_id == conv.project_id,
            Material.user_id == user_id,
        )
    )
    return [row[0] for row in assoc_result.all()]


async def _get_recent_material_ids(
    db: AsyncSession,
    user_id: int = None,
    project_id: Optional[int] = None,
    limit: int = AUTO_MATERIAL_LIMIT,
) -> List[int]:
    """获取最近上传的资料 ID（仅含有内容的资料）。"""
    query = (
        select(Material.id)
        .where(Material.content.is_not(None))
    )
    if user_id:
        query = query.where(Material.user_id == user_id)
    if project_id is not None:
        query = query.join(
            ChatProjectMaterial,
            ChatProjectMaterial.material_id == Material.id,
        ).where(ChatProjectMaterial.project_id == project_id)
    query = query.order_by(desc(Material.created_at), desc(Material.id)).limit(limit)
    result = await db.execute(query)
    return [row[0] for row in result.all()]


# ---- Schemas ----

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = None
    material_id: Optional[int] = None
    material_ids: Optional[List[int]] = None
    conversation_id: Optional[int] = None
    study_session_id: Optional[int] = None
    image_data: Optional[List[str]] = None
    chat_mode: Optional[str] = "normal"  # "normal" | "coach"
    provider_name: Optional[str] = None
    model: Optional[str] = None
    web_search_enabled: bool = False
    web_search_mode: str = WEB_SEARCH_MODE_AUTO
    web_search_provider_name: Optional[str] = None


def _is_sqlite_database_locked(exc: Exception) -> bool:
    if isinstance(exc, OperationalError) and "database is locked" in str(exc).lower():
        return True
    return "sqlite3.operationalerror" in str(exc).lower() and "database is locked" in str(exc).lower()


async def _persist_streamed_chat_turn_once(
    *,
    body: ChatRequest,
    full_reply: str,
    user_id: int,
    sessionmaker,
) -> None:
    async with sessionmaker() as save_db:
        try:
            conv = None
            sess = None
            if body.conversation_id:
                conv_result = await save_db.execute(
                    select(ChatConversation).where(
                        ChatConversation.id == body.conversation_id,
                        ChatConversation.user_id == user_id,
                    )
                )
                conv = conv_result.scalar_one_or_none()

            if body.study_session_id:
                sess_result = await save_db.execute(
                    select(StudySession).where(
                        StudySession.id == body.study_session_id,
                        StudySession.user_id == user_id,
                    )
                )
                sess = sess_result.scalar_one_or_none()

            if body.conversation_id:
                save_db.add(
                    ChatMessageModel(
                        conversation_id=body.conversation_id,
                        role="user",
                        content=body.message,
                        image_data=json.dumps(body.image_data, ensure_ascii=False) if body.image_data else None,
                    )
                )
                save_db.add(
                    ChatMessageModel(
                        conversation_id=body.conversation_id,
                        role="assistant",
                        content=full_reply,
                    )
                )

                if conv:
                    if conv.title == "新对话":
                        conv.title = body.message[:50]
                    conv.updated_at = datetime.now()

            if sess:
                save_db.add(
                    StudyConversation(
                        session_id=sess.id,
                        role="user",
                        content=body.message,
                        message_type="chat",
                    )
                )
                save_db.add(
                    StudyConversation(
                        session_id=sess.id,
                        role="assistant",
                        content=full_reply,
                        message_type="chat",
                    )
                )

            await save_db.commit()
        except Exception:
            await save_db.rollback()
            raise


async def _persist_streamed_chat_turn(
    *,
    body: ChatRequest,
    full_reply: str,
    user_id: int,
    sessionmaker=None,
) -> None:
    """Persist the recoverable part of a streamed chat turn before SSE success."""
    if not full_reply or not (body.conversation_id or body.study_session_id):
        return

    if sessionmaker is None:
        from app.database import async_session_maker
        sessionmaker = async_session_maker

    for attempt, delay in enumerate((0, *_SQLITE_LOCK_RETRY_DELAYS), start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            await _persist_streamed_chat_turn_once(
                body=body,
                full_reply=full_reply,
                user_id=user_id,
                sessionmaker=sessionmaker,
            )
            break
        except Exception as exc:
            if _is_sqlite_database_locked(exc) and attempt <= len(_SQLITE_LOCK_RETRY_DELAYS):
                logger.warning(
                    "流式对话核心消息保存遇到 SQLite 写锁，准备重试: attempt=%s conversation_id=%s study_session_id=%s user_id=%s",
                    attempt,
                    body.conversation_id,
                    body.study_session_id,
                    user_id,
                )
                continue
            logger.exception(
                "流式对话核心消息保存失败: conversation_id=%s study_session_id=%s user_id=%s",
                body.conversation_id,
                body.study_session_id,
                user_id,
            )
            raise

    if not body.conversation_id:
        return

    async with sessionmaker() as enrich_db:
        try:
            await upsert_conversation_summary(body.conversation_id, enrich_db, user_id=user_id)
            await enrich_db.commit()

            await upsert_user_memories_from_turn(
                body.conversation_id,
                body.message,
                full_reply,
                enrich_db,
                user_id=user_id,
            )
            await enrich_db.commit()

            try:
                from app.services.memory_service import run_conversation_reflection
                await run_conversation_reflection(body.conversation_id, enrich_db, user_id=user_id)
                await enrich_db.commit()
            except Exception as e:
                await enrich_db.rollback()
                logger.warning("对话反思失败: %s", e)

            try:
                await _detect_and_create_wrong_questions(
                    body.message,
                    full_reply,
                    body.conversation_id,
                    enrich_db,
                    user_id=user_id,
                )
                await enrich_db.commit()
            except Exception as e:
                await enrich_db.rollback()
                logger.warning("错题自动检测失败: %s", e)

            try:
                from app.services.event_tracker import EventTracker as _ET
                from app.models.learning_event import EventType as _EVT
                _tracker = _ET(enrich_db, user_id=cast(int, cast(object, user_id)))
                await _tracker.track(
                    event_type=_EVT.AI_QUESTION_ASKED,
                    event_data={
                        "conversation_id": body.conversation_id,
                        "message_len": len(body.message),
                        "reply_len": len(full_reply),
                        "chat_mode": body.chat_mode or "normal",
                    },
                    session_id=str(body.conversation_id),
                )
                await enrich_db.commit()
            except Exception as e:
                await enrich_db.rollback()
                logger.warning("学习事件追踪失败: %s", e)
        except Exception:
            await enrich_db.rollback()
            logger.warning(
                "流式对话后处理失败，但核心消息已保存: conversation_id=%s user_id=%s",
                body.conversation_id,
                user_id,
                exc_info=True,
            )




def _is_ai_configuration_error(exc: Exception) -> bool:
    text = str(exc)
    return "API Key 未配置" in text or "不支持的 AI 提供商" in text


def _ai_configuration_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "code": "AI_PROVIDER_NOT_CONFIGURED",
            "message": (
                f"AI 提供商未配置或不可用：{str(exc)}。"
                "请先在设置中检查并启用当前供应商的 API Key、Base URL 和模型配置。"
                "如果你开启了联网搜索，也不会额外使用单独的搜索 Key。"
            ),
        },
    )


def _format_web_search_context(results: list[WebSearchResult]) -> str:
    lines: list[str] = []
    for index, item in enumerate(results, start=1):
        lines.append(
            "\n".join(
                [
                    f"[{index}] {item.title}",
                    f"URL: {item.url}",
                    f"摘要: {item.snippet or '无摘要'}",
                    f"搜索来源: {getattr(item, 'source_provider', 'local')}",
                ]
            )
        )
    return "\n\n".join(lines)


def _is_hosted_web_search_unsupported(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "当前供应商不支持 openai 内置联网搜索" in text
        or "当前供应商不支持工具调用联网搜索" in text
        or ("does not support" in text and "web_search" in text)
        or ("unsupported" in text and "web_search" in text)
        or ("unsupported" in text and "tool" in text)
        or ("不支持" in text and "工具" in text)
    )


def _message_text_for_token_budget(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif item.get("type") == "image_url":
                parts.append("[image]")
        return "\n".join(parts)
    return str(content or "")


def _estimate_message_tokens(message: dict) -> int:
    text = _message_text_for_token_budget(message)
    role = str(message.get("role") or "")
    return max(1, (len(text) + len(role)) // 4 + 4)


def _trim_messages_for_context_budget(messages: list[dict], max_context_tokens: Optional[int]) -> list[dict]:
    if not max_context_tokens or max_context_tokens <= 0:
        return messages
    if not messages:
        return messages

    remaining = max_context_tokens
    selected_reversed: list[dict] = []
    for message in reversed(messages):
        cost = _estimate_message_tokens(message)
        if selected_reversed and cost > remaining:
            continue
        selected_reversed.append(message)
        remaining -= cost
        if remaining <= 0:
            break

    selected_reversed.reverse()
    return selected_reversed or [messages[-1]]


def _normalize_web_search_mode(raw: Optional[str]) -> str:
    mode = (raw or WEB_SEARCH_MODE_AUTO).strip().lower()
    if mode not in _WEB_SEARCH_MODES:
        return WEB_SEARCH_MODE_AUTO
    return mode


def _extract_urls(text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in _URL_PATTERN.findall(text or ""):
        url = match.rstrip(".,);]}>\"'")
        if not url.startswith(("http://", "https://")):
            continue
        key = url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        urls.append(url)
    return urls


def _strip_markdown_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_search_summary_payload(raw_text: str) -> tuple[str, list[dict]]:
    cleaned = _strip_markdown_fences(raw_text)
    candidates = [cleaned]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        candidates.append(cleaned[start : end + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        summary = str(
            data.get("summary")
            or data.get("answer")
            or data.get("content")
            or ""
        ).strip()
        sources_raw = data.get("sources") or data.get("results") or []
        results: list[dict] = []
        for item in sources_raw:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            results.append(
                {
                    "title": str(item.get("title") or url).strip(),
                    "url": url,
                    "snippet": str(item.get("snippet") or "").strip(),
                }
            )
        if summary or results:
            return summary, results[:5]

    urls = _extract_urls(cleaned)
    fallback_results = [
        {"title": url, "url": url, "snippet": ""}
        for url in urls[:5]
    ]
    return cleaned, fallback_results


async def _collect_stream_text(stream: AsyncIterator[str], *, max_chars: int = 16000) -> str:
    parts: list[str] = []
    total = 0
    async for chunk in stream:
        text = str(chunk)
        if not text:
            continue
        parts.append(text)
        total += len(text)
        if total >= max_chars:
            break
    return "".join(parts)


async def _build_provider_search_summary_prompt(
    *,
    query: str,
    db: AsyncSession,
    user_id: int,
    provider_name: Optional[str] = None,
) -> tuple[str, list[dict]]:
    search_provider_name = (provider_name or _DEFAULT_GROK_SEARCH_PROVIDER_NAME).strip()
    search_provider = await AIProviderFactory.create_provider(
        provider_name=search_provider_name,
        db=db,
        scenario="chat_main",
        user_id=user_id,
    )

    if not search_provider.supports_web_search():
        raise ValueError("选定的搜索提供商不支持联网搜索。")

    stream_method = getattr(search_provider, "chat_stream_with_web_search", None)
    if not callable(stream_method):
        raise ValueError("选定的搜索提供商不支持联网搜索。")

    summary_instruction = (
        "你是一名联网研究助手。请先搜索网页，再输出严格 JSON 对象，不要使用 Markdown 代码块。"
        '格式必须是 {"summary":"...","sources":[{"title":"...","url":"...","snippet":"..."}]}。'
        "summary 请用中文简洁总结；sources 保留 2-5 个最重要来源；url 必须是绝对链接。"
    )
    raw_summary = await _collect_stream_text(
        stream_method(
            messages=[{"role": "user", "content": query}],
            system_prompt=summary_instruction,
            temperature=0.1,
        )
    )
    summary, results = _parse_search_summary_payload(raw_summary)
    if not summary and not results:
        raise ValueError("搜索提供商没有返回可用搜索结果。")

    payload_parts: list[str] = []
    if summary:
        payload_parts.append(f"搜索总结:\n{summary}")
    if results:
        payload_parts.append(
            "来源链接:\n"
            + _format_web_search_context(
                [WebSearchResult(**item) for item in results]
            )
        )
    wrapped = wrap_untrusted_context(
        "联网搜索结果（专用搜索提供商总结）",
        "\n\n".join(payload_parts),
        source=f"search_provider:{search_provider_name}",
        max_chars=8000,
    )
    prompt = (
        "\n\n用户开启了联网搜索。下面是由专用搜索提供商联网检索并总结的网页结果。"
        "请优先基于这些结果回答；如果结果不足以支持结论，请明确说明不确定。"
        "引用网页信息时请带上对应 URL。\n"
        f"{wrapped}"
    )
    return prompt, results


def _should_use_provider_web_search(provider, mode: str, search_settings: Optional[dict] = None) -> bool:
    if not provider.supports_web_search():
        return False

    normalized_mode = _normalize_web_search_mode(mode)
    if normalized_mode in {
        WEB_SEARCH_MODE_APP_SEARCH,
        WEB_SEARCH_MODE_GROK_SUMMARY,
        WEB_SEARCH_MODE_TAVILY,
        WEB_SEARCH_MODE_LOCAL_FALLBACK,
    }:
        return False
    if normalized_mode == WEB_SEARCH_MODE_AUTO and search_settings:
        if (
            search_settings.get("enabled")
            and search_settings.get("tavily_api_key")
            and search_settings.get("provider") in {"auto", "tavily"}
        ):
            return False
    return True


async def _build_external_web_search_prompt(
    query: str,
    *,
    db: Optional[AsyncSession] = None,
    user_id: Optional[int] = None,
    mode: str = WEB_SEARCH_MODE_AUTO,
) -> tuple[str, list[dict]]:
    settings_data: Optional[dict] = None
    if db is not None and user_id is not None:
        try:
            settings_data = await get_search_settings_dict(db, user_id)
        except Exception:
            settings_data = None

    if settings_data:
        if mode == WEB_SEARCH_MODE_TAVILY:
            settings_data["enabled"] = True
            settings_data["provider"] = "tavily"
        elif mode in {WEB_SEARCH_MODE_APP_SEARCH, WEB_SEARCH_MODE_LOCAL_FALLBACK}:
            settings_data["enabled"] = True
            settings_data["provider"] = "local_fallback"
    settings = (
        SearchProviderSettings(
            **{
                key: value
                for key, value in (settings_data or {}).items()
                if key in SearchProviderSettings.__dataclass_fields__
            }
        )
        if settings_data
        else None
    )
    results = await search_web(query, limit=5, settings=settings)
    if not results:
        return "", []

    payload = _format_web_search_context(results)
    wrapped = wrap_untrusted_context(
        "联网搜索结果",
        payload,
        source="external_web_search",
        max_chars=6000,
    )
    prompt = (
        "\n\n用户开启了联网搜索，但当前模型供应商没有内置搜索工具。"
        "下面是 Mnemox 代为检索到的网页搜索结果。请优先基于这些结果回答；"
        "如果结果不足或无法支持结论，请明确说明不确定。引用网页信息时请带上对应 URL。\n"
        f"{wrapped}"
    )
    event_results = [
        {
            "title": item.title,
            "url": item.url,
            "snippet": item.snippet,
            "source_provider": getattr(item, "source_provider", "local"),
            "score": getattr(item, "score", None),
            "published_date": getattr(item, "published_date", None),
        }
        for item in results
    ]
    return prompt, event_results

# ---- SSE streaming endpoint ----

@router.post("/send")
async def chat_send(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发送消息并以 SSE 流式返回 AI 回复"""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")

    # Verify conversation ownership if conversation_id is provided
    if body.conversation_id:
        conv_check = await db.execute(
            select(ChatConversation).where(
                ChatConversation.id == body.conversation_id,
                ChatConversation.user_id == current_user.id,
            )
        )
        if not conv_check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="对话不存在")

    # 合并手动选择的资料 ID（兼容旧的 material_id 字段）
    manual_ids: List[int] = list(body.material_ids or [])
    if body.material_id and body.material_id not in manual_ids:
        manual_ids.append(body.material_id)

    system_prompt, detected, auto_selected = await _resolve_materials_and_build_prompt(
        message=body.message,
        manual_ids=manual_ids,
        conversation_id=body.conversation_id,
        db=db,
        user_id=current_user.id,
        chat_mode=body.chat_mode or "normal",
    )

    # Fetch memory indicators for SSE
    memory_indicators = []
    try:
        memory_indicators = await get_relevant_memories(db, topic=body.message, limit=5, user_id=current_user.id)
    except Exception:
        memory_indicators = []
    messages = []
    if body.history:
        for msg in body.history:
            messages.append({"role": msg.role, "content": msg.content})

    # 构建用户消息（支持图片）
    if body.image_data and len(body.image_data) > 0:
        content_parts = [{"type": "text", "text": body.message}]
        for img_b64 in body.image_data:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}"}
            })
        messages.append({"role": "user", "content": content_parts})
    else:
        messages.append({"role": "user", "content": body.message})

    # 获取当前激活的 AI 提供商
    try:
        provider = await AIProviderFactory.create_provider(
            provider_name=body.provider_name,
            model=body.model,
            db=db,
            scenario="chat_main",
            user_id=current_user.id,
        )
    except Exception as e:
        if _is_ai_configuration_error(e):
            raise _ai_configuration_error(e)
        raise HTTPException(
            status_code=500,
            detail=f"无法创建 AI 提供商：{str(e)}",
        )

    messages = _trim_messages_for_context_budget(
        messages,
        getattr(provider, "max_context_tokens", None),
    )

    # 用于收集完整回复以便保存
    collected_reply = []
    user_id = current_user.id

    try:
        await db.rollback()
    except Exception:
        logger.warning("释放流式对话请求数据库会话失败", exc_info=True)

    async def event_stream():
        # 先发送自动命中的资料信息（标题匹配 + 项目资料 + 读取资料库意图）
        merged_detected = []
        seen_ids = set()
        for item in detected + auto_selected:
            if item["id"] in seen_ids:
                continue
            seen_ids.add(item["id"])
            merged_detected.append(item)

        if merged_detected:
            det_data = json.dumps(
                {"type": "materials_detected", "materials": merged_detected},
                ensure_ascii=False,
            )
            yield f"data: {det_data}\n\n"

        # Emit memory indicators
        if memory_indicators:
            mem_data = json.dumps(
                {"type": "memory_indicators", "memories": memory_indicators},
                ensure_ascii=False,
            )
            yield f"data: {mem_data}\n\n"

        try:
            effective_system_prompt = system_prompt
            web_search_mode = _normalize_web_search_mode(body.web_search_mode)
            search_settings = None
            if body.web_search_enabled:
                try:
                    search_settings = await get_search_settings_dict(db, current_user.id)
                except Exception:
                    search_settings = None
            use_hosted_web_search = False
            if body.web_search_enabled and web_search_mode == WEB_SEARCH_MODE_GROK_SUMMARY:
                try:
                    web_prompt, web_results = await _build_provider_search_summary_prompt(
                        query=body.message,
                        db=db,
                        user_id=current_user.id,
                        provider_name=body.web_search_provider_name,
                    )
                    if web_prompt:
                        effective_system_prompt = f"{system_prompt or ''}{web_prompt}"
                        yield f"data: {json.dumps({'type': 'web_search_results', 'results': web_results}, ensure_ascii=False)}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'web_search_results', 'results': []}, ensure_ascii=False)}\n\n"
                except Exception as exc:
                    logger.warning("专用搜索提供商联网失败，降级为应用层网页搜索: %s", exc)
                    notice = "专用搜索提供商暂时不可用，已降级为应用层联网搜索。"
                    yield f"data: {json.dumps({'type': 'web_search_notice', 'message': notice}, ensure_ascii=False)}\n\n"
                    web_prompt, web_results = await _build_external_web_search_prompt(
                        body.message,
                        db=db,
                        user_id=current_user.id,
                        mode=web_search_mode,
                    )
                    if web_prompt:
                        effective_system_prompt = f"{system_prompt or ''}{web_prompt}"
                    yield f"data: {json.dumps({'type': 'web_search_results', 'results': web_results}, ensure_ascii=False)}\n\n"
            elif body.web_search_enabled and _should_use_provider_web_search(provider, web_search_mode, search_settings):
                use_hosted_web_search = True
            elif body.web_search_enabled:
                try:
                    web_prompt, web_results = await _build_external_web_search_prompt(
                        body.message,
                        db=db,
                        user_id=current_user.id,
                        mode=web_search_mode,
                    )
                    if web_prompt:
                        effective_system_prompt = f"{system_prompt or ''}{web_prompt}"
                        yield f"data: {json.dumps({'type': 'web_search_results', 'results': web_results}, ensure_ascii=False)}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'web_search_results', 'results': []}, ensure_ascii=False)}\n\n"
                except Exception as exc:
                    logger.warning("外部联网搜索失败，降级为普通聊天: %s", exc)
                    notice = "联网搜索暂时失败，已降级为普通聊天。请检查网络后重试。"
                    effective_system_prompt = (
                        f"{system_prompt or ''}\n\n"
                        f"注意：用户开启了联网搜索，但应用层网页搜索失败：{format_ai_provider_error(exc)}。"
                        "请不要声称已经查询了最新网页；如果问题依赖实时信息，请说明无法确认。"
                    )
                    yield f"data: {json.dumps({'type': 'web_search_notice', 'message': notice}, ensure_ascii=False)}\n\n"

            try:
                stream_method = (
                    getattr(provider, "chat_stream_with_web_search")
                    if use_hosted_web_search
                    else provider.chat_stream
                )
                async for chunk in stream_method(
                    messages=messages,
                    system_prompt=effective_system_prompt,
                    temperature=0.7,
                ):
                    collected_reply.append(chunk)
                    # SSE format: data: ...\n\n
                    data = json.dumps({"content": chunk}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
            except Exception as exc:
                if not (body.web_search_enabled and use_hosted_web_search and _is_hosted_web_search_unsupported(exc)):
                    raise

                logger.info("联网搜索工具不可用，切换到应用层网页搜索: %s", exc)
                collected_reply.clear()
                web_prompt, web_results = await _build_external_web_search_prompt(
                    body.message,
                    db=db,
                    user_id=current_user.id,
                    mode=web_search_mode,
                )
                fallback_system_prompt = f"{system_prompt or ''}{web_prompt}" if web_prompt else system_prompt
                yield f"data: {json.dumps({'type': 'web_search_results', 'results': web_results}, ensure_ascii=False)}\n\n"
                async for chunk in provider.chat_stream(
                    messages=messages,
                    system_prompt=fallback_system_prompt,
                    temperature=0.7,
                ):
                    collected_reply.append(chunk)
                    data = json.dumps({"content": chunk}, ensure_ascii=False)
                    yield f"data: {data}\n\n"

            # Detect progress feedback before persistence and final success.
            full_reply = "".join(collected_reply)
            try:
                feedback = await detect_progress_feedback(body.message, full_reply, db)
                if feedback:
                    fb_data = json.dumps(
                        {"type": "progress_feedback", "feedback": feedback},
                        ensure_ascii=False,
                    )
                    yield f"data: {fb_data}\n\n"
            except Exception:
                pass

            try:
                await _persist_streamed_chat_turn(
                    body=body,
                    full_reply=full_reply,
                    user_id=user_id,
                )
            except Exception:
                error_data = json.dumps(
                    {"error": "AI 回复已生成，但消息保存失败。请重试，本次回复未确认持久化。"},
                    ensure_ascii=False,
                )
                yield f"data: {error_data}\n\n"
                yield "data: [DONE]\n\n"
                return

            # 保存成功后再发送结束标记，避免前端误判为可恢复成功。
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.exception("流式 AI 回复失败: conversation_id=%s user_id=%s", body.conversation_id, user_id)
            error_text = format_ai_provider_error(e)
            if "API Key 不正确或没有权限" in error_text:
                error_text = (
                    f"{error_text} "
                    "请打开 AI 提供商设置，检查当前供应商的 API Key、Base URL，并先搜索模型后选择一个模型进行验证。"
                )
            error_data = json.dumps({"error": f"AI 回复失败：{error_text}"}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"
            yield "data: [DONE]\n\n"
            return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---- Non-streaming fallback ----

class ChatResponse(BaseModel):
    reply: str
    detected_materials: Optional[List[dict]] = None


@router.post("/send-sync", response_model=ChatResponse)
async def chat_send_sync(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发送消息并一次性返回 AI 回复（非流式）"""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")

    # Verify conversation ownership if conversation_id is provided
    if body.conversation_id:
        conv_check = await db.execute(
            select(ChatConversation).where(
                ChatConversation.id == body.conversation_id,
                ChatConversation.user_id == current_user.id,
            )
        )
        if not conv_check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="对话不存在")

    # 合并手动选择的资料 ID
    manual_ids: List[int] = list(body.material_ids or [])
    if body.material_id and body.material_id not in manual_ids:
        manual_ids.append(body.material_id)

    system_prompt, detected, auto_selected = await _resolve_materials_and_build_prompt(
        message=body.message,
        manual_ids=manual_ids,
        conversation_id=body.conversation_id,
        db=db,
        user_id=current_user.id,
        chat_mode=body.chat_mode or "normal",
    )

    messages = []
    if body.history:
        for msg in body.history:
            messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": body.message})

    try:
        provider = await AIProviderFactory.create_provider(
            provider_name=body.provider_name,
            model=body.model,
            db=db,
            scenario="chat_main",
            user_id=current_user.id,
        )
    except Exception as e:
        if _is_ai_configuration_error(e):
            raise _ai_configuration_error(e)
        raise HTTPException(
            status_code=500,
            detail=f"无法创建 AI 提供商：{str(e)}",
        )

    messages = _trim_messages_for_context_budget(
        messages,
        getattr(provider, "max_context_tokens", None),
    )

    if body.web_search_enabled:
        raise HTTPException(
            status_code=400,
            detail="联网搜索目前仅支持流式对话接口。",
        )

    try:
        reply = await provider.chat(
            messages=messages,
            system_prompt=system_prompt,
            temperature=0.7,
        )
        merged_detected = []
        seen_ids = set()
        for item in detected + auto_selected:
            if item["id"] in seen_ids:
                continue
            seen_ids.add(item["id"])
            merged_detected.append(item)

        return ChatResponse(
            reply=reply,
            detected_materials=merged_detected if merged_detected else None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 回复失败：{format_ai_provider_error(e)}")
