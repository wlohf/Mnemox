"""自主学习 Agent 路由"""
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.agents.manager import agent_manager
from app.models.user import User
from app.services.agent_service import (
    build_agent_action_draft,
    build_agent_brief,
    build_agent_prompt_snippet,
    build_agent_write_draft,
    execute_agent_action,
    execute_agent_write_draft,
    collect_agent_profile_control_logs,
    remember_agent_feedback,
    update_agent_profile_item,
)
from app.services.goal_context_service import build_goal_context
from app.services.learning_event_service import record_learning_event

router = APIRouter()


class AgentAction(BaseModel):
    id: str
    title: str
    reason: str
    action_type: str
    priority: Literal["high", "medium", "low"]
    estimated_minutes: int
    route: str
    target: Any = None
    source: str | None = None
    explainability: dict[str, Any] | None = None


class AgentBriefResponse(BaseModel):
    date: str
    generated_at: str
    autonomy_level: str
    readiness_score: float
    risk_level: Literal["low", "medium", "high"]
    state_summary: str
    current_focus: str
    next_actions: list[AgentAction]
    watch_signals: list[str]
    planner: dict[str, Any] | None = None
    context: dict[str, Any]


class AgentActionDraftResponse(BaseModel):
    action: AgentAction
    draft: dict[str, Any]
    requires_confirmation: bool


class AgentActionExecuteResponse(BaseModel):
    status: str
    action: AgentAction
    draft: dict[str, Any]
    created_task: dict[str, Any] | None = None
    route: str | None = None


class AgentWriteDraftRequest(BaseModel):
    message: str


class AgentWriteExecuteRequest(BaseModel):
    intent: Literal["create_note", "create_goal_tasks", "add_daily_plan_items"]
    draft: dict[str, Any]


class AgentGoalActionDraftRequest(BaseModel):
    message: str | None = None


class AgentTaskTriggerRequest(BaseModel):
    agent: Literal["study_plan", "review", "chat"]
    task: str | None = "run"
    payload: dict[str, Any] | None = None


class AgentToolCallRequest(BaseModel):
    tool: Literal["search_notes", "search_materials", "search_wrong_questions", "search_memories", "get_profile", "get_agent_learning_profile", "get_today_tasks", "get_recent_feedback"]
    query: str | None = None
    limit: int | None = 5


class AgentFeedbackRequest(BaseModel):
    outcome: Literal[
        "accepted",
        "dismissed",
        "completed",
        "failed",
        "adjusted",
        "later",
        "useless",
        "helpful",
        "rejected",
        "snoozed",
    ]
    notes: str | None = None
    effectiveness: float | None = None
    reason_code: Literal[
        "too_long",
        "too_late",
        "too_easy",
        "too_hard",
        "too_disruptive",
        "irrelevant_to_goal",
        "already_known",
        "other",
    ] | None = None


class AgentProfileControlRequest(BaseModel):
    operation: Literal["ignore", "inaccurate", "lock", "unlock", "restore"]


@router.get("/status")
async def get_agent_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询 Agent runtime 状态、任务队列和执行日志。"""
    status = await agent_manager.status(db, int(current_user.id))
    status["profile_control_logs"] = await collect_agent_profile_control_logs(db, int(current_user.id), limit=12)
    return status


@router.post("/tasks/trigger")
async def trigger_agent_task(
    body: AgentTaskTriggerRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """触发一个轻量 Agent 任务。"""
    try:
        return await agent_manager.trigger(
            db=db,
            user_id=int(current_user.id),
            agent_name=body.agent,
            task=body.task or "run",
            payload=body.payload or {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent 执行失败: {exc}") from exc


@router.post("/tools/chat")
async def call_chat_agent_tool(
    body: AgentToolCallRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """调用 ChatAgent 的只读查询工具。"""
    return await agent_manager.call_chat_tool(
        db=db,
        user_id=int(current_user.id),
        tool=body.tool,
        query=body.query or "",
        limit=body.limit or 5,
    )


@router.get("/brief", response_model=AgentBriefResponse)
async def get_agent_brief(
    use_llm: bool = Query(False, description="是否尝试使用 LLM Planner 增强行动规划，失败会回退规则引擎"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取 Agent 今日简报：感知当前状态并给出下一步行动建议。"""
    return await build_agent_brief(db, int(current_user.id), use_llm=use_llm)


@router.get("/goal-context")
async def get_agent_goal_context(
    goal_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取以当前目标为中心的 Agent cockpit 上下文。"""
    return await build_goal_context(db, int(current_user.id), goal_id=goal_id)


@router.post("/write/draft")
async def draft_agent_write(
    body: AgentWriteDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """根据自然语言生成写入草案；只预览，不直接写入。"""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")
    return await build_agent_write_draft(db, int(current_user.id), body.message)


@router.post("/write/execute")
async def execute_agent_write(
    body: AgentWriteExecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认执行自然语言写入草案。"""
    try:
        result = await execute_agent_write_draft(db, int(current_user.id), body.intent, body.draft)
        created = result.get("created") or {}
        if body.intent == "create_note" and (created.get("note") or {}).get("id"):
            note = created["note"]
            await record_learning_event(
                db,
                int(current_user.id),
                "note.created",
                source="agent_write",
                payload={"title": note.get("title"), "intent": body.intent},
                note_id=int(note["id"]),
                dedupe_key=f"agent:note.created:{note['id']}",
            )
        elif body.intent == "create_goal_tasks" and (created.get("goal") or {}).get("id"):
            goal = created["goal"]
            await record_learning_event(
                db,
                int(current_user.id),
                "goal.created" if not body.draft.get("existing_goal_id") else "goal.updated",
                source="agent_write",
                payload={"title": goal.get("title"), "task_count": len(created.get("tasks") or [])},
                goal_id=int(goal["id"]),
                dedupe_key=f"agent:goal_tasks:{goal['id']}:{len(created.get('tasks') or [])}",
            )
            for task in created.get("tasks") or []:
                if task.get("id"):
                    await record_learning_event(
                        db,
                        int(current_user.id),
                        "task.created",
                        source="agent_write",
                        payload={"title": task.get("title"), "planned_date": task.get("planned_date")},
                        goal_id=int(goal["id"]),
                        task_id=int(task["id"]),
                        dedupe_key=f"agent:task.created:{task['id']}",
                    )
        elif body.intent == "add_daily_plan_items" and (created.get("plan") or {}).get("id"):
            plan = created["plan"]
            await record_learning_event(
                db,
                int(current_user.id),
                "daily_plan.updated",
                source="agent_write",
                payload={"date": plan.get("date"), "item_count": len(created.get("items") or [])},
                dedupe_key=f"agent:daily_plan.updated:{plan['id']}:{len(created.get('items') or [])}",
            )
        await db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/prompt")
async def get_agent_prompt_fragment(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """调试用：查看会注入聊天 system prompt 的 Agent 简报片段。"""
    brief = await build_agent_brief(db, int(current_user.id))
    return {"prompt": build_agent_prompt_snippet(brief)}


@router.get("/actions/{action_id}/draft", response_model=AgentActionDraftResponse)
async def get_agent_action_draft(
    action_id: str,
    use_llm: bool = Query(False, description="是否按 LLM Planner 生成的行动查找草案"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """把某个 Agent 行动转成可确认的执行草案；默认只预览，不写入数据。"""
    try:
        return await build_agent_action_draft(db, int(current_user.id), action_id, use_llm=use_llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/goal-context/actions/{action_id}/draft")
async def draft_agent_goal_context_action(
    action_id: str,
    body: AgentGoalActionDraftRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Goal cockpit 的行动草案入口；复用现有 Agent 草稿契约。"""
    if body and body.message and body.message.strip():
        return await build_agent_write_draft(db, int(current_user.id), body.message)
    try:
        return await build_agent_action_draft(db, int(current_user.id), action_id, use_llm=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/goal-context/actions/{action_id}/feedback")
async def record_agent_goal_context_action_feedback(
    action_id: str,
    body: AgentFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录用户对目标 cockpit 行动的反馈。"""
    effectiveness = body.effectiveness
    if effectiveness is not None:
        effectiveness = max(0.0, min(1.0, float(effectiveness)))
    action = None
    try:
        context = await build_goal_context(db, int(current_user.id))
        focus = context.get("today_focus") or {}
        if focus.get("action_id") == action_id or focus.get("id") == action_id:
            action = {
                "id": action_id,
                "title": focus.get("title"),
                "reason": focus.get("reason"),
                "action_type": "goal_context",
                "route": focus.get("route"),
                "target": focus.get("target"),
                "source": "goal_context",
            }
    except Exception:
        action = None
    result = await remember_agent_feedback(
        db,
        int(current_user.id),
        action_id,
        body.outcome,
        body.notes,
        effectiveness,
        action,
        body.reason_code,
    )
    await record_learning_event(
        db,
        int(current_user.id),
        "agent.action_feedback",
        source="agent_goal_context",
        payload={"action_id": action_id, "outcome": body.outcome, "reason_code": body.reason_code},
        dedupe_key=f"agent.goal_context.feedback:{action_id}:{body.outcome}:{body.reason_code or ''}",
    )
    await db.commit()
    return result


@router.post("/actions/{action_id}/execute", response_model=AgentActionExecuteResponse)
async def execute_agent_action_endpoint(
    action_id: str,
    use_llm: bool = Query(False, description="是否按 LLM Planner 生成的行动执行"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认执行一个 Agent 行动。当前只自动创建低风险任务，其余行动记录反馈后跳转。"""
    try:
        user_id = int(current_user.id)
        result = await execute_agent_action(db, user_id, action_id, use_llm=use_llm)
        action = result.get("action") or {}
        created_task = result.get("created_task") or {}
        if created_task.get("id"):
            await record_learning_event(
                db,
                user_id,
                "task.created",
                source="agent_action_execute",
                payload={
                    "title": created_task.get("title"),
                    "action_id": action_id,
                    "action_type": action.get("action_type"),
                    "planned_date": created_task.get("planned_date"),
                },
                goal_id=int(created_task["goal_id"]) if created_task.get("goal_id") else None,
                task_id=int(created_task["id"]),
                dedupe_key=f"agent:action:{action_id}:task.created:{created_task['id']}",
            )
        await record_learning_event(
            db,
            user_id,
            "agent.action_feedback",
            source="agent_action_execute",
            payload={
                "action_id": action_id,
                "action_type": action.get("action_type"),
                "outcome": "accepted" if result.get("status") == "created" else result.get("status"),
                "route": result.get("route"),
            },
            goal_id=int(created_task["goal_id"]) if created_task.get("goal_id") else None,
            task_id=int(created_task["id"]) if created_task.get("id") else None,
            dedupe_key=f"agent:action:{action_id}:feedback:{result.get('status')}",
        )
        await db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/actions/{action_id}/feedback")
async def record_agent_action_feedback(
    action_id: str,
    body: AgentFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录用户对 Agent 行动的反馈，写入 episodic memory 供后续规划参考。"""
    effectiveness = body.effectiveness
    if effectiveness is not None:
        effectiveness = max(0.0, min(1.0, float(effectiveness)))
    action = None
    try:
        brief = await build_agent_brief(db, int(current_user.id), use_llm=False)
        action = next((item for item in brief.get("next_actions", []) if item.get("id") == action_id), None)
    except Exception:
        action = None
    result = await remember_agent_feedback(
        db,
        int(current_user.id),
        action_id,
        body.outcome,
        body.notes,
        effectiveness,
        action,
        body.reason_code,
    )
    await record_learning_event(
        db,
        int(current_user.id),
        "agent.action_feedback",
        source="agent_actions",
        payload={"action_id": action_id, "outcome": body.outcome, "reason_code": body.reason_code},
        dedupe_key=f"agent.actions.feedback:{action_id}:{body.outcome}:{body.reason_code or ''}",
    )
    await db.commit()
    return result



@router.patch("/profile/items/{item_id}")
async def control_agent_profile_item(
    item_id: str,
    body: AgentProfileControlRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """控制 Agent 学到的画像条目：忽略、标记不准确、锁定或恢复。"""
    try:
        return await update_agent_profile_item(db, int(current_user.id), item_id, body.operation)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
