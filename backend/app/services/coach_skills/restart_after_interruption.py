"""Restart after interruption skill."""
from __future__ import annotations

from app.services.coach_skills.base import CoachSkill, CoachSkillContext, CoachSkillResult, explain_with_context, trim_text


class RestartAfterInterruptionSkill(CoachSkill):
    id = "restart_after_interruption"
    display_name = "中断后重启"
    description = "番茄钟中断或走神后，帮助用户用更短专注块重新开始。"
    trigger_event_types = {"pomodoro.interrupted", "pomodoro.distracted"}
    required_context = {"learning", "tasks"}
    tone_rules = ["不责备", "缩短下一轮时长", "强调恢复节奏"]
    safety_rules = ["不自动重排任务", "不制造压力"]

    async def generate(self, ctx: CoachSkillContext) -> CoachSkillResult:
        payload = ctx.event.get("payload") or {}
        task_name = trim_text(payload.get("task_name") or payload.get("task") or "", 36)
        if task_name:
            body = f"刚才中断了也没关系。把「{task_name}」降到12分钟，只恢复节奏，不追进度。"
        else:
            body = "刚才中断了也没关系。下一轮只设12分钟，选一个最小动作恢复节奏。"

        return CoachSkillResult(
            title="用短专注重启",
            body=body,
            suggested_action={
                "type": "start_focus",
                "label": "开12分钟",
                "route": "/pomodoro",
                "minutes": 12,
            },
            route="/pomodoro",
            explainability=explain_with_context(
                ctx,
                "番茄钟被中断，短时重启比继续加压更稳。",
                [f"stop_reason={payload.get('stop_reason') or ctx.event.get('event_type')}"],
            ),
        )
