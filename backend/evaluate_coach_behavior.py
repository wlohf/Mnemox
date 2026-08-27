"""Run the isolated synthetic Coach behavior regression simulation.

The command creates a temporary SQLite database, then deletes it when the
process ends.  It is deliberately unable to target an application database.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - registers every mapped table with Base.
from app.database import Base
from app.models.user import User
from app.services.coach_behavior_simulation_service import build_synthetic_coach_behavior_report


async def _run(output: Path | None) -> dict:
    with tempfile.TemporaryDirectory(prefix="mnemox-coach-simulation-") as directory:
        database_url = f"sqlite+aiosqlite:///{Path(directory) / 'simulation.sqlite3'}"
        engine = create_async_engine(database_url, future=True)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                user = User(
                    username="synthetic_coach_eval",
                    email="synthetic-coach-eval@example.invalid",
                    hashed_password="synthetic-only",
                    is_active=True,
                )
                session.add(user)
                await session.flush()
                report = await build_synthetic_coach_behavior_report(session, int(user.id))
                await session.commit()
        finally:
            await engine.dispose()

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON report path outside application data.")
    args = parser.parse_args()
    report = asyncio.run(_run(args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
