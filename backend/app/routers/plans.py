"""日历计划路由：支持按天读写、按区间拉取（用于本周计划）。"""

from datetime import datetime, date, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.daily_plan import DailyPlan
from app.models.goal import Goal, Task
from app.models.question import ReviewSchedule, WrongQuestion, Question
from app.models.material import Chapter
from app.auth import get_current_user
from app.models.user import User


router = APIRouter()

_MAX_REVIEWS = 3
_MAX_TASKS = 5
_MAX_OVERDUE = 2
_MAX_WRONGS = 2


class PlanUpsertRequest(BaseModel):
    content: str = Field(default="", description="计划/记录内容（markdown 或纯文本）")


class PlanResponse(BaseModel):
    date: str
    content: str


@router.post("/generate/{target_date}")
async def generate_daily_plan(
    target_date: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a focused daily plan with a limited number of items per category."""
    try:
        target = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD")

    now = datetime.now()
    items = []

    # 1. Due ReviewSchedules — limit to most urgent
    review_result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.scheduled_date <= now,
            ReviewSchedule.status == "pending",
            ReviewSchedule.user_id == current_user.id,
            ReviewSchedule.is_archived == False,
        ).order_by(ReviewSchedule.scheduled_date.asc()).limit(_MAX_REVIEWS)
    )
    reviews = review_result.scalars().all()

    chapter_item_ids = [r.item_id for r in reviews if r.item_type == "chapter"]
    question_item_ids = [r.item_id for r in reviews if r.item_type == "question"]

    chapter_map = {}
    if chapter_item_ids:
        ch_result = await db.execute(select(Chapter).where(Chapter.id.in_(chapter_item_ids)))
        chapter_map = {c.id: c for c in ch_result.scalars().all()}

    wq_map = {}
    if question_item_ids:
        wq_result = await db.execute(select(WrongQuestion).where(WrongQuestion.id.in_(question_item_ids)))
        wq_map = {wq.id: wq for wq in wq_result.scalars().all()}

    wq_question_ids = [wq.question_id for wq in wq_map.values()]
    question_map = {}
    if wq_question_ids:
        q_result = await db.execute(select(Question).where(Question.id.in_(wq_question_ids)))
        question_map = {q.id: q for q in q_result.scalars().all()}

    for r in reviews:
        if r.item_type == "chapter":
            ch = chapter_map.get(r.item_id)
            label = f"章节复习：{ch.title}" if ch else f"章节复习 #{r.item_id}"
        elif r.item_type == "question":
            wq = wq_map.get(r.item_id)
            q = question_map.get(wq.question_id) if wq else None
            label = f"错题复习：{(q.content or '')[:30]}" if q else f"错题复习 #{r.item_id}"
        else:
            label = f"复习任务 #{r.item_id}"
        items.append({"emoji": "📖", "label": label, "priority": 100})

    # 2. Planned Tasks for this date
    task_result = await db.execute(
        select(Task)
        .join(Goal, Task.goal_id == Goal.id)
        .where(
            Task.planned_date == target,
            Task.status.in_(["pending", "in_progress"]),
            Goal.user_id == current_user.id,
        ).limit(_MAX_TASKS)
    )
    for t in task_result.scalars().all():
        items.append({"emoji": "📝", "label": t.title, "priority": 80})

    # 3. Overdue Tasks — only most recent
    overdue_result = await db.execute(
        select(Task)
        .join(Goal, Task.goal_id == Goal.id)
        .where(
            Task.planned_date < target,
            Task.status.in_(["pending", "in_progress"]),
            Goal.user_id == current_user.id,
        ).order_by(Task.planned_date.desc()).limit(_MAX_OVERDUE)
    )
    for t in overdue_result.scalars().all():
        days_overdue = (target - t.planned_date).days if t.planned_date else 0
        items.append({"emoji": "⚠️", "label": f"[逾期{days_overdue}天] {t.title}", "priority": 90})

    # 4. Due WrongQuestions (deduplicated)
    review_wq_ids = {r.item_id for r in reviews if r.item_type == "question"}
    wq_due_result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.next_review_at <= now,
            WrongQuestion.mastery_status != "mastered",
            WrongQuestion.user_id == current_user.id,
            WrongQuestion.id.notin_(review_wq_ids),
        ).limit(_MAX_WRONGS)
    )
    for wq in wq_due_result.scalars().all():
        q = question_map.get(wq.question_id)
        label = f"错题重练：{(q.content or '')[:30]}" if q else f"错题重练 #{wq.id}"
        items.append({"emoji": "❌", "label": label, "priority": 70})

    # Try AI summary if available
    ai_intro = ""
    try:
        from app.services.ai_client import get_ai_client
        client = await get_ai_client(db, current_user.id)
        if client and items:
            item_list = "\n".join(f"- {i['emoji']} {i['label']}" for i in items)
            prompt = (
                f"今天是{target_date}，以下是学生今日待办事项：\n{item_list}\n\n"
                "请用1-2句话给出简短、温暖的学习建议，帮助学生轻松开始今天的学习。不要列清单，只给建议。"
            )
            resp = await client.chat(prompt, max_tokens=80)
            if resp:
                ai_intro = resp.strip()
    except Exception:
        pass

    lines = [f"# {target_date} 学习计划", ""]
    if ai_intro:
        lines += [f"> 💡 {ai_intro}", ""]
    if not items:
        lines.append("今日暂无待办，自由学习吧！🎉")
    else:
        for item in sorted(items, key=lambda x: x["priority"], reverse=True):
            lines.append(f"- [ ] {item['emoji']} {item['label']}")

    content = "\n".join(lines)

    result = await db.execute(
        select(DailyPlan).where(DailyPlan.date == target_date, DailyPlan.user_id == current_user.id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = DailyPlan(user_id=current_user.id, date=target_date, content=content)
        db.add(row)
    else:
        row.content = content

    await db.commit()
    return {"date": target_date, "content": row.content, "item_count": len(items)}


@router.get("/{date}", response_model=PlanResponse)
async def get_plan(
    date: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DailyPlan).where(DailyPlan.date == date, DailyPlan.user_id == current_user.id)
    )
    row = result.scalar_one_or_none()
    return PlanResponse(date=date, content=row.content if row else "")


@router.put("/{date}", response_model=PlanResponse)
async def upsert_plan(
    date: str,
    body: PlanUpsertRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DailyPlan).where(DailyPlan.date == date, DailyPlan.user_id == current_user.id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = DailyPlan(user_id=current_user.id, date=date, content=body.content or "")
        db.add(row)
    else:
        row.content = body.content or ""

    await db.commit()
    return PlanResponse(date=date, content=row.content)


@router.get("/", response_model=list[PlanResponse])
async def list_plans(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if start > end:
        raise HTTPException(status_code=400, detail="start 不能大于 end")

    result = await db.execute(
        select(DailyPlan).where(
            DailyPlan.date >= start,
            DailyPlan.date <= end,
            DailyPlan.user_id == current_user.id,
        ).order_by(DailyPlan.date.asc())
    )
    rows = result.scalars().all()
    return [PlanResponse(date=r.date, content=r.content) for r in rows]
