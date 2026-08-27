"""Regression coverage for the isolated virtual-learner Coach simulation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.services.coach_behavior_simulation_service import build_synthetic_coach_behavior_report


class CoachBehaviorSimulationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmpdir.name) / 'simulation.sqlite3'}",
            future=True,
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def test_synthetic_behavior_report_passes_without_claiming_real_world_effect(self):
        async with self.sessions() as session:
            user = User(
                username="synthetic",
                email="synthetic@example.invalid",
                hashed_password="synthetic-only",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            report = await build_synthetic_coach_behavior_report(session, int(user.id))
            await session.commit()

        self.assertTrue(report["passed"])
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(report["metrics"]["suggestion_execution_rate"]["value"], 75.0)
        self.assertEqual(report["metrics"]["suggestion_execution_rate"]["completed_by_domain_event_count"], 4)
        self.assertEqual(report["metrics"]["suggestion_execution_rate"]["completed_by_user_confirmation_count"], 2)
        self.assertIn("不能证明", report["simulation"]["important_limit"])
        self.assertEqual(report["next_evidence"]["model_promotion"], "学习者模型仍只接受真实 holdout 数据，不接受本模拟数据。")
