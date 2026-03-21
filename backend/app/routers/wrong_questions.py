"""错题本与复习中心路由"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.material import Material, Chapter
from app.models.question import Question, WrongQuestion, ReviewSchedule
from app.auth import get_current_user
from app.models.user import User
from app.services.event_tracker import EventTracker
from app.models.learning_event import EventType

router = APIRouter()


class WrongQuestionCreate(BaseModel):
    content: str
    chapter_id: Optional[int] = None
    question_type: Optional[str] = "short_answer"
    answer: Optional[str] = None
    explanation: Optional[str] = None
    difficulty: Optional[int] = 2
    user_answer: Optional[str] = None


class WrongQuestionUpdate(BaseModel):
    mastery_status: Optional[str] = None
    next_review_at: Optional[datetime] = None
    increment_review_count: bool = False


class WrongQuestionReview(BaseModel):
    quality: int  # 0-5


async def _ensure_default_chapter(db: AsyncSession, user_id: int) -> int:
    chapter_result = await db.execute(
        select(Chapter).join(Material, Chapter.material_id == Material.id).where(Material.user_id == user_id).limit(1)
    )
    chapter = chapter_result.scalar_one_or_none()
    if chapter:
        return chapter.id

    material_result = await db.execute(
        select(Material).where(Material.user_id == user_id).limit(1)
    )
    material = material_result.scalar_one_or_none()
    if not material:
        material = Material(
            user_id=user_id,
            title="默认资料",
            file_type="text",
            content="系统自动创建的默认资料，用于承载未分类错题。",
        )
        db.add(material)
        await db.flush()

    chapter = Chapter(
        material_id=material.id,
        title="未分类",
        content="系统自动创建章节",
        order_index=0,
    )
    db.add(chapter)
    await db.flush()
    return chapter.id


def _to_item(wq: WrongQuestion) -> dict:
    q = wq.question
    chapter_title = q.chapter.title if q and q.chapter else "未分类"
    return {
        "id": wq.id,
        "question_id": wq.question_id,
        "content": q.content if q else "",
        "question_type": q.question_type if q else None,
        "answer": q.answer if q else None,
        "explanation": q.explanation if q else None,
        "difficulty": q.difficulty if q else None,
        "chapter_id": q.chapter_id if q else None,
        "chapter_title": chapter_title,
        "wrong_count": wq.wrong_count,
        "mastery_status": wq.mastery_status,
        "review_count": wq.review_count,
        "next_review_at": wq.next_review_at.isoformat() if wq.next_review_at else None,
        "last_wrong_at": wq.last_wrong_at.isoformat() if wq.last_wrong_at else None,
        "created_at": wq.created_at.isoformat() if wq.created_at else None,
    }


@router.get("")
async def list_wrong_questions(
    mastery_status: Optional[str] = None,
    due_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 在 SQL 层直接过滤，避免加载全部数据到内存
    query = select(WrongQuestion).where(WrongQuestion.user_id == current_user.id)
    if mastery_status:
        query = query.where(WrongQuestion.mastery_status == mastery_status)
    if due_only:
        now = datetime.now()
        query = query.where(
            WrongQuestion.next_review_at.isnot(None),
            WrongQuestion.next_review_at <= now,
        )
    query = query.order_by(WrongQuestion.last_wrong_at.desc().nullslast())
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()
    return [_to_item(i) for i in items]


@router.post("")
async def create_wrong_question(
    body: WrongQuestionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    chapter_id = body.chapter_id or await _ensure_default_chapter(db, user_id=current_user.id)

    question = Question(
        user_id=current_user.id,
        chapter_id=chapter_id,
        question_type=body.question_type,
        content=body.content,
        answer=body.answer,
        explanation=body.explanation,
        difficulty=body.difficulty or 2,
    )
    db.add(question)
    await db.flush()

    now = datetime.now()
    wrong = WrongQuestion(
        user_id=current_user.id,
        question_id=question.id,
        first_wrong_at=now,
        last_wrong_at=now,
        wrong_count=1,
        mastery_status="not_mastered",
        next_review_at=now,
        review_count=0,
    )
    db.add(wrong)
    await db.flush()

    # Auto-create ReviewSchedule for this wrong question (due immediately)
    try:
        review = ReviewSchedule(
            user_id=current_user.id,
            item_type="question",
            item_id=wrong.id,
            scheduled_date=now,
            interval_days=1,
            ease_factor=250,
            repetitions=0,
            status="pending",
        )
        db.add(review)
        await db.flush()
    except Exception:
        pass  # Non-blocking

    await db.refresh(wrong)

    # 记录学习事件：新增错题
    try:
        tracker = EventTracker(db, user_id=current_user.id)
        await tracker.track(
            event_type=EventType.QUESTION_WRONG,
            event_category="practice",
            event_data={
                "wrong_question_id": wrong.id,
                "question_type": body.question_type,
                "chapter_id": chapter_id,
            },
        )
    except Exception:
        pass  # 事件追踪不影响主流程

    return _to_item(wrong)


@router.put("/{wrong_question_id}")
async def update_wrong_question(
    wrong_question_id: int,
    body: WrongQuestionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.id == wrong_question_id,
            WrongQuestion.user_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="错题不存在")

    if body.mastery_status is not None:
        item.mastery_status = body.mastery_status
    if body.next_review_at is not None:
        item.next_review_at = body.next_review_at
    if body.increment_review_count:
        item.review_count = (item.review_count or 0) + 1

    await db.flush()
    await db.refresh(item)
    return _to_item(item)


@router.post("/{wrong_question_id}/review")
async def review_wrong_question(
    wrong_question_id: int,
    body: WrongQuestionReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.quality < 0 or body.quality > 5:
        raise HTTPException(status_code=400, detail="quality 必须在 0-5")

    result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.id == wrong_question_id,
            WrongQuestion.user_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="错题不存在")

    # 使用 SM-2 算法（与 review.py 统一）
    from app.routers.review import _sm2_update, _calc_mastery_status

    # 查找或创建关联的 ReviewSchedule
    review_result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.item_type == "question",
            ReviewSchedule.item_id == item.id,
            ReviewSchedule.user_id == current_user.id,
        )
    )
    review_task = review_result.scalar_one_or_none()

    now = datetime.now()
    current_interval = int(getattr(review_task, "interval_days", 1) or 1) if review_task else 1
    current_reps = int(getattr(review_task, "repetitions", 0) or 0) if review_task else 0
    current_ef = int(getattr(review_task, "ease_factor", 250) or 250) if review_task else 250

    days, new_reps, new_ef = _sm2_update(current_interval, current_reps, current_ef, body.quality)
    next_review_at = now + timedelta(days=days)

    # 更新错题本
    item.review_count = (item.review_count or 0) + 1
    item.mastery_status = _calc_mastery_status(body.quality)
    item.next_review_at = next_review_at

    # 同步更新 ReviewSchedule（保持一致性）
    if review_task:
        review_task.repetitions = new_reps
        review_task.last_quality = body.quality
        review_task.interval_days = days
        review_task.ease_factor = new_ef
        review_task.completed_at = now
        review_task.scheduled_date = next_review_at
        review_task.status = "pending"
    else:
        # 不存在则创建
        new_review = ReviewSchedule(
            user_id=current_user.id,
            item_type="question",
            item_id=item.id,
            scheduled_date=next_review_at,
            interval_days=days,
            ease_factor=new_ef,
            repetitions=new_reps,
            last_quality=body.quality,
            status="pending",
        )
        db.add(new_review)

    await db.flush()
    await db.refresh(item)

    # 记录学习事件：复习答题
    try:
        tracker = EventTracker(db, user_id=current_user.id)
        event_type = EventType.QUESTION_CORRECT if body.quality >= 4 else (
            EventType.QUESTION_ANSWERED if body.quality >= 2 else EventType.QUESTION_WRONG
        )
        await tracker.track(
            event_type=event_type,
            event_category="review",
            event_data={
                "wrong_question_id": wrong_question_id,
                "quality": body.quality,
                "new_interval_days": days,
                "mastery_status": item.mastery_status,
            },
        )
    except Exception:
        pass  # 事件追踪不影响主流程

    return _to_item(item)


@router.delete("/{wrong_question_id}")
async def delete_wrong_question(
    wrong_question_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.id == wrong_question_id,
            WrongQuestion.user_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="错题不存在")

    # 级联删除关联的 ReviewSchedule（复习中心的复习任务）
    from sqlalchemy import delete
    await db.execute(
        delete(ReviewSchedule).where(
            ReviewSchedule.item_type == "question",
            ReviewSchedule.item_id == item.id,
            ReviewSchedule.user_id == current_user.id,
        )
    )

    await db.delete(item)
    return {"ok": True}
