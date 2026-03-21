"""复习任务路由（基于 review_schedule）"""
from datetime import datetime, timedelta
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.question import ReviewSchedule, WrongQuestion
from app.models.material import Chapter, Material
from app.auth import get_current_user
from app.models.user import User

router = APIRouter()


class ReviewCompleteRequest(BaseModel):
    quality: int  # 0-5


class ChapterEnqueueRequest(BaseModel):
    scheduled_date: Optional[datetime] = None


def _sm2_update(interval_days: int, repetitions: int, ease_factor_scaled: int, quality: int):
    """SM-2 更新（ease_factor 使用 *100 的整数存储）。"""
    ef = (ease_factor_scaled or 250) / 100.0

    # 原始 SM-2 EF 更新公式
    ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ef = max(1.3, ef)

    if quality < 3:
        # 低质量复习：重置 repetitions
        new_repetitions = 0
        new_interval = 1
    else:
        if repetitions <= 0:
            new_interval = 1
        elif repetitions == 1:
            new_interval = 6
        else:
            base = interval_days or 1
            new_interval = max(1, int(round(base * ef)))
        new_repetitions = repetitions + 1

    return new_interval, new_repetitions, int(round(ef * 100))


def _calc_mastery_status(quality: int) -> str:
    if quality >= 4:
        return "mastered"
    if quality >= 2:
        return "partial"
    return "not_mastered"


async def _sync_wrong_questions_to_review_schedule(db: AsyncSession, user_id: int) -> None:
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

async def _sync_chapters_to_review_schedule(db: AsyncSession, user_id: int) -> None:
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

    if wrong and wrong.question:
        content = wrong.question.content or ""
        chapter_title = wrong.question.chapter.title if wrong.question.chapter else "未分类"
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
    await _sync_wrong_questions_to_review_schedule(db, user_id=current_user.id)
    await _sync_chapters_to_review_schedule(db, user_id=current_user.id)

    now = datetime.now()
    query = select(ReviewSchedule).where(ReviewSchedule.user_id == current_user.id)
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
        wq_result = await db.execute(select(WrongQuestion).where(WrongQuestion.id.in_(question_item_ids)))
        wq_map = {wq.id: wq for wq in wq_result.scalars().all()}

    ch_map = {}
    if chapter_item_ids:
        ch_result = await db.execute(select(Chapter).where(Chapter.id.in_(chapter_item_ids)))
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
    current_interval = int(getattr(task, "interval_days", 1) or 1)
    current_reps = int(getattr(task, "repetitions", 0) or 0)
    current_ef = int(getattr(task, "ease_factor", 250) or 250)
    days, new_reps, new_ef = _sm2_update(current_interval, current_reps, current_ef, body.quality)
    next_review_at = now + timedelta(days=days)

    # 更新复习计划（公共部分）
    task.repetitions = new_reps
    task.last_quality = body.quality
    task.interval_days = days
    task.completed_at = now
    task.scheduled_date = next_review_at
    task.status = "pending"
    task.ease_factor = new_ef

    if task_type == "chapter":
        chapter_result = await db.execute(
            select(Chapter).where(Chapter.id == task.item_id)
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
        return _to_task_item(task, chapter=chapter)

    wrong_result = await db.execute(
        select(WrongQuestion).where(WrongQuestion.id == task.item_id)
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

    return _to_task_item(task, wrong)


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
    
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == task.item_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # Get material for context
    material_result = await db.execute(select(Material).where(Material.id == chapter.material_id))
    material = material_result.scalar_one_or_none()
    
    # Generate AI content
    from app.ai.factory import AIProviderFactory
    provider = AIProviderFactory.create_provider()
    
    prompt = f"""你是一位专业的学习助手。用户正在复习以下章节：

章节标题：{chapter.title}
章节内容：
{chapter.content or '（无详细内容）'}

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
    
    # Get chapter
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == task.item_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # AI evaluate answers
    from app.ai.factory import AIProviderFactory
    provider = AIProviderFactory.create_provider()
    
    answers_text = "\n".join([
        f"问题{i+1}：{ans.get('question', '')}\n用户答案：{ans.get('answer', '')}"
        for i, ans in enumerate(body.answers)
    ])
    
    prompt = f"""你是一位专业的学习评估专家。用户刚完成了章节「{chapter.title}」的复习测验。

章节内容：
{chapter.content or '（无详细内容）'}

用户的答题情况：
{answers_text}

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
        response = await provider.chat([{"role": "user", "content": prompt}])
        
        import json
        import re
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        
        data = json.loads(text)
        score = int(data.get("score", 60))
        quality = int(data.get("quality", 3))
        feedback = data.get("feedback", "")
        
    except Exception:
        # Fallback scoring
        score = 60
        quality = 3
        feedback = "评估完成，建议继续复习巩固"
    
    # Update review schedule using SM-2
    interval, reps, ef = _sm2_update(
        task.interval_days or 1,
        task.repetitions or 0,
        task.ease_factor or 250,
        quality,
    )
    
    now = datetime.now()
    task.repetitions = reps
    task.last_quality = quality
    task.interval_days = interval
    task.completed_at = now
    task.scheduled_date = now + timedelta(days=interval)
    task.status = "pending"
    task.ease_factor = ef
    
    # Update chapter mastery
    old_mastery = float(chapter.mastery_level or 0)
    new_mastery = old_mastery * 0.7 + score * 0.3
    chapter.mastery_level = new_mastery
    
    await db.flush()
    
    return {
        "score": score,
        "quality": quality,
        "feedback": feedback,
        "next_review_date": (now + timedelta(days=interval)).isoformat(),
    }
