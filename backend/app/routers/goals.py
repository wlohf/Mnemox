"""学习目标与任务路由（MVP）"""
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, and_, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.goal import Goal, Task
from app.models.pomodoro import Pomodoro
from app.models.session import StudySession
from app.models.material import Material, Chapter
from app.auth import get_current_user
from app.models.user import User
from app.services.learning_event_service import record_learning_event
from app.utils.pydantic_compat import provided_model_fields
from app.utils.sync import begin_idempotent_operation, complete_idempotent_operation, flush_sync_mutation, require_matching_version
from app.utils.utc import to_utc_iso, utc_now_db


async def _ensure_user_chapter(db: AsyncSession, chapter_id: int, user_id: int) -> Chapter:
    """章节归属校验：章节必须属于当前用户的资料，否则按不存在处理。"""
    result = await db.execute(
        select(Chapter)
        .join(Material, Chapter.material_id == Material.id)
        .where(Chapter.id == chapter_id, Material.user_id == user_id)
    )
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return chapter

router = APIRouter()


class GoalCreate(BaseModel):
    title: str
    description: Optional[str] = None
    target_level: Optional[str] = None
    deadline: Optional[date] = None
    material_id: Optional[int] = None


class GoalUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    target_level: Optional[str] = None
    deadline: Optional[date] = None
    status: Optional[str] = None
    material_id: Optional[int] = None


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    task_type: Optional[str] = "learn"
    planned_date: Optional[date] = None
    chapter_id: Optional[int] = None
    parent_task_id: Optional[int] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    task_type: Optional[str] = None
    planned_date: Optional[date] = None
    chapter_id: Optional[int] = None
    parent_task_id: Optional[int] = None
    status: Optional[str] = None


def _goal_item(g: Goal, material_title: Optional[str] = None) -> dict:
    return {
        "id": g.id,
        "title": g.title,
        "description": g.description,
        "target_level": g.target_level,
        "deadline": g.deadline.isoformat() if g.deadline else None,
        "status": g.status,
        "material_id": g.material_id,
        "material_title": material_title,
        "created_at": to_utc_iso(g.created_at) if g.created_at else None,
        "updated_at": to_utc_iso(g.updated_at) if g.updated_at else None,
        "sync_version": g.sync_version,
    }


def _task_item(t: Task, chapter_title: Optional[str] = None) -> dict:
    return {
        "id": t.id,
        "goal_id": t.goal_id,
        "parent_task_id": t.parent_task_id,
        "chapter_id": t.chapter_id,
        "chapter_title": chapter_title,
        "title": t.title,
        "description": t.description,
        "task_type": t.task_type,
        "planned_date": t.planned_date.isoformat() if t.planned_date else None,
        "status": t.status,
        "completed_at": to_utc_iso(t.completed_at) if t.completed_at else None,
        "created_at": to_utc_iso(t.created_at) if t.created_at else None,
        "updated_at": to_utc_iso(t.updated_at) if t.updated_at else None,
        "sync_version": t.sync_version,
    }


@router.get("")
async def list_goals(
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Goal).where(Goal.user_id == current_user.id)
    if status:
        query = query.where(Goal.status == status)
    result = await db.execute(query)
    goals = result.scalars().all()

    # Batch load material titles to avoid N+1
    material_ids = {g.material_id for g in goals if g.material_id}
    material_map = {}
    if material_ids:
        mat_result = await db.execute(select(Material).where(Material.id.in_(material_ids)))
        material_map = {m.id: m.title for m in mat_result.scalars().all()}

    out = []
    for g in goals:
        material_title = material_map.get(g.material_id) if g.material_id else None
        out.append(_goal_item(g, material_title))
    return out


@router.post("")
async def create_goal(
    body: GoalCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    operation = await begin_idempotent_operation(
        db, user_id=int(current_user.id), idempotency_key=idempotency_key,
        method="POST", path="/api/goals", body=body.dict(),
    )
    if operation.replay is not None:
        return operation.replay
    if body.material_id:
        mat_result = await db.execute(
            select(Material).where(Material.id == body.material_id, Material.user_id == current_user.id)
        )
        if not mat_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="资料不存在或无权访问")

    goal = Goal(
        user_id=current_user.id,
        material_id=body.material_id,
        title=body.title,
        description=body.description,
        target_level=body.target_level,
        deadline=body.deadline,
        status="active",
    )
    db.add(goal)
    await db.flush()
    await db.refresh(goal)
    await record_learning_event(
        db,
        int(current_user.id),
        "goal.created",
        source="goals_router",
        payload={"title": goal.title, "deadline": goal.deadline.isoformat() if goal.deadline else None},
        material_id=goal.material_id,
        goal_id=int(goal.id),
        dedupe_key=f"goal.created:{goal.id}",
    )
    item = _goal_item(goal)
    await complete_idempotent_operation(db, operation, item)
    return item


@router.put("/tasks/{task_id}")
async def update_task(
    task_id: int,
    body: TaskUpdate,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    operation = await begin_idempotent_operation(
        db, user_id=int(current_user.id), idempotency_key=idempotency_key,
        method="PUT", path=f"/api/goals/tasks/{task_id}", body=body.dict(exclude_unset=True), if_match=if_match,
    )
    if operation.replay is not None:
        return operation.replay
    # Verify task belongs to a goal owned by current_user
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # Check that the parent goal belongs to current user
    goal_result = await db.execute(select(Goal).where(Goal.id == task.goal_id, Goal.user_id == current_user.id))
    if not goal_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="任务不存在")
    require_matching_version(task.sync_version, if_match)

    if body.chapter_id is not None:
        await _ensure_user_chapter(db, body.chapter_id, int(current_user.id))
        task.chapter_id = body.chapter_id

    fields_set = provided_model_fields(body)
    if "parent_task_id" in fields_set:
        if body.parent_task_id is None:
            task.parent_task_id = None
        else:
            if body.parent_task_id == task.id:
                raise HTTPException(status_code=400, detail="父任务不能是自己")
            parent_result = await db.execute(
                select(Task).where(Task.id == body.parent_task_id, Task.goal_id == task.goal_id)
            )
            parent_task = parent_result.scalar_one_or_none()
            if not parent_task:
                raise HTTPException(status_code=404, detail="父任务不存在")

            check_node = parent_task
            visited = set()
            while check_node is not None and check_node.parent_task_id is not None:
                if check_node.id == task.id:
                    raise HTTPException(status_code=400, detail="不能将任务移动到自己的子任务下")
                if check_node.id in visited:
                    break
                visited.add(check_node.id)
                next_result = await db.execute(
                    select(Task).where(Task.id == check_node.parent_task_id, Task.goal_id == task.goal_id)
                )
                check_node = next_result.scalar_one_or_none()

            task.parent_task_id = body.parent_task_id
    if body.title is not None:
        task.title = body.title
    if body.description is not None:
        task.description = body.description
    if body.task_type is not None:
        task.task_type = body.task_type
    if body.planned_date is not None:
        task.planned_date = body.planned_date
    if body.status is not None:
        previous_status = task.status
        task.status = body.status
        if body.status == "completed":
            task.completed_at = task.completed_at or utc_now_db()
        else:
            task.completed_at = None

    for field in ("description", "task_type", "planned_date", "chapter_id"):
        if field in fields_set and getattr(body, field) is None:
            setattr(task, field, None)
    await flush_sync_mutation(db)
    await db.refresh(task)
    if body.status == "completed" and previous_status != "completed":
        await record_learning_event(
            db,
            int(current_user.id),
            "task.completed",
            source="goals_router",
            payload={"title": task.title, "planned_date": task.planned_date.isoformat() if task.planned_date else None},
            goal_id=int(task.goal_id),
            task_id=int(task.id),
            dedupe_key=f"task.completed:{task.id}:{task.completed_at.date().isoformat() if task.completed_at else date.today().isoformat()}",
        )
    else:
        await record_learning_event(
            db,
            int(current_user.id),
            "task.updated",
            source="goals_router",
            payload={"title": task.title, "status": task.status},
            goal_id=int(task.goal_id),
            task_id=int(task.id),
            dedupe_key=f"task.updated:{task.id}:{datetime.now().strftime('%Y%m%d%H%M%S')}",
        )
    item = _task_item(task)
    await complete_idempotent_operation(db, operation, item)
    return item


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    operation = await begin_idempotent_operation(
        db, user_id=int(current_user.id), idempotency_key=idempotency_key,
        method="DELETE", path=f"/api/goals/tasks/{task_id}", body={}, if_match=if_match,
    )
    if operation.replay is not None:
        return operation.replay
    result = await db.execute(select(Task).join(Goal).where(Task.id == task_id, Goal.user_id == current_user.id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_matching_version(task.sync_version, if_match)

    # Check that the parent goal belongs to current user
    goal_result = await db.execute(select(Goal).where(Goal.id == task.goal_id, Goal.user_id == current_user.id))
    if not goal_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="任务不存在")

    child_result = await db.execute(select(Task.id).where(Task.parent_task_id == task.id).limit(1))
    if child_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="请先删除或调整该任务的子任务")

    # 先解除其他业务表对 task_id 的引用，避免外键约束导致删除失败（500）
    pomodoro_result = await db.execute(select(Pomodoro).where(Pomodoro.task_id == task.id))
    for p in pomodoro_result.scalars().all():
        p.task_id = None

    session_result = await db.execute(select(StudySession).where(StudySession.task_id == task.id))
    for s in session_result.scalars().all():
        s.task_id = None

    await db.delete(task)
    await flush_sync_mutation(db)
    from app.services.understanding_runtime import enqueue_understanding
    await enqueue_understanding(db, current_user.id)
    item = {"ok": True}
    await complete_idempotent_operation(db, operation, item)
    return item


@router.get("/tasks/daily")
async def list_daily_tasks(
    day: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Only return tasks whose parent goal belongs to the current user
    result = await db.execute(
        select(Task)
        .join(Goal, Task.goal_id == Goal.id)
        .where(Task.planned_date == day, Goal.user_id == current_user.id)
    )
    tasks = result.scalars().all()

    # Batch load chapter titles to avoid N+1
    chapter_ids = {t.chapter_id for t in tasks if t.chapter_id}
    chapter_map = {}
    if chapter_ids:
        ch_result = await db.execute(
            select(Chapter)
            .join(Material, Chapter.material_id == Material.id)
            .where(Chapter.id.in_(chapter_ids), Material.user_id == current_user.id)
        )
        chapter_map = {c.id: c.title for c in ch_result.scalars().all()}

    out = []
    for t in tasks:
        chapter_title = chapter_map.get(t.chapter_id) if t.chapter_id else None
        out.append(_task_item(t, chapter_title))
    return out


@router.put("/{goal_id}")
async def update_goal(
    goal_id: int,
    body: GoalUpdate,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    operation = await begin_idempotent_operation(
        db, user_id=int(current_user.id), idempotency_key=idempotency_key,
        method="PUT", path=f"/api/goals/{goal_id}", body=body.dict(exclude_unset=True), if_match=if_match,
    )
    if operation.replay is not None:
        return operation.replay
    result = await db.execute(select(Goal).where(Goal.id == goal_id, Goal.user_id == current_user.id))
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="目标不存在")
    require_matching_version(goal.sync_version, if_match)

    if body.material_id is not None:
        mat_result = await db.execute(
            select(Material).where(Material.id == body.material_id, Material.user_id == current_user.id)
        )
        if not mat_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="资料不存在或无权访问")
        goal.material_id = body.material_id
    if body.title is not None:
        goal.title = body.title
    if body.description is not None:
        goal.description = body.description
    if body.target_level is not None:
        goal.target_level = body.target_level
    if body.deadline is not None:
        goal.deadline = body.deadline
    if body.status is not None:
        goal.status = body.status

    for field in ("description", "target_level", "deadline", "material_id"):
        if field in provided_model_fields(body) and getattr(body, field) is None:
            setattr(goal, field, None)
    await flush_sync_mutation(db)
    await db.refresh(goal)
    await record_learning_event(
        db,
        int(current_user.id),
        "goal.updated",
        source="goals_router",
        payload={"title": goal.title, "status": goal.status, "deadline": goal.deadline.isoformat() if goal.deadline else None},
        material_id=goal.material_id,
        goal_id=int(goal.id),
        dedupe_key=f"goal.updated:{goal.id}:{datetime.now().strftime('%Y%m%d%H%M%S')}",
    )
    item = _goal_item(goal)
    await complete_idempotent_operation(db, operation, item)
    return item


@router.delete("/{goal_id}")
async def delete_goal(
    goal_id: int,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    operation = await begin_idempotent_operation(
        db, user_id=int(current_user.id), idempotency_key=idempotency_key,
        method="DELETE", path=f"/api/goals/{goal_id}", body={}, if_match=if_match,
    )
    if operation.replay is not None:
        return operation.replay
    result = await db.execute(select(Goal).where(Goal.id == goal_id, Goal.user_id == current_user.id))
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="目标不存在")
    require_matching_version(goal.sync_version, if_match)

    # 显式查询任务，避免异步 Session 上访问 goal.tasks 懒加载导致 MissingGreenlet
    tasks_result = await db.execute(select(Task.id).where(Task.goal_id == goal.id))
    task_ids = list(tasks_result.scalars())

    # 先解除外部表对 Task 的引用，避免 Goal 级联删除 Task 时触发外键错误
    if task_ids:
        await db.execute(
            update(Pomodoro)
            .where(Pomodoro.task_id.in_(task_ids))
            .values(task_id=None)
        )
        await db.execute(
            update(StudySession)
            .where(StudySession.task_id.in_(task_ids))
            .values(task_id=None)
        )

    # ReviewSchedule belongs to the user's chapter, not to a goal referencing it.
    # Preserve FSRS and archive state even when this is the last referencing goal.

    await db.delete(goal)
    await flush_sync_mutation(db)
    from app.services.understanding_runtime import enqueue_understanding
    await enqueue_understanding(db, current_user.id)
    item = {"ok": True}
    await complete_idempotent_operation(db, operation, item)
    return item


@router.get("/{goal_id}/tasks")
async def list_goal_tasks(
    goal_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    goal_result = await db.execute(select(Goal).where(Goal.id == goal_id, Goal.user_id == current_user.id))
    if not goal_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="目标不存在")

    result = await db.execute(
        select(Task)
        .where(Task.goal_id == goal_id)
        .order_by(Task.parent_task_id.is_not(None), Task.created_at.asc(), Task.id.asc())
    )
    tasks = result.scalars().all()

    # Batch load chapter titles to avoid N+1
    chapter_ids = {t.chapter_id for t in tasks if t.chapter_id}
    chapter_map = {}
    if chapter_ids:
        ch_result = await db.execute(
            select(Chapter)
            .join(Material, Chapter.material_id == Material.id)
            .where(Chapter.id.in_(chapter_ids), Material.user_id == current_user.id)
        )
        chapter_map = {c.id: c.title for c in ch_result.scalars().all()}

    out = []
    for t in tasks:
        chapter_title = chapter_map.get(t.chapter_id) if t.chapter_id else None
        out.append(_task_item(t, chapter_title))
    return out


@router.post("/{goal_id}/tasks")
async def create_goal_task(
    goal_id: int,
    body: TaskCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    operation = await begin_idempotent_operation(
        db, user_id=int(current_user.id), idempotency_key=idempotency_key,
        method="POST", path=f"/api/goals/{goal_id}/tasks", body=body.dict(),
    )
    if operation.replay is not None:
        return operation.replay
    goal_result = await db.execute(select(Goal).where(Goal.id == goal_id, Goal.user_id == current_user.id))
    if not goal_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="目标不存在")

    if body.chapter_id:
        await _ensure_user_chapter(db, body.chapter_id, int(current_user.id))

    if body.parent_task_id is not None:
        parent_result = await db.execute(
            select(Task).where(Task.id == body.parent_task_id, Task.goal_id == goal_id)
        )
        if not parent_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="父任务不存在")

    task = Task(
        goal_id=goal_id,
        parent_task_id=body.parent_task_id,
        chapter_id=body.chapter_id,
        title=body.title,
        description=body.description,
        task_type=body.task_type,
        planned_date=body.planned_date,
        status="pending",
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    await record_learning_event(
        db,
        int(current_user.id),
        "task.created",
        source="goals_router",
        payload={"title": task.title, "planned_date": task.planned_date.isoformat() if task.planned_date else None},
        chapter_id=task.chapter_id,
        goal_id=int(goal_id),
        task_id=int(task.id),
        dedupe_key=f"task.created:{task.id}",
    )
    item = _task_item(task)
    await complete_idempotent_operation(db, operation, item)
    return item


@router.get("/{goal_id}/time-summary")
async def get_goal_time_summary(
    goal_id: int,
    range: str = Query("all"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    goal_result = await db.execute(select(Goal).where(Goal.id == goal_id, Goal.user_id == current_user.id))
    if not goal_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="目标不存在")

    task_result = await db.execute(select(Task).where(Task.goal_id == goal_id))
    tasks = list(task_result.scalars().all())
    task_map = {t.id: t for t in tasks}

    now = datetime.now()
    period = (range or "all").strip().lower()
    if period not in {"all", "week", "month"}:
        raise HTTPException(status_code=400, detail="range 仅支持 all/week/month")

    pomodoro_filters = [Pomodoro.user_id == current_user.id, Pomodoro.task_id.is_not(None)]
    if period == "week":
        week_start = now - timedelta(days=now.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        pomodoro_filters.append(Pomodoro.created_at >= week_start)
    elif period == "month":
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        pomodoro_filters.append(Pomodoro.created_at >= month_start)

    duration_result = await db.execute(
        select(Pomodoro.task_id, func.sum(Pomodoro.duration))
        .where(and_(*pomodoro_filters))
        .group_by(Pomodoro.task_id)
    )
    direct_minutes = {
        int(task_id): float(minutes or 0)
        for task_id, minutes in duration_result.all()
        if task_id is not None and int(task_id) in task_map
    }

    children_map: dict[int, list[Task]] = {}
    root_tasks: list[Task] = []
    for task in tasks:
        if task.parent_task_id and task.parent_task_id in task_map:
            children_map.setdefault(task.parent_task_id, []).append(task)
        else:
            root_tasks.append(task)

    def _build(node: Task, visited: set[int]) -> dict:
        if node.id in visited:
            return {
                "task_id": node.id,
                "title": node.title,
                "task_type": node.task_type,
                "self_minutes": round(direct_minutes.get(node.id, 0.0), 1),
                "total_minutes": round(direct_minutes.get(node.id, 0.0), 1),
                "children": [],
            }

        next_visited = set(visited)
        next_visited.add(node.id)
        child_nodes = sorted(children_map.get(node.id, []), key=lambda x: (x.created_at is None, x.created_at or datetime.min, x.id))
        children = [_build(child, next_visited) for child in child_nodes]
        self_minutes = float(direct_minutes.get(node.id, 0.0))
        total_minutes = self_minutes + sum(float(child["total_minutes"]) for child in children)

        return {
            "task_id": node.id,
            "title": node.title,
            "task_type": node.task_type,
            "self_minutes": round(self_minutes, 1),
            "total_minutes": round(total_minutes, 1),
            "children": children,
        }

    roots = sorted(root_tasks, key=lambda x: (x.created_at is None, x.created_at or datetime.min, x.id))
    tree = [_build(root, set()) for root in roots]

    overall_minutes = round(sum(float(item["total_minutes"]) for item in tree), 1)
    return {
        "goal_id": goal_id,
        "range": period,
        "total_minutes": overall_minutes,
        "tasks": tree,
    }


# ============ 动态任务生成 API ============

class GoalPlanRequest(BaseModel):
    total_days: int
    current_chapter_id: Optional[int] = None
    study_days_per_week: int = 5


@router.post("/{goal_id}/plan")
async def create_goal_plan(
    goal_id: int,
    body: GoalPlanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """设定学习计划并生成本周任务"""
    # Verify goal ownership
    goal_result = await db.execute(select(Goal).where(Goal.id == goal_id, Goal.user_id == current_user.id))
    goal = goal_result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="目标不存在")
    
    # Validate chapter if provided
    if body.current_chapter_id:
        await _ensure_user_chapter(db, body.current_chapter_id, int(current_user.id))
    
    # Update goal with plan settings
    from datetime import date
    today = date.today()
    goal.plan_total_days = body.total_days
    goal.plan_current_chapter_id = body.current_chapter_id
    goal.plan_study_days_per_week = body.study_days_per_week
    goal.plan_start_date = today
    goal.plan_last_generated_week = today
    
    await db.flush()
    
    # Generate this week's tasks
    tasks = await _generate_weekly_tasks(goal, db, today)
    
    return {
        "goal_id": goal.id,
        "plan_set": True,
        "generated_tasks": len(tasks),
        "tasks": tasks,
    }


@router.post("/{goal_id}/plan/next-week")
async def generate_next_week_tasks(
    goal_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """生成下周任务"""
    goal_result = await db.execute(select(Goal).where(Goal.id == goal_id, Goal.user_id == current_user.id))
    goal = goal_result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="目标不存在")
    
    if not goal.plan_start_date:
        raise HTTPException(status_code=400, detail="请先设定学习计划")
    
    # Calculate next week start
    from datetime import timedelta
    today = date.today()
    next_monday = today + timedelta(days=(7 - today.weekday()))
    
    # Update last generated week
    goal.plan_last_generated_week = next_monday
    await db.flush()
    
    # Generate next week's tasks
    tasks = await _generate_weekly_tasks(goal, db, next_monday)
    
    return {
        "goal_id": goal.id,
        "week_start": str(next_monday),
        "generated_tasks": len(tasks),
        "tasks": tasks,
    }


async def _generate_weekly_tasks(goal: Goal, db: AsyncSession, week_start: date) -> list:
    """根据学习计划生成一周的任务"""
    from datetime import timedelta
    
    if not goal.material_id:
        return []
    
    # Get all chapters for this material
    ch_result = await db.execute(
        select(Chapter)
        .where(Chapter.material_id == goal.material_id)
        .order_by(Chapter.order_index)
    )
    chapters = ch_result.scalars().all()
    
    if not chapters:
        return []
    
    # Find current chapter index
    current_idx = 0
    if goal.plan_current_chapter_id:
        for i, ch in enumerate(chapters):
            if ch.id == goal.plan_current_chapter_id:
                current_idx = i
                break
    
    # Calculate how many chapters to cover this week
    study_days = goal.plan_study_days_per_week or 5
    chapters_this_week = chapters[current_idx:current_idx + study_days]
    
    # Get existing tasks for this week to avoid duplicates
    week_end = week_start + timedelta(days=6)
    existing_result = await db.execute(
        select(Task).where(
            Task.goal_id == goal.id,
            Task.planned_date >= week_start,
            Task.planned_date <= week_end,
        )
    )
    existing_chapter_ids = {t.chapter_id for t in existing_result.scalars().all() if t.chapter_id}
    
    # Generate tasks for this week
    tasks = []
    day_offset = 0
    for ch in chapters_this_week:
        if ch.id in existing_chapter_ids:
            continue
        
        # Skip weekends (assuming Monday=0, Sunday=6)
        while (week_start + timedelta(days=day_offset)).weekday() >= 5:
            day_offset += 1
        
        planned_date = week_start + timedelta(days=day_offset)
        task = Task(
            goal_id=goal.id,
            chapter_id=ch.id,
            title=f"学习：{ch.title}",
            description=f"学习章节「{ch.title}」",
            task_type="learn",
            status="pending",
            planned_date=planned_date,
        )
        db.add(task)
        tasks.append({
            "title": task.title,
            "chapter_id": ch.id,
            "planned_date": str(planned_date),
        })
        day_offset += 1
    
    if tasks:
        await db.flush()
        # Update current chapter to the last one generated
        if chapters_this_week:
            goal.plan_current_chapter_id = chapters_this_week[-1].id
            await db.flush()
    
    return tasks
