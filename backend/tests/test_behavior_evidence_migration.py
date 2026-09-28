"""Upgrade historical focus records without fabricating actual measurements."""
import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import _run_lightweight_migrations


@pytest.mark.parametrize("mode", ["sqlite_alembic", "sqlite_lightweight", "postgres"])
def test_evidence_columns_preserve_unknown_history(tmp_path, mode):
    url = f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"
    if mode == "postgres":
        url = os.getenv("MNEMOX_EVIDENCE_PG_TEST_URL")
        if not url:
            pytest.skip("Requires an empty disposable PostgreSQL evidence database")
        parsed = urlparse(url)
        assert parsed.scheme == "postgresql+asyncpg"
        assert parsed.hostname in {"localhost", "127.0.0.1"}
        assert parsed.path == "/behavior_evidence_test" and parsed.username == "evidence_test"

    async def query(statement):
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(statement))
                return result.all() if result.returns_rows else []
        finally:
            await engine.dispose()

    if mode == "postgres":
        assert asyncio.run(query("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"))[0][0] == 0
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "20260925_28")
    asyncio.run(query("INSERT INTO users(id,username,email,hashed_password) VALUES (1,'evidence','evidence@test.invalid','hash')"))
    asyncio.run(query("INSERT INTO pomodoros(id,user_id,duration,time_basis,completed) VALUES (1,1,50,'legacy',FALSE)"))

    if mode == "sqlite_lightweight":
        async def lightweight():
            engine = create_async_engine(url)
            try:
                async with engine.begin() as conn:
                    await _run_lightweight_migrations(conn)
                    await _run_lightweight_migrations(conn)
            finally:
                await engine.dispose()
        asyncio.run(lightweight())
    else:
        command.upgrade(config, "head")
        command.downgrade(config, "20260925_28")
        command.upgrade(config, "head")

    rows = asyncio.run(query("SELECT duration,planned_duration,actual_duration,record_origin,time_basis FROM pomodoros WHERE id=1"))
    assert tuple(rows[0]) == (50, None, None, "legacy", "legacy")
    if mode == "postgres":
        command.check(config)
