"""AI 对话路由"""
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import List, Optional, cast

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

from app.config import settings
from app.auth import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)


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
    "【教练模式 / Socratic Method】\n"
    "你是一位苏格拉底式学习教练。你必须严格遵守以下规则：\n"
    "1. **绝不直接给出答案**。用引导式提问帮助用户自己思考和发现答案。\n"
    "2. 当用户提问时，先反问：'你目前对这个概念的理解是什么？'或类似的引导问题。\n"
    "3. 当用户尝试解释时，用 1-5 分评估其理解程度，并指出哪里正确、哪里需要改进。\n"
    "4. 使用费曼技巧：要求用户'用自己的话解释给一个初学者听'。\n"
    "5. 提供渐进式提示（Progressive Hints）：从抽象到具体，逐步引导。\n"
    "6. 如果用户多次答错，可以给出部分线索，但仍要让用户完成最后一步推理。\n"
    "7. 每次回复结尾附上一个思考问题，保持对话推进。\n"
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


async def _load_materials(ids: List[int], db: AsyncSession) -> List[dict]:
    """根据 ID 列表加载资料内容，返回 [{"title": str, "content": str}, ...]"""
    if not ids:
        return []
    result = await db.execute(select(Material).where(Material.id.in_(ids)))
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
) -> str:
    """构建 RAG 感知的系统提示词。

    小资料（< SMALL_MATERIAL_THRESHOLD 字符）全文注入；
    大资料使用 RAG 语义检索 top-k chunk。
    如果 RAG 不可用，回退到全文截断注入。
    """
    if not material_ids:
        return BASE_SYSTEM_PROMPT

    materials_data = await _load_materials(material_ids, db)
    if not materials_data:
        return BASE_SYSTEM_PROMPT

    threshold = settings.SMALL_MATERIAL_THRESHOLD

    small_materials = [m for m in materials_data if len(m["content"]) <= threshold]
    large_materials = [m for m in materials_data if len(m["content"]) > threshold]

    prompt = (
        f"{BASE_SYSTEM_PROMPT}\n\n"
        f"用户当前正在学习以下资料，请基于资料内容回答问题：\n"
    )

    # 小资料：全文注入
    for i, mat in enumerate(small_materials):
        prompt += f"\n--- 资料：{mat['title']} ---\n"
        prompt += mat["content"] + "\n"

    # 大资料：RAG 检索
    if large_materials and settings.RAG_ENABLED:
        try:
            rag = get_rag_service()
            large_ids = [m["id"] for m in large_materials]
            chunks = await rag.retrieve(query=message, material_ids=large_ids)
            if chunks:
                prompt += "\n--- 以下为 RAG 语义检索到的相关资料片段 ---\n"
                for chunk in chunks:
                    prompt += f"\n[来源：{chunk['material_title']}（相关度 {chunk['score']:.2f}）]\n"
                    prompt += chunk["text"] + "\n"
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
        parts.append(f"\n--- 资料：{mat['title']} ---\n{content}\n")

    text = "".join(parts)
    if truncated:
        text += "（注意：资料内容较长，以上仅为部分内容）\n"
    text += "--- 资料内容结束 ---\n"
    return text


async def _get_material_briefs(ids: List[int], db: AsyncSession) -> List[dict]:
    """返回资料简要信息，供前端展示自动命中的资料标签。"""
    if not ids:
        return []

    result = await db.execute(
        select(Material.id, Material.title).where(Material.id.in_(ids))
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
            select(ChatConversation).where(ChatConversation.id == conversation_id)
        )
        conv = conv_result.scalar_one_or_none()
        if conv and conv.project_id:
            project_id = conv.project_id
            assoc_result = await db.execute(
                select(ChatProjectMaterial.material_id).where(
                    ChatProjectMaterial.project_id == conv.project_id
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
            auto_selected.extend(await _get_material_briefs(project_material_ids, db))

    # 自动注入：读取资料库意图
    if not all_ids and _looks_like_read_materials_intent(message):
        recent_ids = await _get_recent_material_ids(db, user_id=user_id, project_id=project_id)
        for rid in recent_ids:
            if rid not in all_ids:
                all_ids.append(rid)
        if recent_ids:
            auto_selected.extend(await _get_material_briefs(recent_ids, db))

    # 构建 RAG 感知的系统提示
    system_prompt = await _build_system_prompt_with_rag(message, all_ids, db)

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
            select(ChatConversation).where(ChatConversation.id == conversation_id)
        )
        conv = conv_result.scalar_one_or_none()
        if conv and conv.project_id:
            proj_result = await db.execute(
                select(ChatProject).where(ChatProject.id == conv.project_id)
            )
            proj = proj_result.scalar_one_or_none()
            if proj and proj.default_instructions:
                system_prompt += f"\n\n项目指令：{proj.default_instructions}"

    # 注入用户学习画像（个性化建议上下文）
    try:
        from app.services.profile_service import get_or_compute_profile, build_profile_prompt_snippet
        _profile = await get_or_compute_profile(db, user_id)
        _snippet = build_profile_prompt_snippet(_profile)
        if _snippet:
            system_prompt += "\n\n" + _snippet
    except Exception as _pe:
        logger.warning("用户画像注入失败: %s", _pe)

    return system_prompt, detected, auto_selected


async def _get_project_material_ids(conversation_id: int, db: AsyncSession) -> List[int]:
    """获取对话所属项目绑定的资料 ID 列表。"""
    conv_result = await db.execute(
        select(ChatConversation).where(ChatConversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv or not conv.project_id:
        return []

    assoc_result = await db.execute(
        select(ChatProjectMaterial.material_id).where(
            ChatProjectMaterial.project_id == conv.project_id
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
        provider = await AIProviderFactory.create_provider(db=db, scenario="chat_main", user_id=current_user.id)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"无法创建 AI 提供商：{str(e)}。请在设置中配置 API Key。",
        )

    # 用于收集完整回复以便保存
    collected_reply = []
    user_id = current_user.id

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
            async for chunk in provider.chat_stream(
                messages=messages,
                system_prompt=system_prompt,
                temperature=0.7,
            ):
                collected_reply.append(chunk)
                # SSE format: data: ...\n\n
                data = json.dumps({"content": chunk}, ensure_ascii=False)
                yield f"data: {data}\n\n"

            # Detect progress feedback before sending [DONE]
            full_reply = "".join(collected_reply)
            try:
                from app.services.memory_service import detect_progress_feedback
                feedback = await detect_progress_feedback(body.message, full_reply, db)
                if feedback:
                    fb_data = json.dumps(
                        {"type": "progress_feedback", "feedback": feedback},
                        ensure_ascii=False,
                    )
                    yield f"data: {fb_data}\n\n"
            except Exception:
                pass

            # 发送结束标记
            yield "data: [DONE]\n\n"
        except Exception as e:
            error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"
            yield "data: [DONE]\n\n"

        # 流结束后保存消息到数据库
        # 使用独立 session 避免依赖注入 session 生命周期不匹配
        full_reply = "".join(collected_reply)
        if (body.conversation_id or body.study_session_id) and full_reply:
            from app.database import async_session_maker
            async with async_session_maker() as save_db:
                try:
                    if body.conversation_id:
                        # 保存用户消息
                        user_msg = ChatMessageModel(
                            conversation_id=body.conversation_id,
                            role="user",
                            content=body.message,
                            image_data=json.dumps(body.image_data, ensure_ascii=False) if body.image_data else None,
                        )
                        save_db.add(user_msg)

                        # 保存 AI 回复
                        ai_msg = ChatMessageModel(
                            conversation_id=body.conversation_id,
                            role="assistant",
                            content=full_reply,
                        )
                        save_db.add(ai_msg)

                        # 自动设置标题
                        conv_result2 = await save_db.execute(
                            select(ChatConversation).where(ChatConversation.id == body.conversation_id)
                        )
                        conv2 = conv_result2.scalar_one_or_none()
                        if conv2 and conv2.title == "新对话":
                            conv2.title = body.message[:50]

                        # 记忆沉淀
                        await upsert_conversation_summary(body.conversation_id, save_db, user_id=user_id)
                        await upsert_user_memories_from_turn(body.conversation_id, body.message, full_reply, save_db, user_id=user_id)

                        # Conversation Reflection (gated: every ~5 user turns)
                        try:
                            from app.services.memory_service import run_conversation_reflection
                            await run_conversation_reflection(body.conversation_id, save_db, user_id=user_id)
                        except Exception as e:
                            logger.warning("对话反思失败: %s", e)

                        # Auto-detect wrong questions from chat
                        try:
                            await _detect_and_create_wrong_questions(
                                body.message, full_reply, body.conversation_id, save_db,
                                user_id=user_id,
                            )
                        except Exception:
                            pass  # Non-blocking

                        # 记录学习事件：AI 对话轮次
                        try:
                            from app.services.event_tracker import EventTracker as _ET
                            from app.models.learning_event import EventType as _EVT
                            _tracker = _ET(save_db, user_id=cast(int, cast(object, user_id)))
                            await _tracker.track(
                                event_type=_EVT.AI_QUESTION_ASKED,
                                event_data={
                                    "conversation_id": body.conversation_id,
                                    "message_len": len(body.message),
                                    "reply_len": len(full_reply),
                                    "chat_mode": body.chat_mode or "normal",
                                },
                                session_id=str(body.conversation_id) if body.conversation_id else None,
                            )
                        except Exception as _e:
                            logger.warning("学习事件追踪失败: %s", _e)

                    # 同步写入学习会话对话（用于 Task-Session 闭环）
                    if body.study_session_id:
                        sess_result = await save_db.execute(
                            select(StudySession).where(StudySession.id == body.study_session_id)
                        )
                        sess = sess_result.scalar_one_or_none()
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
            db=db,
            scenario="chat_main",
            user_id=current_user.id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"无法创建 AI 提供商：{str(e)}。请在设置中配置 API Key。",
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
        raise HTTPException(status_code=500, detail=f"AI 回复失败：{str(e)}")
