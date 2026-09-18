"""Fault injection at real SQLite checkpoint boundaries; no provider/network access."""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import event, func, inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.extraction_budget import ExtractionCall, ExtractionDailyBudget
from app.models.knowledge import Claim, KnowledgeExtractionRun, KnowledgeSource, KnowledgeSourceRevision, KnowledgeUnit
from app.models.user import User
from app.models.concept import Concept
from app.services.concept_service import normalize_concept_name
from app.schemas.knowledge_extraction import KnowledgeExtractionResult
from app.services.extraction_budget_service import ExtractionLeaseLost
from app.services.knowledge_extraction_service import (
    cancel_extraction_run, claim_next_extraction_run, mark_extraction_run_failed,
    process_claimed_extraction_run, retry_extraction_run,
)
from app.services.knowledge_extraction_worker import KnowledgeExtractionWorker
from app.services.knowledge_source_service import delete_source
from app.utils.utc import utc_now_db


def candidate(unit, label='grounded', concepts=None):
    return KnowledgeExtractionResult.model_validate({'claims': [{
        'local_id': 'c1', 'statement': f'{label} fact from unit {unit.ordinal}.',
        'claim_kind': 'observation', 'evidence': [{'quote': unit.text}],
        'concepts': concepts or [], 'confidence': 0.9,
    }], 'relations': []})


class ExtractionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = await self._test_engine()

        if self.engine.dialect.name == 'sqlite':
            @event.listens_for(self.engine.sync_engine, 'connect')
            def pragmas(connection, _):
                connection.execute('PRAGMA foreign_keys=ON')
                connection.execute('PRAGMA journal_mode=WAL')

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            user = User(username='runtime_user', email='runtime@example.test', hashed_password='synthetic')
            db.add(user); await db.commit(); self.user_id = user.id
        self.patches = [patch.object(settings, key, value) for key, value in {
            'KNOWLEDGE_V2_ENABLED': True, 'KNOWLEDGE_LLM_EXTRACTION_ENABLED': True,
            'KNOWLEDGE_EMBEDDING_ENABLED': False,
        }.items()]
        for item in self.patches:
            item.start()
        self.release = asyncio.Event()
        self.entered = asyncio.Event()
        self.orphans = set()
        self.tasks = []
        self.worker = None

    async def _test_engine(self):
        return create_async_engine(f'sqlite+aiosqlite:///{Path(self.tmp.name) / "runtime.db"}')

    async def asyncTearDown(self):
        self.release.set()
        if self.worker:
            await self.worker.stop()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await asyncio.gather(*list(self.orphans), return_exceptions=True)
        if self.worker:
            await asyncio.gather(*list(self.worker._orphan_tasks), return_exceptions=True)
        for item in reversed(self.patches):
            item.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def seed(self, *, units=1, kind='deterministic', claim=True, lease=10):
        async with self.sessions() as db:
            source = KnowledgeSource(user_id=self.user_id, source_type='material', source_record_id=1,
                                     source_key='material:1', title_snapshot='Synthetic', current_revision=1)
            db.add(source); await db.flush()
            revision = KnowledgeSourceRevision(user_id=self.user_id, knowledge_source_id=source.id,
                                               revision=1, content_hash='a' * 64, title_snapshot='Synthetic')
            db.add(revision); await db.flush()
            self.unit_ids = []
            for ordinal in range(units):
                text = f'Synthetic evidence {ordinal}.'
                unit = KnowledgeUnit(user_id=self.user_id, source_revision_id=revision.id,
                                     unit_type='chunk', ordinal=ordinal, text=text,
                                     text_hash=hashlib.sha256(text.encode()).hexdigest(), locator={})
                db.add(unit); await db.flush(); self.unit_ids.append(unit.id)
            run = KnowledgeExtractionRun(user_id=self.user_id, source_revision_id=revision.id,
                                         extractor_type=kind, extractor_version='test-v1', schema_version=1,
                                         input_hash='b' * 64, status='queued', usage={}, stats={})
            db.add(run); await db.commit(); self.run_id = run.id
        if claim:
            return await self.claim(lease=lease)

    async def claim(self, *, lease=10):
        async with self.sessions() as db:
            run = await claim_next_extraction_run(db, worker_id='same-worker', lease_seconds=lease)
            await db.commit()
            return run

    def launch(self, run, **kwargs):
        task = asyncio.create_task(process_claimed_extraction_run(
            self.sessions, run_id=run.id, worker_id='same-worker', lease_token=run.lease_token,
            orphan_tasks=self.orphans, **kwargs,
        ))
        self.tasks.append(task)
        return task

    def slow_extractor(self, *, second_only=False, ignore_cancel=False):
        outer = self

        class Slow:
            async def extract(self, unit):
                outer.assertTrue(inspect(unit).detached)
                if not second_only or unit.ordinal == 1:
                    outer.entered.set()
                    try:
                        await outer.release.wait()
                    except asyncio.CancelledError:
                        if not ignore_cancel:
                            raise
                        await outer.release.wait()
                return candidate(unit)
        return Slow()

    async def test_unit_checkpoint_survives_cancellation_and_resume_without_open_transaction(self):
        run = await self.seed(units=2)
        task = self.launch(run, extractor=self.slow_extractor(second_only=True))
        await asyncio.wait_for(self.entered.wait(), 5)
        self.assertEqual(self.engine.pool.checkedout(), 0, 'Provider must not retain a SQL connection')

        async def independent_write():
            async with self.sessions() as db:
                self.assertEqual(await db.scalar(select(func.count(Claim.id))), 1)
                stored = await db.get(KnowledgeExtractionRun, run.id)
                self.assertEqual(stored.stats['processed_unit_ids'], [self.unit_ids[0]])
                user = await db.get(User, self.user_id)
                user.email = 'unblocked@example.test'
                await db.commit()
        await asyncio.wait_for(independent_write(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        async with self.sessions() as db:
            stored = await db.get(KnowledgeExtractionRun, run.id)
            stored.lease_expires_at = utc_now_db() - timedelta(seconds=1)
            await db.commit()
        resumed = await self.claim()
        calls = []

        class Resumed:
            async def extract(self, unit):
                calls.append(unit.ordinal)
                return candidate(unit)
        done = await self.launch(resumed, extractor=Resumed())
        self.assertEqual(done.status, 'succeeded')
        self.assertEqual(calls, [1])
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count(Claim.id))), 2)

    async def test_user_cancel_fences_ignored_cancellation_and_late_result(self):
        run = await self.seed()
        task = self.launch(run, extractor=self.slow_extractor(ignore_cancel=True))
        await asyncio.wait_for(self.entered.wait(), 5)
        async with self.sessions() as db:
            await cancel_extraction_run(db, user_id=self.user_id, run_id=run.id)
            await db.commit()
        with self.assertRaises(ExtractionLeaseLost):
            await asyncio.wait_for(asyncio.shield(task), 3)
        self.release.set()
        await asyncio.gather(*list(self.orphans), return_exceptions=True)
        async with self.sessions() as db:
            self.assertEqual((await db.get(KnowledgeExtractionRun, run.id)).status, 'cancelled')
            self.assertEqual(await db.scalar(select(func.count(Claim.id))), 0)

    async def test_source_delete_is_not_blocked_by_model_and_late_output_cannot_resurrect(self):
        run = await self.seed()
        task = self.launch(run, extractor=self.slow_extractor())
        await asyncio.wait_for(self.entered.wait(), 5)
        async with self.sessions() as db:
            self.assertTrue(await delete_source(db, user_id=self.user_id, source_type='material', source_record_id=1))
            await db.commit()
        self.release.set()
        with self.assertRaises(ExtractionLeaseLost):
            await task
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count(Claim.id))), 0)
            self.assertEqual((await db.get(KnowledgeExtractionRun, run.id)).status, 'cancelled')

    async def test_same_worker_reclaim_uses_new_token_and_rejects_old_failure_and_output(self):
        run = await self.seed()
        task = self.launch(run, extractor=self.slow_extractor())
        await asyncio.wait_for(self.entered.wait(), 5)
        async with self.sessions() as db:
            stored = await db.get(KnowledgeExtractionRun, run.id)
            stored.lease_expires_at = utc_now_db() - timedelta(seconds=1)
            await db.commit()
        fresh = await self.claim()
        self.assertNotEqual(run.lease_token, fresh.lease_token)
        async with self.sessions() as db:
            self.assertFalse(await mark_extraction_run_failed(
                db, run_id=run.id, worker_id='same-worker', lease_token=run.lease_token,
                error=RuntimeError('old error'), retry_delay_seconds=0,
            ))
            await db.commit()
        self.release.set()
        with self.assertRaises(ExtractionLeaseLost):
            await task
        async with self.sessions() as db:
            self.assertEqual((await db.get(KnowledgeExtractionRun, run.id)).lease_token, fresh.lease_token)
            self.assertEqual(await db.scalar(select(func.count(Claim.id))), 0)

    async def test_heartbeat_extends_lease_without_holding_it_during_model_wait(self):
        run = await self.seed(lease=1)
        task = self.launch(run, extractor=self.slow_extractor(), lease_seconds=1)
        await asyncio.wait_for(self.entered.wait(), 5)
        await asyncio.sleep(1.4)
        self.assertIsNone(await self.claim(lease=1))
        self.release.set()
        self.assertEqual((await task).status, 'succeeded')

    async def test_worker_stop_is_bounded_even_if_provider_ignores_cancel(self):
        await self.seed(claim=False)
        real_process = process_claimed_extraction_run
        slow = self.slow_extractor(ignore_cancel=True)

        async def injected(*args, **kwargs):
            return await real_process(*args, **kwargs, extractor=slow)
        self.worker = KnowledgeExtractionWorker(self.sessions, worker_id='shutdown-worker', batch_size=1,
                                                shutdown_grace_seconds=0.5)
        with patch('app.services.knowledge_extraction_worker.process_claimed_extraction_run', side_effect=injected):
            self.worker.start()
            await asyncio.wait_for(self.entered.wait(), 5)
            started = time.monotonic()
            await self.worker.stop()
            self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(self.worker.health_snapshot()['pending_provider_tasks'], 1)
        async with self.sessions() as db:
            self.assertEqual((await db.get(KnowledgeExtractionRun, self.run_id)).status, 'queued')
            self.assertEqual(await db.scalar(select(func.count(Claim.id))), 0)
        self.release.set()

    def provider(self, *, fallback=False, block=False, ignore_cancel=False, actual_tokens=5):
        outer = self

        class Provider:
            model = 'synthetic'
            max_output_tokens = 512
            calls = 0
            usage = {}

            def supports_structured_output(self):
                return fallback

            def clear_last_usage(self):
                self.usage = {}

            def get_last_usage(self):
                return self.usage

            async def chat_structured(self, **kwargs):
                self.calls += 1
                raise NotImplementedError('structured output is unsupported')

            async def chat(self, **kwargs):
                self.calls += 1
                outer.assertEqual(outer.engine.pool.checkedout(), 0)
                if block:
                    outer.entered.set()
                    try:
                        await outer.release.wait()
                    except asyncio.CancelledError:
                        if not ignore_cancel:
                            raise
                        await outer.release.wait()
                self.usage = {'input_tokens': 3, 'output_tokens': 2, 'total_tokens': actual_tokens}
                unit = type('Unit', (), {'ordinal': 0, 'text': 'Synthetic evidence 0.'})()
                return candidate(unit).model_dump_json()
        return Provider()

    async def test_structured_fallback_is_two_durable_charged_attempts(self):
        run = await self.seed(kind='llm')
        provider = self.provider(fallback=True)
        finished = await self.launch(run, provider=provider)
        self.assertEqual(finished.status, 'succeeded')
        self.assertEqual(provider.calls, 2)
        self.assertEqual(finished.usage['call_count'], 2)
        async with self.sessions() as db:
            calls = list((await db.scalars(select(ExtractionCall))).all())
            self.assertEqual({call.state for call in calls}, {'failed', 'succeeded'})
            self.assertEqual((await db.scalar(select(ExtractionDailyBudget))).charged_tokens,
                             sum(call.charged_tokens for call in calls))

    async def test_one_call_cap_prevents_unbudgeted_structured_fallback(self):
        run = await self.seed(kind='llm')
        provider = self.provider(fallback=True)
        with patch.object(settings, 'KNOWLEDGE_LLM_MAX_CALLS_PER_RUN', 1):
            result = await self.launch(run, provider=provider)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(provider.calls, 1)
        self.assertEqual(result.usage['call_count'], 1)

    async def test_cancelled_llm_call_remains_charged_and_visible_without_domain_writes(self):
        run = await self.seed(kind='llm')
        task = self.launch(run, provider=self.provider(block=True))
        await asyncio.wait_for(self.entered.wait(), 5)
        async with self.sessions() as db:
            await cancel_extraction_run(db, user_id=self.user_id, run_id=run.id)
            await db.commit()
        with self.assertRaises(ExtractionLeaseLost):
            await task
        async with self.sessions() as db:
            call = await db.scalar(select(ExtractionCall))
            self.assertEqual(call.state, 'unknown')
            self.assertGreater(call.charged_tokens, 0)
            stored = await db.get(KnowledgeExtractionRun, run.id)
            self.assertEqual(stored.status, 'cancelled')
            self.assertEqual(stored.usage['unknown_calls'], 1)
            self.assertEqual(await db.scalar(select(func.count(Claim.id))), 0)

    async def test_late_provider_usage_refines_unknown_without_changing_cancelled_run(self):
        run = await self.seed(kind='llm')
        provider = self.provider(block=True, ignore_cancel=True, actual_tokens=100000)
        task = self.launch(run, provider=provider)
        await asyncio.wait_for(self.entered.wait(), 5)
        async with self.sessions() as db:
            await cancel_extraction_run(db, user_id=self.user_id, run_id=run.id)
            await db.commit()
        with self.assertRaises(ExtractionLeaseLost):
            await task
        async with self.sessions() as db:
            self.assertEqual((await db.scalar(select(ExtractionCall))).state, 'unknown')
        self.release.set()
        while self.orphans:
            await asyncio.gather(*list(self.orphans), return_exceptions=True)
            await asyncio.sleep(0)
        async with self.sessions() as db:
            call = await db.scalar(select(ExtractionCall))
            self.assertEqual(call.state, 'succeeded')
            self.assertEqual(call.charged_tokens, 100000)
            self.assertEqual((await db.scalar(select(ExtractionDailyBudget))).charged_tokens, 100000)
            stored = await db.get(KnowledgeExtractionRun, run.id)
            self.assertEqual(stored.status, 'cancelled')
            self.assertEqual(stored.usage['unknown_calls'], 0)
            self.assertEqual(await db.scalar(select(func.count(Claim.id))), 0)

    async def test_checkpoint_failure_does_not_roll_back_bill_or_reset_force_retry_cap(self):
        run = await self.seed(kind='llm')
        provider = self.provider()
        with patch('app.services.knowledge_extraction_runtime._persist_grounded_claims', side_effect=RuntimeError('DB fault')):
            finished = await self.launch(run, provider=provider)
        self.assertEqual(finished.status, 'partial')
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count(Claim.id))), 0)
            self.assertEqual(await db.scalar(select(func.count(ExtractionCall.id))), 1)
            await retry_extraction_run(db, user_id=self.user_id, run_id=run.id, force=True)
            await db.commit()
        retried = await self.claim()
        with patch.object(settings, 'KNOWLEDGE_LLM_MAX_CALLS_PER_RUN', 1):
            finished = await self.launch(retried, provider=provider)
        self.assertEqual(finished.status, 'partial')
        self.assertEqual(provider.calls, 1)

    async def test_exact_concepts_do_not_gain_extra_embedding_calls_from_prefetch(self):
        run = await self.seed()
        async with self.sessions() as db:
            db.add(Concept(user_id=self.user_id, name='Synthetic concept',
                           name_normalized=normalize_concept_name('Synthetic concept'), review_status='confirmed'))
            await db.commit()

        class Extractor:
            async def extract(self, unit):
                return candidate(unit, concepts=[{'text': 'Synthetic concept'}])
        with patch.object(settings, 'KNOWLEDGE_EMBEDDING_ENABLED', True), patch(
            'app.services.knowledge_embedding_service.get_knowledge_embedding_index',
            side_effect=AssertionError('Exact matches must not trigger model I/O'),
        ) as lookup:
            finished = await self.launch(run, extractor=Extractor())
        self.assertEqual(finished.status, 'succeeded')
        lookup.assert_not_called()

    async def test_semantic_resolution_io_is_prefetched_outside_checkpoint(self):
        run = await self.seed()
        checkouts = []
        outer = self

        class Extractor:
            async def extract(self, unit):
                return candidate(unit, concepts=[{'text': 'Synthetic concept'}])

        class Index:
            async def query_concepts(self, **kwargs):
                checkouts.append(outer.engine.pool.checkedout())
                return []
        with patch.object(settings, 'KNOWLEDGE_EMBEDDING_ENABLED', True), patch(
            'app.services.knowledge_embedding_service.get_knowledge_embedding_index', return_value=Index(),
        ):
            finished = await self.launch(run, extractor=Extractor())
        self.assertEqual(finished.status, 'succeeded')
        self.assertEqual(checkouts, [0])
