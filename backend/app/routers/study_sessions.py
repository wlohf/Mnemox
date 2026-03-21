"""学习会话路由（任务闭环）"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.session import StudySession, Conversation
from app.models.goal import Goal, Task
from app.models.question import ReviewSchedule
from app.auth import get_current_user
from app.models.user import User

router = APIRouter()


class StartSessionRequest(BaseModel):
    task_id: int
    session_type: Optional[str] = "new_learning"


class AddMessageRequest(BaseModel):
    role: str
    content: str
    message_type: Optional[str] = None


class CompleteSessionRequest(BaseModel):
    summary: Optional[str] = None
    ai_feedback: Optional[str] = None
    mark_task_completed: bool = True


def _session_item(s: StudySession) -> dict:
    return {
        "id": s.id,
        "task_id": s.task_id,
        "chapter_id": s.chapter_id,
        "session_type": s.session_type,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        "summary": s.summary,
        "ai_feedback": s.ai_feedback,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.post("/start")
async def start_session(
    body: StartSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify task exists and belongs to a goal owned by the current user
    task_result = await db.execute(select(Task).where(Task.id == body.task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # Check that the parent goal belongs to current user
    goal_result = await db.execute(
        select(Goal).where(Goal.id == task.goal_id, Goal.user_id == current_user.id)
    )
    if not goal_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="任务不存在")

    # 若已有进行中的会话，直接复用
    active_result = await db.execute(
        select(StudySession).where(
            StudySession.task_id == body.task_id,
            StudySession.ended_at.is_(None),
            StudySession.user_id == current_user.id,
        )
    )
    active = active_result.scalar_one_or_none()
    if active:
        return _session_item(active)

    now = datetime.now()
    session = StudySession(
        user_id=current_user.id,
        task_id=task.id,
        chapter_id=task.chapter_id,
        session_type=body.session_type or "new_learning",
        started_at=now,
    )
    db.add(session)

    # 启动学习会话时，任务至少应处于进行中
    if task.status == "pending":
        task.status = "in_progress"

    await db.flush()
    await db.refresh(session)
    return _session_item(session)


@router.post("/{session_id}/messages")
async def add_session_message(
    session_id: int,
    body: AddMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.role not in ("user", "assistant"):
        raise HTTPException(status_code=400, detail="role 仅支持 user/assistant")

    session_result = await db.execute(
        select(StudySession).where(
            StudySession.id == session_id,
            StudySession.user_id == current_user.id,
        )
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在")

    msg = Conversation(
        session_id=session_id,
        role=body.role,
        content=body.content,
        message_type=body.message_type,
    )
    db.add(msg)
    await db.flush()
    return {
        "id": msg.id,
        "session_id": msg.session_id,
        "role": msg.role,
        "content": msg.content,
        "message_type": msg.message_type,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.post("/{session_id}/complete")
async def complete_session(
    session_id: int,
    body: CompleteSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session_result = await db.execute(
        select(StudySession).where(
            StudySession.id == session_id,
            StudySession.user_id == current_user.id,
        )
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在")

    if session.ended_at is not None:
        return _session_item(session)

    now = datetime.now()
    session.ended_at = now
    if body.summary is not None:
        session.summary = body.summary
    if body.ai_feedback is not None:
        session.ai_feedback = body.ai_feedback

    # 若未传 summary，自动从会话消息提炼简要总结
    if not session.summary:
        msg_result = await db.execute(
            select(Conversation)
            .where(Conversation.session_id == session_id)
            .order_by(Conversation.id.desc())
            .limit(12)
        )
        msgs = list(reversed(msg_result.scalars().all()))
        user_msgs = [m.content for m in msgs if m.role == "user"]
        ai_msgs = [m.content for m in msgs if m.role == "assistant"]
        if user_msgs:
            summary = "；".join([m[:60] for m in user_msgs[-3:]])
            if ai_msgs:
                summary += f"。AI建议：{ai_msgs[-1][:100]}"
            session.summary = summary[:500]

    if body.mark_task_completed and session.task_id:
        task_result = await db.execute(select(Task).where(Task.id == session.task_id))
        task = task_result.scalar_one_or_none()
        if task:
            task.status = "completed"
            task.completed_at = now

    # Auto-create ReviewSchedule for the chapter if applicable
    if session.chapter_id:
        try:
            existing_review = await db.execute(
                select(ReviewSchedule).where(
                    ReviewSchedule.item_type == "chapter",
                    ReviewSchedule.item_id == session.chapter_id,
                    ReviewSchedule.status == "pending",
                    ReviewSchedule.user_id == current_user.id,
                )
            )
            if not existing_review.scalar_one_or_none():
                review = ReviewSchedule(
                    user_id=current_user.id,
                    item_type="chapter",
                    item_id=session.chapter_id,
                    scheduled_date=now + timedelta(days=1),
                    interval_days=1,
                    ease_factor=250,
                    repetitions=0,
                    status="pending",
                )
                db.add(review)
        except Exception:
            pass  # Non-blocking

    await db.flush()
    await db.refresh(session)
    return _session_item(session)


@router.get("/task/{task_id}")
async def list_task_sessions(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(StudySession)
        .where(StudySession.task_id == task_id, StudySession.user_id == current_user.id)
        .order_by(StudySession.started_at.desc())
    )
    return [_session_item(s) for s in result.scalars().all()]


@router.get("/active")
async def list_active_sessions(
    task_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(StudySession).where(
        StudySession.ended_at.is_(None),
        StudySession.user_id == current_user.id,
    )
    if task_id is not None:
        query = query.where(StudySession.task_id == task_id)
    query = query.order_by(StudySession.started_at.desc())

    result = await db.execute(query)
    return [_session_item(s) for s in result.scalars().all()]
