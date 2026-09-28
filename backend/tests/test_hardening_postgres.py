"""Opt-in destructive rehearsal, restricted to an empty disposable loopback DB."""
import asyncio
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text, select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


def test_postgres_hardening_migration_and_concurrent_mutations():
    url = os.getenv("MNEMOX_HARDENING_PG_TEST_URL")
    if not url:
        pytest.skip("Requires a disposable PostgreSQL rehearsal database")
    parsed = urlparse(url)
    assert parsed.scheme == "postgresql+asyncpg"
    assert parsed.hostname in {"localhost", "127.0.0.1"}
    assert parsed.path == "/hardening_test" and parsed.username == "hardening_test"

    async def empty():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                assert await conn.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")) == 0
        finally:
            await engine.dispose()
    asyncio.run(empty())
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "20260925_26")

    async def seed():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("INSERT INTO users(id,username,email,hashed_password) VALUES (1,'pg-rehearsal','pg@test.invalid','hash')"))
                await conn.execute(text("""INSERT INTO review_schedule
                    (id,user_id,item_type,item_id,repetitions,stability,is_archived,last_review_at)
                    VALUES (1,1,'chapter',10,7,20,TRUE,'2026-09-20'),
                           (2,1,'chapter',10,4,30,FALSE,'2026-09-25')"""))
        finally:
            await engine.dispose()
    asyncio.run(seed())
    command.upgrade(config, "head")
    command.check(config)

    async def verify():
        from app.models.anki import AnkiCard
        from app.models.chat import ChatConversation, ChatMessage
        from app.models.pomodoro import Pomodoro
        from app.models.learning_event import LearningEvent
        from app.routers.anki import review_card, AnkiCardReview
        from app.routers.chat import ChatRequest
        from app.routers.pomodoro import PomodoroCreate, start_pomodoro, PomodorosBatchCreate, batch_create_pomodoros
        from app.services.chat_progress import save_chat_progress
        engine = create_async_engine(url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        actor = SimpleNamespace(id=1)
        try:
            async with sessions() as db:
                assert tuple((await db.execute(text("SELECT id,repetitions,stability,is_archived FROM review_schedule"))).one()) == (2, 7, 30, True)
                assert await db.scalar(text("SELECT count(*) FROM review_schedule_merge_audit")) == 2
                card = AnkiCard(user_id=1, front="front", back="back")
                conversation = ChatConversation(user_id=1)
                db.add_all([card, conversation])
                await db.commit()
                card_id, conversation_id = card.id, conversation.id
            grade = AnkiCardReview(attempt_id=uuid.uuid4(), quality=4, expected_version=1)
            async def review():
                async with sessions() as db:
                    result = await review_card(card_id, grade, db, actor)
                    await db.commit()
                    return json.loads(result.body) if hasattr(result, "body") else result
            results = await asyncio.gather(review(), review())
            assert results[0] == results[1] and results[0]["sync_version"] == 2
            start_body = PomodoroCreate(task_name="pg timer", duration=25, client_record_id="pg-focus",
                                       started_at="2026-09-25T17:00:00+08:00")
            async def start():
                async with sessions() as db:
                    result = await start_pomodoro(start_body, db, actor)
                    await db.commit()
                    return result.id
            ids = await asyncio.gather(start(), start())
            assert ids[0] == ids[1]
            batch = PomodorosBatchCreate(records=[dict(task_name="pg timer", duration=5,
                client_record_id="pg-focus", completed=False, stop_reason="interrupted")],
                completed_ats=["2026-09-25T17:05:00+08:00"])
            async def finish():
                async with sessions() as db:
                    await batch_create_pomodoros(batch, db, actor)
                    await db.commit()
            await asyncio.gather(finish(), finish())
            body = ChatRequest(message="durable", conversation_id=conversation_id)
            await asyncio.gather(*(save_chat_progress(body=body, user_id=1, sessionmaker=sessions) for _ in range(2)))
            await save_chat_progress(body=body, user_id=1, content="partial", status="interrupted", sessionmaker=sessions)
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(Pomodoro)) == 1
                timer = await db.get(Pomodoro, ids[0])
                assert timer.started_at.hour == 9 and timer.ended_at.hour == 9
                assert timer.completed is False and timer.stop_reason == "interrupted"
                assert await db.scalar(select(func.count()).select_from(LearningEvent).where(LearningEvent.event_type == "review.completed")) == 1
                messages = (await db.scalars(select(ChatMessage).order_by(ChatMessage.id))).all()
                assert [(m.content, m.status) for m in messages] == [("durable", "completed"), ("partial", "interrupted")]
        finally:
            await engine.dispose()
    asyncio.run(verify())
