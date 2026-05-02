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



@router.post("/write/draft")
async def draft_agent_write(
    body: AgentWriteDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """根据自然语言生成写入草案；只预览，不直接写入。"""
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


@router.post("/actions/{action_id}/execute", response_model=AgentActionExecuteResponse)
async def execute_agent_action_endpoint(
    action_id: str,
    use_llm: bool = Query(False, description="是否按 LLM Planner 生成的行动执行"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认执行一个 Agent 行动。当前只自动创建低风险任务，其余行动记录反馈后跳转。"""
    try:
        return await execute_agent_action(db, int(current_user.id), action_id, use_llm=use_llm)
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
    return await remember_agent_feedback(
        db,
        int(current_user.id),
        action_id,
        body.outcome,
        body.notes,
        effectiveness,
        action,
        body.reason_code,
    )



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
