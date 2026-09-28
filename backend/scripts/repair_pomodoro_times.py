"""Preview and apply explicit, snapshot-checked historical timezone conversions.

Run from backend with PYTHONPATH=. Never guesses which rows came from local time.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from app.models.pomodoro import Pomodoro
from app.models.learning_event import LearningEvent
from app.models.learner_model import LearnerEvidence, ProjectionOutbox
from app.utils.mutation_lock import lock_user_mutation


def convert(value: datetime | None, zone: str) -> datetime | None:
    if value is None:
        return None
    tz = ZoneInfo(zone)
    candidates = [value.replace(tzinfo=tz, fold=fold) for fold in (0, 1)]
    if candidates[0].utcoffset() != candidates[1].utcoffset():
        raise ValueError(f"夏令时歧义或不存在的本地时间，需人工确认：{value}")
    result = candidates[0].astimezone(timezone.utc)
    if result.astimezone(tz).replace(tzinfo=None) != value:
        raise ValueError(f"不存在的本地时间：{value}")
    return result.replace(tzinfo=None)


def snapshot(row) -> dict:
    return {"started_at": row.started_at.isoformat() if row.started_at else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "time_basis": row.time_basis}


async def make_plan(db, ids: list[int], source_zone: str) -> dict:
    rows = list((await db.scalars(select(Pomodoro).where(Pomodoro.id.in_(ids)).order_by(Pomodoro.id))).all())
    if {row.id for row in rows} != set(ids):
        raise ValueError("部分指定记录不存在")
    plan = {"version": 1, "source_zone": source_zone, "records": []}
    for row in rows:
        if row.time_basis not in ("legacy", "mixed"):
            raise ValueError(f"记录 {row.id} 已是 UTC，不允许重复转换")
        fields = ["started_at"] + (["ended_at"] if row.time_basis == "legacy" else [])
        after = snapshot(row)
        for field in fields:
            value = convert(getattr(row, field), source_zone)
            after[field] = value.isoformat() if value else None
        after["time_basis"] = "utc"
        events = []
        for field, suffixes in (("started_at", ("started",)), ("ended_at", ("completed", "interrupted"))):
            if field not in fields:
                continue
            keys = [f"pomodoro.{suffix}:{row.id}" for suffix in suffixes]
            for event in (await db.scalars(select(LearningEvent).where(
                    LearningEvent.user_id == row.user_id, LearningEvent.dedupe_key.in_(keys)))).all():
                target = convert(event.timestamp, source_zone)
                events.append({"id": event.id, "before": event.timestamp.isoformat(), "after": target.isoformat()})
        plan["records"].append({"id": row.id, "user_id": row.user_id,
                                "before": snapshot(row), "after": after, "events": events})
    return plan


async def apply_plan(db, plan: dict) -> int:
    if plan.get("version") != 1:
        raise ValueError("迁移计划版本不支持")
    for user_id in sorted({item["user_id"] for item in plan["records"]}):
        await lock_user_mutation(db, user_id)
    changes = []
    # Validate every snapshot before applying any updates; reruns are harmless.
    for item in plan["records"]:
        row = await db.get(Pomodoro, item["id"], populate_existing=True)
        if row is None or row.user_id != item["user_id"]:
            raise ValueError("记录归属变化或记录已删除，请重新预览")
        current = snapshot(row)
        if current == item["after"]:
            continue
        if current != item["before"]:
            raise ValueError(f"记录 {row.id} 已变化，请重新预览")
        events = []
        for event_data in item["events"]:
            event = await db.get(LearningEvent, event_data["id"], populate_existing=True)
            if event is None or event.user_id != row.user_id or event.timestamp.isoformat() != event_data["before"]:
                raise ValueError("关联学习事件已变化，请重新预览")
            events.append((event, datetime.fromisoformat(event_data["after"])))
        changes.append((row, item["after"], events))
    concepts = set()
    for row, after, events in changes:
        row.started_at = datetime.fromisoformat(after["started_at"]) if after["started_at"] else None
        row.ended_at = datetime.fromisoformat(after["ended_at"]) if after["ended_at"] else None
        row.time_basis = "utc"
        for event, timestamp in events:
            event.timestamp = timestamp
            for evidence in (await db.scalars(select(LearnerEvidence).where(
                    LearnerEvidence.user_id == row.user_id, LearnerEvidence.source_event_id == event.id))).all():
                evidence.observed_at = timestamp
                concepts.add((row.user_id, evidence.concept_id))
            await db.execute(update(ProjectionOutbox).where(
                ProjectionOutbox.user_id == row.user_id, ProjectionOutbox.source_event_id == event.id,
            ).values(occurred_at=timestamp))
    await db.flush()
    from app.services.learner_model_service import recompute_concept_state
    for user_id, concept_id in concepts:
        await recompute_concept_state(db, user_id, concept_id)
    return len(changes)


async def main(args):
    from app.database import async_session_maker
    async with async_session_maker() as db:
        if args.apply:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
            count = await apply_plan(db, plan)
            await db.commit()
            print(f"已转换 {count} 条记录；created_at 和实际专注时长保持不变。")
        else:
            if not args.ids or not args.source_zone:
                raise ValueError("预览必须明确指定 --ids 和 --source-zone，不能自动猜测旧时间")
            plan = await make_plan(db, json.loads(args.ids.read_text()), args.source_zone)
            with args.plan.open("x", encoding="utf-8") as output:
                json.dump(plan, output, ensure_ascii=False, indent=2)
            print(f"已生成 {len(plan['records'])} 条转换计划，数据库未修改。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", type=Path, help="人工确认的一组记录 ID 的 JSON 数组")
    parser.add_argument("--source-zone", help="例如 Asia/Shanghai；已是 UTC 的旧记录使用 UTC")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args()))
