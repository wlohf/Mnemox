"""复习任务路由（基于 review_schedule）"""
import logging
from datetime import datetime, timedelta
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.question import Question, ReviewSchedule, WrongQuestion
from app.models.material import Chapter, Material
from app.auth import get_current_user
from app.models.user import User
from app.services.review_scheduler import apply_review
from app.services.learning_event_service import (
    record_review_completed_event,
    record_review_scheduled_event,
)
from app.services.projection_outbox_service import process_event_projection
from app.utils.prompt_safety import wrap_untrusted_context

router = APIRouter()
logger = logging.getLogger(__name__)


class ReviewCompleteRequest(BaseModel):
    quality: int  # 0-5


class ChapterEnqueueRequest(BaseModel):
    scheduled_date: Optional[datetime] = None


def _calc_mastery_status(quality: int) -> str:
    if quality >= 4:
        return "mastered"
    if quality >= 2:
        return "partial"
    return "not_mastered"


async def _sync_wrong_questions_to_review_schedule(db: AsyncSession, user_id: int) -> list[ReviewSchedule]:
    """增量同步：只为尚无 ReviewSchedule 的错题创建任务，避免全量遍历 N+1。"""
    # 子查询：已有 review schedule 的错题 ID
    existing_subq = (
        select(ReviewSchedule.item_id)
        .where(
            ReviewSchedule.item_type == "question",
            ReviewSchedule.user_id == user_id,
        )
        .scalar_subquery()
    )
    # 只查没有对应 ReviewSchedule 的错题
    result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.id.notin_(existing_subq),
        )
    )
    new_items = result.scalars().all()
    now = datetime.now()

    created: list[ReviewSchedule] = []
    for wq in new_items:
        next_time = wq.next_review_at or now
        task = ReviewSchedule(
            user_id=user_id,
            item_type="question",
            item_id=wq.id,
            scheduled_date=next_time,
            interval_days=1,
            ease_factor=250,
            repetitions=wq.review_count or 0,
            status="pending",
        )
        db.add(task)
        created.append(task)
    return created

async def _sync_chapters_to_review_schedule(db: AsyncSession, user_id: int) -> list[ReviewSchedule]:
    """增量同步：只为尚无 ReviewSchedule 的章节创建任务，避免全量遍历 N+1。"""
    from app.models.material import Material
    # 子查询：已有 review schedule 的章节 ID
    existing_subq = (
        select(ReviewSchedule.item_id)
        .where(
            ReviewSchedule.item_type == "chapter",
            ReviewSchedule.user_id == user_id,
        )
        .scalar_subquery()
    )
    # 只查没有对应 ReviewSchedule 的章节
    result = await db.execute(
        select(Chapter)
        .join(Material, Chapter.material_id == Material.id)
        .where(
            Material.user_id == user_id,
            Chapter.id.notin_(existing_subq),
        )
    )
    new_chapters = result.scalars().all()
    now = datetime.now()

    created: list[ReviewSchedule] = []
    for chapter in new_chapters:
        mastery = float(chapter.mastery_level or 0)
        default_time = now if mastery < 60 else now + timedelta(days=3)
        task = ReviewSchedule(
            user_id=user_id,
            item_type="chapter",
            item_id=chapter.id,
            scheduled_date=default_time,
            interval_days=3,
            ease_factor=250,
            repetitions=0,
            status="pending",
        )
        db.add(task)
        created.append(task)
    return created

def _to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return None


def _to_task_item(
    task: ReviewSchedule,
    wrong: Optional[WrongQuestion] = None,
    chapter: Optional[Chapter] = None,
) -> dict:
    content = ""
    chapter_title = "未分类"
    mastery_status = "not_mastered"
    wrong_count = 0
    review_count = 0

    if wrong:
        question = wrong.__dict__.get("question")
        if question:
            content = question.content or ""
            chapter = question.__dict__.get("chapter")
            chapter_title = chapter.title if chapter else "未分类"
        mastery_status = wrong.mastery_status or "not_mastered"
        wrong_count = wrong.wrong_count or 0
        review_count = wrong.review_count or 0
    elif chapter:
        content = chapter.title or "章节复习"
        chapter_title = chapter.title or "未分类"
        level = float(chapter.mastery_level or 0)
        if level >= 80:
            mastery_status = "mastered"
        elif level >= 50:
            mastery_status = "partial"
        else:
            mastery_status = "not_mastered"

    return {
        "task_id": task.id,
        "item_type": task.item_type,
        "item_id": task.item_id,
        "scheduled_date": _to_iso(getattr(task, "scheduled_date", None)),
        "interval_days": task.interval_days,
        "ease_factor": task.ease_factor,
        "repetitions": task.repetitions,
        "status": task.status,
        "content": content,
        "chapter_title": chapter_title,
        "mastery_status": mastery_status,
        "wrong_count": wrong_count,
        "review_count": review_count,
        "chapter_mastery_level": float(getattr(chapter, "mastery_level", 0) or 0) if chapter else None,
        "last_wrong_at": _to_iso(getattr(wrong, "last_wrong_at", None)) if wrong else None,
        "next_review_at": _to_iso(getattr(wrong, "next_review_at", None)) if wrong else None,
    }


@router.get("/due-count")
async def get_due_review_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return count of due review items for badge display."""
    now = datetime.now()
    result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.scheduled_date <= now,
            ReviewSchedule.status == "pending",
            ReviewSchedule.user_id == current_user.id,
            ReviewSchedule.is_archived == False,
        )
    )
    due_items = result.scalars().all()
    return {"due_count": len(due_items)}


@router.get("/tasks")
async def list_review_tasks(
    scope: str = Query("due", pattern="^(due|all)$"),
    item_type: str = Query("all", pattern="^(all|question|chapter)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    created_schedules = await _sync_wrong_questions_to_review_schedule(db, user_id=current_user.id)
    created_schedules.extend(await _sync_chapters_to_review_schedule(db, user_id=current_user.id))
    if created_schedules:
        await db.flush()
        for schedule in created_schedules:
            await record_review_scheduled_event(
                db,
                int(current_user.id),
                entity_type="review_schedule",
                entity_id=int(schedule.id),
                due_at=schedule.scheduled_date,
                source="review_router",
                item_type=schedule.item_type,
                item_id=schedule.item_id,
                reason="initial_sync",
            )

    now = datetime.now()
    query = select(ReviewSchedule).where(ReviewSchedule.user_id == current_user.id, ReviewSchedule.is_archived == False)
    if item_type != "all":
        query = query.where(ReviewSchedule.item_type == item_type)
    if scope == "due":
        query = query.where(ReviewSchedule.scheduled_date <= now)
    query = query.order_by(ReviewSchedule.scheduled_date.asc()).offset(skip).limit(limit)

    result = await db.execute(query)
    tasks = result.scalars().all()

    # Batch preload wrong_questions and chapters to avoid N+1
    question_item_ids = [t.item_id for t in tasks if t.item_type == "question"]
    chapter_item_ids = [t.item_id for t in tasks if t.item_type == "chapter"]

    wq_map = {}
    if question_item_ids:
        wq_result = await db.execute(
            select(WrongQuestion)
            .options(selectinload(WrongQuestion.question).selectinload(Question.chapter))
            .where(
                WrongQuestion.id.in_(question_item_ids),
                WrongQuestion.user_id == current_user.id,
            )
        )
        wq_map = {wq.id: wq for wq in wq_result.scalars().all()}

    ch_map = {}
    if chapter_item_ids:
        ch_result = await db.execute(
            select(Chapter)
            .join(Material, Chapter.material_id == Material.id)
            .where(
                Chapter.id.in_(chapter_item_ids),
                Material.user_id == current_user.id,
            )
        )
        ch_map = {c.id: c for c in ch_result.scalars().all()}

    out = []
    for task in tasks:
        if task.item_type == "question":
            wrong = wq_map.get(task.item_id)
            out.append(_to_task_item(task, wrong=wrong))
        elif task.item_type == "chapter":
            chapter = ch_map.get(task.item_id)
            out.append(_to_task_item(task, chapter=chapter))
    return out


@router.post("/tasks/{task_id}/complete")
async def complete_review_task(
    task_id: int,
    body: ReviewCompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.quality < 0 or body.quality > 5:
        raise HTTPException(status_code=400, detail="quality 必须在 0-5")

    task_result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.id == task_id,
            ReviewSchedule.user_id == current_user.id,
        )
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="复习任务不存在")

    task_type = str(getattr(task, "item_type", ""))
    if task_type not in ("question", "chapter"):
        raise HTTPException(status_code=400, detail="暂不支持该任务类型")

    now = datetime.now()
    scheduled_for = task.scheduled_date or now
    schedule = apply_review(task, body.quality, now, due_attr="scheduled_date")
    next_review_at = schedule.due_at

    # 更新复习计划（公共部分）
    task.completed_at = now
    task.status = "pending"

    if task_type == "chapter":
        chapter_result = await db.execute(
            select(Chapter)
            .join(Material, Chapter.material_id == Material.id)
            .where(Chapter.id == task.item_id, Material.user_id == current_user.id)
        )
        chapter = chapter_result.scalar_one_or_none()
        if not chapter:
            raise HTTPException(status_code=404, detail="关联章节不存在")

        delta_map = {
            0: -8,
            1: -4,
            2: 0,
            3: 6,
            4: 10,
            5: 14,
        }
        delta = delta_map.get(body.quality, 0)
        level = float(chapter.mastery_level or 0)
        chapter.mastery_level = max(0.0, min(100.0, level + delta))

        await db.flush()
        await db.refresh(task)
        await db.refresh(chapter)
        completed_event = await record_review_completed_event(
            db,
            int(current_user.id),
            entity_type="review_schedule",
            entity_id=int(task.id),
            scheduled_for=scheduled_for,
            source="review_router",
            quality=body.quality,
            item_type=task.item_type,
            item_id=task.item_id,
            next_due_at=schedule.due_at,
            scheduler=schedule.algorithm,
            occurred_at=now,
        )
        await process_event_projection(
            db,
            user_id=int(current_user.id),
            source_event_id=int(completed_event["id"]),
        )
        await record_review_scheduled_event(
            db,
            int(current_user.id),
            entity_type="review_schedule",
            entity_id=int(task.id),
            due_at=schedule.due_at,
            source="review_router",
            item_type=task.item_type,
            item_id=task.item_id,
            reason="review_completed",
            occurred_at=now,
        )
        return _to_task_item(task, chapter=chapter)

    wrong_result = await db.execute(
        select(WrongQuestion)
        .options(selectinload(WrongQuestion.question).selectinload(Question.chapter))
        .where(
            WrongQuestion.id == task.item_id,
            WrongQuestion.user_id == current_user.id,
        )
    )
    wrong = wrong_result.scalar_one_or_none()
    if not wrong:
        raise HTTPException(status_code=404, detail="关联错题不存在")

    # 更新错题
    wrong.review_count = (wrong.review_count or 0) + 1
    wrong.mastery_status = _calc_mastery_status(body.quality)
    wrong.next_review_at = next_review_at

    await db.flush()
    await db.refresh(task)
    await db.refresh(wrong)

    completed_event = await record_review_completed_event(
        db,
        int(current_user.id),
        entity_type="review_schedule",
        entity_id=int(task.id),
        scheduled_for=scheduled_for,
        source="review_router",
        quality=body.quality,
        item_type=task.item_type,
        item_id=task.item_id,
        next_due_at=schedule.due_at,
        scheduler=schedule.algorithm,
        concept_id=wrong.concept_id,
        occurred_at=now,
    )
    await process_event_projection(
        db,
        user_id=int(current_user.id),
        source_event_id=int(completed_event["id"]),
    )
    await record_review_scheduled_event(
        db,
        int(current_user.id),
        entity_type="review_schedule",
        entity_id=int(task.id),
        due_at=schedule.due_at,
        source="review_router",
        item_type=task.item_type,
        item_id=task.item_id,
        reason="review_completed",
        occurred_at=now,
    )

    return _to_task_item(task, wrong)


@router.delete("/tasks/{task_id}")
async def delete_review_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除复习任务"""
    result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.id == task_id,
            ReviewSchedule.user_id == current_user.id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="复习任务不存在")
    task.is_archived = True
    await db.flush()
    return {"ok": True}


@router.post("/tasks/chapter/{chapter_id}/enqueue")
async def enqueue_chapter_review_task(
    chapter_id: int,
    body: ChapterEnqueueRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    chapter_result = await db.execute(
        select(Chapter).join(Material, Chapter.material_id == Material.id).where(
            Chapter.id == chapter_id, Material.user_id == current_user.id
        )
    )
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    task_result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.item_type == "chapter",
            ReviewSchedule.item_id == chapter_id,
            ReviewSchedule.user_id == current_user.id,
        )
    )
    task = task_result.scalar_one_or_none()
    when = body.scheduled_date or datetime.now()

    if not task:
        task = ReviewSchedule(
            user_id=current_user.id,
            item_type="chapter",
            item_id=chapter_id,
            scheduled_date=when,
            interval_days=1,
            ease_factor=250,
            repetitions=0,
            status="pending",
        )
        db.add(task)
    else:
        task.scheduled_date = when
        task.status = "pending"

    await db.flush()
    await db.refresh(task)
    await db.refresh(chapter)
    await record_review_scheduled_event(
        db,
        int(current_user.id),
        entity_type="review_schedule",
        entity_id=int(task.id),
        due_at=task.scheduled_date or when,
        source="review_router",
        item_type=task.item_type,
        item_id=task.item_id,
        reason="manual_enqueue",
    )
    return _to_task_item(task, chapter=chapter)


# ============ AI 复习评估 API ============

class ReviewContentResponse(BaseModel):
    summary: List[str]
    questions: List[dict]


class ReviewSubmitRequest(BaseModel):
    answers: List[dict]


@router.get("/{task_id}/content")
async def get_review_content(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取复习内容：AI生成的知识点总结和检验题目"""
    # Get review task
    task_result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.id == task_id,
            ReviewSchedule.user_id == current_user.id,
        )
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="复习任务不存在")
    
    # Get chapter content
    if task.item_type != "chapter":
        raise HTTPException(status_code=400, detail="暂只支持章节复习的AI评估")
    
    chapter_result = await db.execute(
        select(Chapter, Material)
        .join(Material, Chapter.material_id == Material.id)
        .where(
            Chapter.id == task.item_id,
            Material.user_id == current_user.id,
        )
    )
    row = chapter_result.first()
    if not row:
        raise HTTPException(status_code=404, detail="章节不存在")
    chapter, _material = row
    
    chapter_block = wrap_untrusted_context(
        "章节内容",
        f"章节标题：{chapter.title}\n章节内容：\n{chapter.content or '（无详细内容）'}",
        source=f"chapter:{chapter.id}",
    )
    prompt = f"""你是一位专业的学习助手。用户正在复习以下章节：

{chapter_block}

请生成：
1. 该章节的核心知识点总结（3-5条，每条一句话）
2. 2-3道检验题目，用于测试用户对该章节的掌握程度

返回JSON格式：
{{
  "summary": ["知识点1", "知识点2", "知识点3"],
  "questions": [
    {{
      "id": 1,
      "type": "choice",
      "question": "题目内容",
      "options": ["A. 选项1", "B. 选项2", "C. 选项3", "D. 选项4"],
      "correct_answer": "A"
    }},
    {{
      "id": 2,
      "type": "short_answer",
      "question": "简答题内容",
      "reference_answer": "参考答案"
    }}
  ]
}}

注意：
- 知识点要简洁明了
- 题目要有针对性，能真正检验理解程度
- 选择题要有明确的正确答案
- 简答题要提供参考答案用于评分
"""
    
    try:
        from app.ai.factory import AIProviderFactory

        provider = await AIProviderFactory.create_provider(
            db=db,
            scenario="review",
            user_id=current_user.id,
        )
        response = await provider.chat([{"role": "user", "content": prompt}])
        
        # Parse JSON from response
        import json
        import re
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        
        data = json.loads(text)
        
        return {
            "summary": data.get("summary", []),
            "questions": data.get("questions", []),
        }
    except Exception as e:
        logger.warning("AI 复习内容生成失败: %s", e)
        # Fallback if AI fails
        return {
            "summary": [
                f"复习章节：{chapter.title}",
                "请回顾该章节的核心概念和关键知识点",
                "尝试用自己的话总结章节内容",
            ],
            "questions": [
                {
                    "id": 1,
                    "type": "short_answer",
                    "question": f"请简要总结「{chapter.title}」的核心内容",
                    "reference_answer": "（AI生成失败，请自行评估）",
                }
            ],
        }


@router.post("/{task_id}/submit")
async def submit_review_answers(
    task_id: int,
    body: ReviewSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交复习答案，AI评估并返回分数"""
    # Get review task
    task_result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.id == task_id,
            ReviewSchedule.user_id == current_user.id,
        )
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="复习任务不存在")
    
    if task.item_type != "chapter":
        raise HTTPException(status_code=400, detail="暂只支持章节复习的AI评估")

    # Get chapter
    chapter_result = await db.execute(
        select(Chapter, Material)
        .join(Material, Chapter.material_id == Material.id)
        .where(
            Chapter.id == task.item_id,
            Material.user_id == current_user.id,
        )
    )
    row = chapter_result.first()
    if not row:
        raise HTTPException(status_code=404, detail="章节不存在")
    chapter, _material = row
    
    answers_text = "\n".join([
        f"问题{i+1}：{ans.get('question', '')}\n用户答案：{ans.get('answer', '')}"
        for i, ans in enumerate(body.answers)
    ])
    
    quiz_block = wrap_untrusted_context(
        "章节内容与答题记录",
        (
            f"章节标题：{chapter.title}\n"
            f"章节内容：\n{chapter.content or '（无详细内容）'}\n\n"
            f"用户的答题情况：\n{answers_text}"
        ),
        source=f"chapter:{chapter.id}",
    )
    prompt = f"""你是一位专业的学习评估专家。用户刚完成了章节复习测验。

{quiz_block}

请评估用户的掌握程度，返回JSON格式：
{{
  "score": 85,
  "quality": 4,
  "feedback": "整体掌握良好，但在XX方面还需加强..."
}}

评分标准：
- score: 0-100分，综合评估答题质量
- quality: 0-5分，用于间隔重复算法（0=完全不会，3=一般，5=非常熟练）
- feedback: 简短反馈（1-2句话）

注意：
- 评分要客观公正
- quality要根据score转换：score>=90→5, >=80→4, >=60→3, >=40→2, >=20→1, <20→0
"""
    
    try:
        from app.ai.factory import AIProviderFactory

        provider = await AIProviderFactory.create_provider(
            db=db,
            scenario="review",
            user_id=current_user.id,
        )
        response = await provider.chat([{"role": "user", "content": prompt}])
        
        import json
        import re
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        
        data = json.loads(text)
        score = max(0, min(100, int(data.get("score", 60))))
        quality = max(0, min(5, int(data.get("quality", 3))))
        feedback = data.get("feedback", "")
        
    except Exception as e:
        logger.warning("AI 复习答案评估失败: %s", e)
        # Fallback scoring
        score = 60
        quality = 3
        feedback = "评估完成，建议继续复习巩固"
    
    # 更新复习调度（FSRS 优先，SM-2 兜底）
    now = datetime.now()
    scheduled_for = task.scheduled_date or now
    schedule = apply_review(task, quality, now, due_attr="scheduled_date")
    task.completed_at = now
    task.status = "pending"

    # Update chapter mastery
    old_mastery = float(chapter.mastery_level or 0)
    new_mastery = old_mastery * 0.7 + score * 0.3
    chapter.mastery_level = new_mastery

    await db.flush()
    completed_event = await record_review_completed_event(
        db,
        int(current_user.id),
        entity_type="review_schedule",
        entity_id=int(task.id),
        scheduled_for=scheduled_for,
        source="review_router",
        quality=quality,
        item_type=task.item_type,
        item_id=task.item_id,
        next_due_at=schedule.due_at,
        scheduler=schedule.algorithm,
        normalized_score=score / 100.0,
        occurred_at=now,
    )
    await process_event_projection(
        db,
        user_id=int(current_user.id),
        source_event_id=int(completed_event["id"]),
    )
    await record_review_scheduled_event(
        db,
        int(current_user.id),
        entity_type="review_schedule",
        entity_id=int(task.id),
        due_at=schedule.due_at,
        source="review_router",
        item_type=task.item_type,
        item_id=task.item_id,
        reason="review_completed",
        occurred_at=now,
    )

    return {
        "score": score,
        "quality": quality,
        "feedback": feedback,
        "next_review_date": schedule.due_at.isoformat(),
    }
