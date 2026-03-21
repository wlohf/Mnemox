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
    """Generate a daily plan combining due reviews, pending tasks, overdue items, and wrong questions.

    target_date: YYYY-MM-DD
    """
    try:
        target = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD")

    now = datetime.now()
    items = []

    # 1. Due ReviewSchedules (priority 100+)
    review_result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.scheduled_date <= now,
            ReviewSchedule.status == "pending",
            ReviewSchedule.user_id == current_user.id,
        )
    )
    reviews = review_result.scalars().all()

    # Batch preload related objects to avoid N+1
    chapter_item_ids = [r.item_id for r in reviews if r.item_type == "chapter"]
    question_item_ids = [r.item_id for r in reviews if r.item_type == "question"]
    reflection_item_ids = [r.item_id for r in reviews if r.item_type == "reflection"]

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

    mem_map = {}
    if reflection_item_ids:
        try:
            from app.models.memory import UserMemory
            mem_result = await db.execute(select(UserMemory).where(UserMemory.id.in_(reflection_item_ids)))
            mem_map = {m.id: m for m in mem_result.scalars().all()}
        except Exception:
            pass

    for r in reviews:
        label = ""
        if r.item_type == "chapter":
            ch = chapter_map.get(r.item_id)
            label = f"章节复习：{ch.title}" if ch else f"章节复习 #{r.item_id}"
        elif r.item_type == "question":
            wq = wq_map.get(r.item_id)
            if wq:
                q = question_map.get(wq.question_id)
                label = f"错题复习：{(q.content or '')[:40]}" if q else f"错题复习 #{r.item_id}"
            else:
                label = f"复习任务 #{r.item_id}"
        elif r.item_type == "reflection":
            mem = mem_map.get(r.item_id)
            label = f"纠正理解：{(mem.memory_value or '')[:40]}" if mem else f"反思复习 #{r.item_id}"

        emoji = "🔍" if r.item_type == "reflection" else "📖"
        items.append({
            "type": "review",
            "emoji": emoji,
            "label": label,
            "priority": 100 + (10 if r.item_type == "question" else 0),
            "id": r.id,
        })

    # 2. Planned Tasks for this date (priority 80) - only tasks belonging to user's goals
    task_result = await db.execute(
        select(Task)
        .join(Goal, Task.goal_id == Goal.id)
        .where(
            Task.planned_date == target,
            Task.status.in_(["pending", "in_progress"]),
            Goal.user_id == current_user.id,
        )
    )
    planned_tasks = task_result.scalars().all()
    for t in planned_tasks:
        items.append({
            "type": "task",
            "emoji": "📝",
            "label": t.title,
            "priority": 80,
            "id": t.id,
        })

    # 3. Overdue Tasks (priority 90+)
    overdue_result = await db.execute(
        select(Task)
        .join(Goal, Task.goal_id == Goal.id)
        .where(
            Task.planned_date < target,
            Task.status.in_(["pending", "in_progress"]),
            Goal.user_id == current_user.id,
        )
    )
    overdue_tasks = overdue_result.scalars().all()
    # Exclude already-added planned tasks
    planned_ids = {t.id for t in planned_tasks}
    for t in overdue_tasks:
        if t.id in planned_ids:
            continue
        days_overdue = (target - t.planned_date).days if t.planned_date else 0
        items.append({
            "type": "overdue",
            "emoji": "⚠️",
            "label": f"[逾期{days_overdue}天] {t.title}",
            "priority": 90 + min(days_overdue, 10),
            "id": t.id,
        })

    # 4. Due WrongQuestions (priority 70)
    wq_result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.next_review_at <= now,
            WrongQuestion.mastery_status != "mastered",
            WrongQuestion.user_id == current_user.id,
        )
    )
    due_wrongs = wq_result.scalars().all()
    # Avoid duplicates with review items already added
    review_wq_ids = {r.item_id for r in reviews if r.item_type == "question"}

    # Batch load questions for due wrong questions
    due_wq_question_ids = [wq.question_id for wq in due_wrongs if wq.id not in review_wq_ids]
    due_question_map = {}
    if due_wq_question_ids:
        dq_result = await db.execute(select(Question).where(Question.id.in_(due_wq_question_ids)))
        due_question_map = {q.id: q for q in dq_result.scalars().all()}

    for wq in due_wrongs:
        if wq.id in review_wq_ids:
            continue
        q = due_question_map.get(wq.question_id)
        label = f"错题重练：{(q.content or '')[:40]}" if q else f"错题重练 #{wq.id}"
        items.append({
            "type": "wrong_retry",
            "emoji": "❌",
            "label": label,
            "priority": 70,
            "id": wq.id,
        })

    # 5. Reflection misconceptions from episodic memory (priority 60)
    try:
        from app.models.memory import UserMemory
        mem_result = await db.execute(
            select(UserMemory).where(
                UserMemory.category == "weakness",
                UserMemory.status == "active",
                UserMemory.user_id == current_user.id,
            ).limit(5)
        )
        episodic_weaknesses = mem_result.scalars().all()
        for mem in episodic_weaknesses:
            mem_type = getattr(mem, "memory_type", "semantic") or "semantic"
            if mem_type != "episodic":
                continue
            items.append({
                "type": "reflection_review",
                "emoji": "🧠",
                "label": f"回顾薄弱点：{(mem.memory_value or '')[:40]}",
                "priority": 60,
                "id": mem.id,
            })
    except Exception:
        pass  # Non-blocking

    # Sort by priority descending
    items.sort(key=lambda x: x["priority"], reverse=True)

    # Format as markdown checklist
    lines = [f"# {target_date} 学习计划", ""]
    if not items:
        lines.append("今日暂无待办事项，可以自由学习！ 🎉")
    else:
        for item in items:
            lines.append(f"- [ ] {item['emoji']} {item['label']}")

    content = "\n".join(lines)

    # Save to daily_plans table
    result = await db.execute(
        select(DailyPlan).where(DailyPlan.date == target_date, DailyPlan.user_id == current_user.id)
    )
    row = result.scalar_one_or_none()
    existing_content = row.content if row else ""
    was_manually_edited = False

    if row is None:
        row = DailyPlan(user_id=current_user.id, date=target_date, content=content)
        db.add(row)
    else:
        # 检查是否已手动编辑（内容不为空且不以自动生成的标题开头）
        auto_header = f"# {target_date} 学习计划"
        if existing_content and not existing_content.strip().startswith(auto_header):
            # 已手动编辑，将自动生成内容追加到末尾而非覆盖
            was_manually_edited = True
            merged = existing_content.rstrip() + "\n\n---\n\n" + content
            row.content = merged
        else:
            row.content = content

    await db.commit()

    return {
        "date": target_date,
        "content": row.content,
        "item_count": len(items),
        "items": items,
        "was_merged": was_manually_edited,
    }


@router.get("/{date}", response_model=PlanResponse)
async def get_plan(
    date: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取某一天的计划。
    date: YYYY-MM-DD
    """

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
    """
    新建/更新某一天的计划。
    """

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
    """
    按日期区间拉取计划（闭区间）。

    说明：date 字段为 YYYY-MM-DD 字符串，字符串比较可直接用于区间过滤。
    """

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
