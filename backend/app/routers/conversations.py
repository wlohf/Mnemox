"""对话管理路由"""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, or_, func
from pydantic import BaseModel
from typing import Optional, List

from app.database import get_db
from app.models.chat import ChatConversation, ChatMessage
from app.auth import get_current_user
from app.models.user import User

router = APIRouter()


# ---- Schemas ----

class ConversationCreate(BaseModel):
    title: Optional[str] = "新对话"
    project_id: Optional[int] = None


class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    project_id: Optional[int] = None
    is_pinned: Optional[bool] = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    image_data: Optional[List[str]] = None
    created_at: str

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    id: int
    title: str
    project_id: Optional[int] = None
    is_pinned: bool
    summary: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ConversationDetail(ConversationOut):
    messages: List[MessageOut] = []


# ---- Endpoints ----

@router.get("")
async def list_conversations(
    project_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出对话（支持按项目筛选和关键词搜索）"""
    query = select(ChatConversation).where(ChatConversation.user_id == current_user.id)

    if project_id is not None:
        query = query.where(ChatConversation.project_id == project_id)

    if search:
        # 搜索对话标题或消息内容
        keyword = f"%{search}%"
        query = query.outerjoin(ChatMessage).where(
            or_(
                ChatConversation.title.ilike(keyword),
                ChatMessage.content.ilike(keyword),
            )
        ).distinct()

    query = query.order_by(desc(ChatConversation.is_pinned), desc(ChatConversation.updated_at))
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    conversations = result.scalars().all()

    out = []
    keyword = (search or "").strip()
    for c in conversations:
        matched_preview = None
        if keyword:
            msg_result = await db.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == c.id,
                    ChatMessage.content.ilike(f"%{keyword}%"),
                )
                .order_by(ChatMessage.id.desc())
                .limit(1)
            )
            m = msg_result.scalar_one_or_none()
            if m and m.content:
                text = m.content.replace("\n", " ").strip()
                idx = text.lower().find(keyword.lower())
                if idx >= 0:
                    start = max(0, idx - 20)
                    end = min(len(text), idx + len(keyword) + 40)
                    matched_preview = text[start:end]
                else:
                    matched_preview = text[:60]

        out.append(
            {
                "id": c.id,
                "title": c.title,
                "project_id": c.project_id,
                "is_pinned": c.is_pinned,
                "summary": c.summary,
                "matched_preview": matched_preview,
                "created_at": str(c.created_at or ""),
                "updated_at": str(c.updated_at or ""),
            }
        )

    return out


@router.post("")
async def create_conversation(
    body: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新对话"""
    conv = ChatConversation(
        user_id=current_user.id,
        title=body.title or "新对话",
        project_id=body.project_id,
    )
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    return {
        "id": conv.id,
        "title": conv.title,
        "project_id": conv.project_id,
        "is_pinned": conv.is_pinned,
        "created_at": str(conv.created_at or ""),
        "updated_at": str(conv.updated_at or ""),
    }


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: int,
    limit: int = Query(100, ge=1, le=500, description="消息数量限制"),
    offset: int = Query(0, ge=0, description="消息偏移量"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取对话详情（含消息，支持分页）"""
    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 添加分页支持，避免长对话加载过多消息
    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.id)
        .limit(limit)
        .offset(offset)
    )
    messages = msg_result.scalars().all()
    
    # 获取消息总数用于前端分页
    count_result = await db.execute(
        select(func.count(ChatMessage.id)).where(ChatMessage.conversation_id == conversation_id)
    )
    total_messages = count_result.scalar() or 0

    return {
        "id": conv.id,
        "title": conv.title,
        "project_id": conv.project_id,
        "is_pinned": conv.is_pinned,
        "summary": conv.summary,
        "created_at": str(conv.created_at or ""),
        "updated_at": str(conv.updated_at or ""),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "image_data": json.loads(m.image_data) if m.image_data else None,
                "created_at": str(m.created_at or ""),
            }
            for m in messages
        ],
        "total_messages": total_messages,
        "limit": limit,
        "offset": offset,
    }


@router.put("/{conversation_id}")
async def update_conversation(
    conversation_id: int,
    body: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新对话"""
    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    fields_set = getattr(body, "model_fields_set", getattr(body, "__fields_set__", set()))

    if body.title is not None:
        conv.title = body.title
    if "project_id" in fields_set:
        conv.project_id = body.project_id
    if body.is_pinned is not None:
        conv.is_pinned = body.is_pinned

    await db.flush()
    await db.refresh(conv)
    return {
        "id": conv.id,
        "title": conv.title,
        "project_id": conv.project_id,
        "is_pinned": conv.is_pinned,
        "created_at": str(conv.created_at or ""),
        "updated_at": str(conv.updated_at or ""),
    }


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除对话及其消息"""
    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    await db.delete(conv)
    return {"ok": True}
