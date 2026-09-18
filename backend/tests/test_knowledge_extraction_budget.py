"""Synthetic transactional tests for the durable LLM extraction call ledger."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.extraction_budget import ExtractionCall, ExtractionDailyBudget
from app.models.knowledge import KnowledgeExtractionRun, KnowledgeSource, KnowledgeSourceRevision, KnowledgeUnit
from app.models.user import User
from app.services.extraction_budget_service import (
    ExtractionBudgetExceeded,
    ExtractionLeaseLost,
    reserve_extraction_call,
    settle_extraction_call,
)


class ExtractionBudgetLedgerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = await self._test_engine()
        async with self.engine.begin() as connection:
            if self.engine.dialect.name == 'sqlite':
                await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.now = datetime(2030, 6, 2, 12, 0, 0)
        async with self.sessions() as db:
            user = User(username="ledger-owner", email="ledger-owner@example.test", hashed_password="hash")
            db.add(user)
            await db.flush()
            self.user_id = int(user.id)
            self.run_id, self.unit_id, self.lease_token = await self._add_run(db, "one")
            await db.commit()

    async def _test_engine(self):
        return create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'ledger.db'}", connect_args={'timeout': 10})

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _add_run(self, db, suffix: str) -> tuple[int, int, str]:
        self.source_count = getattr(self, 'source_count', 0) + 1
        source = KnowledgeSource(
            user_id=self.user_id,
            source_type="material",
            source_record_id=self.source_count,
            source_key=f"synthetic-{suffix}",
            title_snapshot="Synthetic",
        )
        db.add(source)
        await db.flush()
        revision = KnowledgeSourceRevision(
            user_id=self.user_id,
            knowledge_source_id=int(source.id),
            revision=1,
            content_hash=(suffix * 64)[:64],
            title_snapshot="Synthetic",
        )
        db.add(revision)
        await db.flush()
        unit = KnowledgeUnit(
            user_id=self.user_id,
            source_revision_id=int(revision.id),
            unit_type="chunk",
            ordinal=0,
            text="synthetic source only",
            text_hash=("u" + suffix * 64)[:64],
            locator={},
        )
        token = str(uuid4())
        run = KnowledgeExtractionRun(
            user_id=self.user_id,
            source_revision_id=int(revision.id),
            extractor_type="llm",
            extractor_version="test-v1",
            schema_version=1,
            input_hash=("r" + suffix * 64)[:64],
            status="running",
            available_at=self.now,
            lease_token=token,
            lease_expires_at=self.now + timedelta(days=2),
            usage={},
            stats={},
        )
        db.add_all([unit, run])
        await db.flush()
        return int(run.id), int(unit.id), token

    async def _reserve(self, db, *, run_id=None, unit_id=None, lease_token=None, estimate=40, now=None):
        return await reserve_extraction_call(
            db,
            call_id=str(uuid4()),
            user_id=self.user_id,
            run_id=self.run_id if run_id is None else run_id,
            unit_id=self.unit_id if unit_id is None else unit_id,
            lease_token=self.lease_token if lease_token is None else lease_token,
            estimated_tokens=estimate,
            now=self.now if now is None else now,
        )

    async def test_today_bucket_is_not_run_creation_day(self):
        yesterday = self.now - timedelta(days=1)
        async with self.sessions() as db:
            run = await db.get(KnowledgeExtractionRun, self.run_id)
            run.created_at = yesterday
            await self._reserve(db, estimate=40)
            await db.commit()
        async with self.sessions() as db:
            bucket = await db.scalar(select(ExtractionDailyBudget))
            self.assertEqual(bucket.execution_day, self.now.date())
            self.assertEqual(bucket.charged_tokens, 40)

    async def test_concurrent_runs_cannot_overspend_one_user_day(self):
        async with self.sessions() as db:
            second_run_id, second_unit_id, second_lease = await self._add_run(db, "two")
            await db.commit()

        async def reserve_and_finish(run_id, unit_id, token):
            async with self.sessions() as db:
                try:
                    await self._reserve(
                        db,
                        run_id=run_id,
                        unit_id=unit_id,
                        lease_token=token,
                        estimate=60,
                    )
                    await db.commit()
                    return "reserved"
                except ExtractionBudgetExceeded:
                    await db.rollback()
                    return "blocked"

        with patch.object(settings, "KNOWLEDGE_LLM_DAILY_ESTIMATED_TOKENS_PER_USER", 100):
            outcomes = await asyncio.gather(
                reserve_and_finish(self.run_id, self.unit_id, self.lease_token),
                reserve_and_finish(second_run_id, second_unit_id, second_lease),
            )
        self.assertEqual(sorted(outcomes), ["blocked", "reserved"])
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.sum(ExtractionDailyBudget.charged_tokens))), 60)
            self.assertEqual(await db.scalar(select(func.count(ExtractionCall.id))), 1)

    async def test_per_run_budget_survives_days_and_retries(self):
        with patch.object(settings, "KNOWLEDGE_LLM_MAX_ESTIMATED_TOKENS_PER_RUN", 100):
            async with self.sessions() as db:
                await self._reserve(db, estimate=60)
                await db.commit()
            async with self.sessions() as db:
                with self.assertRaises(ExtractionBudgetExceeded):
                    await self._reserve(db, estimate=50, now=self.now + timedelta(days=1))
                await db.rollback()

    async def test_rollback_removes_call_and_day_charge(self):
        async with self.sessions() as db:
            await self._reserve(db, estimate=40)
            await db.rollback()
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count(ExtractionCall.id))), 0)
            self.assertEqual(await db.scalar(select(func.count(ExtractionDailyBudget.id))), 0)

    async def test_settlement_is_idempotent_and_sanitizes_usage(self):
        async with self.sessions() as db:
            call = await self._reserve(db, estimate=40)
            call_id = call.id
            await db.commit()
        usage = {
            "total_tokens": 75,
            "configured_cost_usd": 0.012,
            "secret-bearing-token-key": 1000,
            "source_text": "must never persist",
            "prompt": "must never persist",
            "output": {"content": "must never persist"},
        }
        async with self.sessions() as db:
            self.assertTrue(await settle_extraction_call(db, call_id=call_id, state="succeeded", usage=usage, now=self.now))
            await db.commit()
        async with self.sessions() as db:
            self.assertFalse(await settle_extraction_call(db, call_id=call_id, state="succeeded", usage={"total_tokens": 900}, now=self.now))
            await db.commit()
        async with self.sessions() as db:
            call = await db.get(ExtractionCall, call_id)
            bucket = await db.scalar(select(ExtractionDailyBudget))
            self.assertEqual(call.charged_tokens, 75)
            self.assertEqual(bucket.charged_tokens, 75)
            self.assertEqual(call.usage, {"total_tokens": 75, "configured_cost_usd": 0.012})
            self.assertNotIn("source", repr(call.usage).lower())
            self.assertFalse(hasattr(call, "prompt"))
            self.assertFalse(hasattr(call, "output"))

    async def test_failed_and_unknown_calls_keep_reservations(self):
        async with self.sessions() as db:
            failed = await self._reserve(db, estimate=30)
            unknown = await self._reserve(db, estimate=20)
            await db.commit()
        async with self.sessions() as db:
            self.assertTrue(await settle_extraction_call(db, call_id=failed.id, state="failed", usage={"total_tokens": 2}))
            self.assertTrue(await settle_extraction_call(db, call_id=unknown.id, state="unknown"))
            await db.commit()
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.sum(ExtractionDailyBudget.charged_tokens))), 50)
            states = set((await db.scalars(select(ExtractionCall.state))).all())
            self.assertEqual(states, {"failed", "unknown"})

    async def test_legacy_usage_is_not_reset_by_first_post_upgrade_call(self):
        async with self.sessions() as db:
            run = await db.get(KnowledgeExtractionRun, self.run_id)
            run.usage = {'call_count': 4, 'estimated_tokens': 100}
            await db.commit()
        async with self.sessions() as db:
            with self.assertRaisesRegex(ExtractionBudgetExceeded, 'Legacy'):
                await self._reserve(db)
            await db.rollback()

    async def test_concurrent_settlements_charge_excess_once(self):
        async with self.sessions() as db:
            call_id = (await self._reserve(db)).id
            await db.commit()

        async def settle():
            async with self.sessions() as db:
                result = await settle_extraction_call(db, call_id=call_id, state='succeeded', usage={'total_tokens': 80})
                await db.commit()
                return result
        self.assertEqual(sorted(await asyncio.gather(settle(), settle())), [False, True])
        async with self.sessions() as db:
            self.assertEqual((await db.scalar(select(ExtractionDailyBudget))).charged_tokens, 80)

    async def test_new_run_cannot_evade_another_legacy_run_for_same_user(self):
        async with self.sessions() as db:
            old = await db.get(KnowledgeExtractionRun, self.run_id)
            old.budget_review_required = True
            old.usage = {}  # Even an unconfirmed pre-upgrade call has no known day.
            run_id, unit_id, token = await self._add_run(db, 'new')
            await db.commit()
        async with self.sessions() as db:
            with self.assertRaisesRegex(ExtractionBudgetExceeded, 'Legacy'):
                await self._reserve(db, run_id=run_id, unit_id=unit_id, lease_token=token)
            await db.rollback()

    async def test_unknown_can_be_refined_once_without_refund_or_day_change(self):
        async with self.sessions() as db:
            call = await self._reserve(db)
            call_id = call.id
            await settle_extraction_call(db, call_id=call_id, state='unknown', usage={'total_tokens': 60}, now=self.now)
            await db.commit()
        async with self.sessions() as db:
            self.assertTrue(await settle_extraction_call(db, call_id=call_id, state='succeeded', usage={'total_tokens': 80}, now=self.now + timedelta(days=1)))
            self.assertFalse(await settle_extraction_call(db, call_id=call_id, state='succeeded', usage={'total_tokens': 100}))
            await db.commit()
        async with self.sessions() as db:
            bucket = await db.scalar(select(ExtractionDailyBudget))
            self.assertEqual(bucket.execution_day, self.now.date())
            self.assertEqual(bucket.charged_tokens, 80)

    async def test_foreign_source_unit_cannot_be_charged_to_a_valid_lease(self):
        async with self.sessions() as db:
            _, unit_id, _ = await self._add_run(db, 'foreign')
            await db.commit()
        async with self.sessions() as db:
            with self.assertRaises(ExtractionLeaseLost):
                await self._reserve(db, unit_id=unit_id)
            await db.rollback()

    async def test_lease_mismatch_is_rejected(self):
        async with self.sessions() as db:
            with self.assertRaises(ExtractionLeaseLost):
                await self._reserve(db, lease_token=str(uuid4()))
            await db.rollback()


if __name__ == "__main__":
    unittest.main()
