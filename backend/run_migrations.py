"""Execute database migration helpers.

SQLite development databases are covered by ``app.database.init_db`` lightweight
column checks. For non-SQLite deployments this runner applies the checked-in SQL
files in a stable order so model columns do not drift between environments.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text

from app.config import settings
from app.database import engine, init_db


MIGRATION_ORDER = [
    "add_user_scope_and_agent_fields.sql",
    "add_goal_plan_fields.sql",
    "add_daily_plan_task_ids.sql",
    "add_pomodoro_stop_reason.sql",
    "add_review_schedule_is_archived.sql",
    "add_ai_search_and_token_settings.sql",
    "add_web_search_cache.sql",
    "add_coach_kernel_tables.sql",
    "add_coach_skill_stats.sql",
    "add_learning_event_metadata.sql",
    "add_agent_memory_metadata.sql",
]


def _is_sqlite_url(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def _split_sql(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_dollar_quote = False
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            current.append(line)
            continue
        if "$$" in line:
            in_dollar_quote = not in_dollar_quote
        current.append(line)
        if not in_dollar_quote and stripped.endswith(";"):
            statement = "\n".join(current).strip()
            if statement:
                statements.append(statement.rstrip(";"))
            current = []
    tail = "\n".join(current).strip()
    if tail:
        statements.append(tail.rstrip(";"))
    return statements


async def _run_sql_file(path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    statements = _split_sql(sql)
    print(f"\n{'=' * 60}")
    print(f"执行迁移文件: {path.name}")
    print(f"{'=' * 60}")
    for index, statement in enumerate(statements, 1):
        try:
            preview = " ".join(statement.split())[:110]
            print(f"[{index}/{len(statements)}] {preview}...")
            async with engine.begin() as conn:
                await conn.execute(text(statement))
        except Exception as exc:
            message = str(exc).lower()
            if any(token in message for token in ("duplicate column", "already exists", "duplicate key")):
                print("  字段或对象已存在，跳过")
                continue
            raise


async def run_migrations() -> None:
    """Run migrations for the configured database."""

    if _is_sqlite_url(settings.DATABASE_URL):
        print("检测到 SQLite，执行 Base.metadata.create_all + 轻量迁移。")
        await init_db()
        print("SQLite 迁移检查完成。")
        return

    migration_dir = Path(__file__).parent / "migrations"
    for filename in MIGRATION_ORDER:
        path = migration_dir / filename
        if not path.exists():
            print(f"跳过缺失迁移文件: {filename}")
            continue
        await _run_sql_file(path)

    print(f"\n{'=' * 60}")
    print("所有迁移文件执行完成。")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(run_migrations())
