"""Local Agent/Coach smoke test against a running Mnemox backend.

Usage:
    python scripts/agent_coach_smoke.py
    python scripts/agent_coach_smoke.py --eval-cases --base-url http://127.0.0.1:8000

Environment overrides:
    MNEMOX_API_BASE_URL=http://127.0.0.1:8000
    MNEMOX_SMOKE_USERNAME=mnemox_test_agent
    MNEMOX_SMOKE_PASSWORD=TestAgent123!
    MNEMOX_SMOKE_EMAIL=mnemox-test-agent@example.com
"""
import asyncio
import argparse
import os
import sys
from typing import Any

import httpx


DEFAULT_BASE_URL = os.environ.get("MNEMOX_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
DEFAULT_USERNAME = os.environ.get("MNEMOX_SMOKE_USERNAME", "mnemox_test_agent")
DEFAULT_PASSWORD = os.environ.get("MNEMOX_SMOKE_PASSWORD", "TestAgent123!")
DEFAULT_EMAIL = os.environ.get("MNEMOX_SMOKE_EMAIL", "mnemox-test-agent@example.com")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _brief_summary(brief: dict[str, Any]) -> str:
    return (
        f"autonomy={brief.get('autonomy_level')} "
        f"readiness={brief.get('readiness_score')} "
        f"actions={len(brief.get('next_actions') or [])} "
        f"planner={((brief.get('planner') or {}).get('source') or 'unknown')}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Agent/Coach smoke test against a running Mnemox backend.")
    parser.add_argument("--eval-cases", action="store_true", help="Run expanded goal-memory HTTP smoke probes.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Backend base URL.")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help="Smoke test username.")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Smoke test password.")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="Smoke test email.")
    return parser.parse_args()


async def _register_or_ignore(client: httpx.AsyncClient, username: str, password: str, email: str) -> None:
    response = await client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    if response.status_code in {200, 201, 400}:
        return
    response.raise_for_status()


async def _login(client: httpx.AsyncClient, username: str, password: str) -> str:
    response = await client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    _require(bool(token), "login response did not include access_token")
    return str(token)


async def _post_required(client: httpx.AsyncClient, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
    response = await client.post(path, json=json)
    if response.status_code == 404:
        raise AssertionError(f"required endpoint missing: POST {path}")
    response.raise_for_status()
    return response.json()


async def _get_required(client: httpx.AsyncClient, path: str) -> dict[str, Any] | list[Any]:
    response = await client.get(path)
    if response.status_code == 404:
        raise AssertionError(f"required endpoint missing: GET {path}")
    response.raise_for_status()
    return response.json()


async def _run_default_smoke(client: httpx.AsyncClient) -> None:
    brief = (await client.get("/api/agent/brief")).json()
    _require("context" in brief, "agent brief missing context")
    _require("tasks" in (brief.get("context") or {}), "agent brief missing tasks context")
    print(f"[agent.brief] {_brief_summary(brief)}")

    draft_cases = [
        ("今天的任务是复习英语听力20分钟", "add_daily_plan_items"),
        ("帮我记一条笔记：六级听力要先抓转折词", "create_note"),
        ("新建目标：两周提升英语听力，任务：每天精听20分钟", "create_goal_tasks"),
    ]
    for message, expected in draft_cases:
        response = await client.post("/api/agent/write/draft", json={"message": message})
        response.raise_for_status()
        draft = response.json()
        _require(draft.get("intent") == expected, f"{message!r} expected {expected}, got {draft.get('intent')}")
        _require(draft.get("requires_confirmation") is True, f"{expected} should require confirmation")
        print(f"[agent.write] {expected}: {draft.get('summary')}")

    profile_tool = (
        await client.post(
            "/api/agent/tools/chat",
            json={"tool": "get_agent_learning_profile", "query": "", "limit": 1},
        )
    ).json()
    _require(profile_tool.get("tool") == "get_agent_learning_profile", "profile tool contract changed")
    print("[agent.tool] get_agent_learning_profile ok")

    await _run_coach_feedback_smoke(client)


async def _run_coach_feedback_smoke(client: httpx.AsyncClient) -> None:
    coach_response = await client.post(
        "/api/coach/evaluate",
        json={
            "event": {
                "event_type": "chat.low_motivation_detected",
                "source": "chat",
                "channel": "chat_inline",
                "payload": {"text": "今天有点学不进去，先给我一个最小动作"},
                "severity": "info",
            }
        },
    )
    coach_response.raise_for_status()
    coach = coach_response.json()
    _require(coach.get("policy", {}).get("skill_id") == "low_motivation", "coach did not route low motivation event")
    nudge = coach.get("nudge")
    _require(bool(nudge), "coach did not create a nudge")
    print(f"[coach.evaluate] {nudge.get('skill_id')}: {nudge.get('title')}")

    nudge_id = nudge["id"]
    shown = await client.post(f"/api/coach/nudges/{nudge_id}/shown")
    shown.raise_for_status()
    feedback = await client.post(
        f"/api/coach/nudges/{nudge_id}/feedback",
        json={"outcome": "helpful", "notes": "smoke test"},
    )
    feedback.raise_for_status()
    stats = feedback.json().get("learning_stats") or {}
    _require(int(stats.get("shown_count") or 0) >= 1, "coach learning stats did not count shown nudge")
    _require(int(stats.get("helpful_count") or 0) >= 1, "coach learning stats did not count helpful feedback")
    print("[coach.feedback] stats updated")


async def _run_eval_case_smoke(client: httpx.AsyncClient) -> None:
    goal_context = await _get_required(client, "/api/agent/goal-context")
    _require("today_focus" in goal_context, "goal-context response missing today_focus")
    print(f"[agent.goal-context] focus={(goal_context.get('today_focus') or {}).get('action_id')}")

    draft = await _post_required(
        client,
        "/api/agent/write/draft",
        json={"message": "记一个灵感到笔记里：smoke harness note retrieval checkpoint"},
    )
    _require(draft.get("intent") == "create_note", "write draft did not produce create_note")
    _require(draft.get("requires_confirmation") is True, "write draft should require confirmation")
    created = await _post_required(
        client,
        "/api/agent/write/execute",
        json={"intent": draft["intent"], "draft": draft["draft"]},
    )
    _require(created.get("status") in {"created", "skipped_duplicate"}, "write execute returned unexpected status")
    note = ((created.get("created") or {}).get("note") or {})
    note_id = note.get("id")
    print(f"[agent.write.execute] {created.get('status')}: {created.get('message')}")

    learning = await _post_required(client, "/api/agent/memory/run-learning")
    _require("checkpoint" in learning, "memory learner response missing checkpoint")
    print(f"[agent.memory.run-learning] events={learning.get('processed_event_count')} candidates={learning.get('candidate_count')}")

    if not note_id:
        notes = await _get_required(client, "/api/notes?q=smoke%20harness")
        items = notes if isinstance(notes, list) else notes.get("items") or notes.get("data") or []
        _require(items, "note retrieval did not return created smoke note")
        note_id = items[0]["id"]
    note_detail = await _get_required(client, f"/api/notes/{note_id}")
    _require(note_detail.get("id") == note_id, "note retrieval returned wrong note")
    action_draft = await _post_required(
        client,
        f"/api/notes/{note_id}/actions/ask-agent",
        json={"selected_text": "smoke harness", "instruction": "prepare a retrieval preview"},
    )
    _require(bool(action_draft), "note action endpoint returned empty response")
    print(f"[notes.action] note_id={note_id}")

    await _run_coach_feedback_smoke(client)


async def main() -> int:
    args = _parse_args()
    base_url = args.base_url.rstrip("/")
    timeout = httpx.Timeout(20.0, connect=5.0)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout, trust_env=False) as client:
        health = await client.get("/health")
        health.raise_for_status()
        await _register_or_ignore(client, args.username, args.password, args.email)
        token = await _login(client, args.username, args.password)
        client.headers.update({"Authorization": f"Bearer {token}"})

        if args.eval_cases:
            await _run_eval_case_smoke(client)
        else:
            await _run_default_smoke(client)

    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except httpx.ConnectError:
        print("Cannot connect to backend. Start the backend first or pass --base-url.", file=sys.stderr)
        raise SystemExit(2)
    except Exception as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
