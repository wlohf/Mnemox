"""DI-0/1 behavioral contract, temporal replay, deletion, runtime and API tests."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import app.models
from app.database import Base, get_db
from app.auth import get_current_user
from app.models.user import User
from app.models.coach import CoachPreference, CoachActionAttempt, CoachNudge
from app.models.daily_plan import DailyPlan, DailyPlanRevision
from app.models.goal import Goal, Task
from app.models.pomodoro import Pomodoro
from app.models.agent import AgentJob
from app.models.understanding import UnderstandingPreference, Experience, BehavioralHypothesis, HypothesisRevision
from app.routers.understanding import router
from app.routers.plans import router as plans_router
from app.schemas.understanding import Candidate, CandidateBatch, HypothesisReview
from app.services.experience_service import refresh_experiences, live_experiences, reflection_text, public_experience
from app.services.hypothesis_service import save_candidates, assess, evaluate_all, review_hypothesis
from app.services.understanding_runtime import enqueue_understanding, run_understanding_once, JobMeter
from app.services.understanding_context_service import understanding_context
from app.services.agent_budget_service import reserve_understanding_call
from app.ai.base import AIProvider
from app.config import settings

NOW = datetime(2026, 9, 1, 12)


class ProposalProvider(AIProvider):
    def __init__(self):
        super().__init__('test', 'scripted-test', max_output_tokens=1000)
    async def chat(self, messages, system_prompt=None, temperature=0.1):
        data = json.loads(messages[0]['content'])
        row = data['experiences'][0]
        self.record_last_usage(input_tokens=100, output_tokens=40)
        return json.dumps({'candidates': [{'statement': '在这个任务情境下可能比较容易完成', 'context': '仅限记录中的任务情境',
            'support': [{'id': row['id'], 'version': row['version'], 'quote': row.get('outcome', row.get('text', ''))}],
            'unknowns': ['其他情境未知'], 'next_signal': '后续相同情境是否继续完成'}]})
    async def chat_stream(self, *args, **kwargs):
        yield ''


class DynamicUnderstandingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f'sqlite+aiosqlite:///{Path(self.temp.name)/"test.db"}')
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.factory() as db:
            users = [User(username=n, email=n+'@test.invalid', hashed_password='x') for n in ['owner','other']]
            db.add_all(users)
            await db.flush()
            self.uid, self.other = [u.id for u in users]
            db.add_all([CoachPreference(user_id=self.uid, time_zone='Asia/Shanghai'),
                UnderstandingPreference(user_id=self.uid, analysis_enabled=True, graph_enabled=False, consume_enabled=True)])
            await db.commit()
        self.app = FastAPI()
        self.app.include_router(router, prefix='/api/understanding')
        self.app.include_router(plans_router, prefix='/api/plans')
        async def db_override():
            async with self.factory() as db:
                yield db
        self.app.dependency_overrides[get_db] = db_override
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=self.uid)
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()
        self.temp.cleanup()

    def focus(self, at=NOW, **kw):
        data = dict(user_id=self.uid, time_basis='utc', record_origin='recorded', started_at=at-timedelta(minutes=25),
            ended_at=at, created_at=at-timedelta(minutes=25), duration=25, planned_duration=25, actual_duration=25,
            completed=True, note='先画图后理解了矩阵乘法')
        data.update(kw)
        return Pomodoro(**data)

    async def seed_hypothesis(self, db):
        p = self.focus()
        db.add(p)
        await db.flush()
        live, _ = await refresh_experiences(db, self.uid, now=NOW)
        row = live[0]
        candidate = Candidate(statement='先画图后可能更容易完成这类任务', context='仅限已记录的任务情境',
            support=[{'id': row.id, 'version': row.source_version, 'quote': 'completed'}],
            unknowns=['其他任务和未记录情况未知'], next_signal='未来是否仍能完成',
            prospective_test={'scope': [], 'outcome': {'field':'outcome','op':'eq','value':'completed'},'description':'未来完成记录'})
        result = await save_candidates(db, self.uid, CandidateBatch(candidates=[candidate]), live, cutoff=NOW, model='test')
        h = await db.get(BehavioralHypothesis, result['accepted'][0])
        return p, row, h, candidate

    async def test_cold_start_abstains_and_stays_sql_only(self):
        async with self.factory() as db:
            await enqueue_understanding(db, self.uid, task='analyze', run_key='cold')
            await db.commit()
        self.assertEqual(await run_understanding_once(self.factory), 1)
        response = (await self.client.get('/api/understanding')).json()
        self.assertEqual(response['hypotheses'], [])
        self.assertEqual(response['jobs'][0]['status'], 'completed')
        self.assertEqual(response['jobs'][0]['calls'], [])
        self.assertIn('暂不判断', response['jobs'][0]['result']['abstention_reason'])

    async def test_raw_and_derived_sources_group_and_exclude_demo(self):
        async with self.factory() as db:
            db.add_all([self.focus(), self.focus(record_origin='demo'),
                DailyPlan(user_id=self.uid,date='2026-09-01',content='## 复盘\n画图后理解了矩阵乘法。\n## 明镜追问\nAI 说我天才')])
            await db.flush()
            live, _ = await refresh_experiences(db, self.uid, now=NOW)
            self.assertEqual(len(live), 3)
            self.assertEqual(len([r for r in live if r.payload['eligible']]), 2)
            reflection = next(r for r in live if r.kind == 'reflection')
            self.assertNotIn('天才', json.dumps(reflection.payload, ensure_ascii=False))
            self.assertIsNone(reflection.occurred_at)
            self.assertEqual(len({r.payload['independence_day'] for r in live}), 1)

    async def test_reflection_template_is_not_user_evidence(self):
        self.assertEqual(reflection_text('## 晚间费曼复盘（不用切换模式）\n请用自己的话写 3-5 句话：\n1. 今天我真正理解了什么？\n2. 如果讲给一个完全没学过的人，我会怎么解释？\n3. 哪个地方还讲不顺？\n> 写完后点击'), '')

    async def test_discovery_and_same_day_duplicates_do_not_validate(self):
        async with self.factory() as db:
            _, _, h, _ = await self.seed_hypothesis(db)
            db.add_all([self.focus(at=NOW+timedelta(minutes=i+1)) for i in range(50)])
            await db.flush()
            live, _ = await refresh_experiences(db, self.uid, now=NOW+timedelta(hours=2))
            status, result = assess(h, live, NOW+timedelta(hours=2))
            self.assertEqual(status, 'candidate')
            self.assertEqual(result['independent_groups'], 0)
            self.assertIsNone(result['confidence'])

    async def test_future_counterexample_changes_revision_without_changing_mastery(self):
        async with self.factory() as db:
            _, _, h, _ = await self.seed_hypothesis(db)
            db.add_all([self.focus(at=NOW+timedelta(days=1)), self.focus(at=NOW+timedelta(days=2), completed=False, stop_reason='distracted')])
            await db.flush()
            live, _ = await refresh_experiences(db, self.uid, now=NOW+timedelta(days=3))
            await evaluate_all(db, self.uid, live, NOW+timedelta(days=3))
            self.assertEqual(h.status, 'contested')
            self.assertEqual(h.assessment['support_groups'], 1)
            self.assertEqual(h.assessment['counter_groups'], 1)
            self.assertFalse(h.assessment['verified'])
            self.assertEqual(h.version, 2)
            await evaluate_all(db, self.uid, live, NOW+timedelta(days=3))
            self.assertEqual(h.version, 2)

    async def test_late_backfill_never_becomes_future_validation(self):
        async with self.factory() as db:
            _, _, h, _ = await self.seed_hypothesis(db)
            db.add(self.focus(at=NOW-timedelta(days=1)))
            await db.flush()
            live, _ = await refresh_experiences(db, self.uid, now=NOW+timedelta(days=2))
            self.assertEqual(assess(h, live, NOW+timedelta(days=2))[1]['independent_groups'], 0)

    async def test_missing_measurement_is_unknown_not_negative(self):
        async with self.factory() as db:
            _, _, h, _ = await self.seed_hypothesis(db)
            h.details = {**h.details, 'prospective_test': {'scope':[], 'outcome':{'field':'actual_minutes','op':'ge','value':20},'description':'时长'}}
            db.add(self.focus(at=NOW+timedelta(days=1),actual_duration=None))
            await db.flush()
            live, _ = await refresh_experiences(db, self.uid, now=NOW+timedelta(days=2))
            result = assess(h, live, NOW+timedelta(days=2))[1]
            self.assertEqual(result['unknown_groups'], 1)
            self.assertEqual(result['counter_groups'], 0)

    async def test_foreign_or_invented_quote_is_rejected(self):
        async with self.factory() as db:
            _, row, _, candidate = await self.seed_hypothesis(db)
            for changes in [{'id':'foreign'}, {'version':'old'}, {'quote':'invented'}]:
                bad = candidate.model_copy(deep=True)
                bad.statement += str(changes)
                bad.support[0] = bad.support[0].model_copy(update=changes)
                result = await save_candidates(db, self.uid, CandidateBatch(candidates=[bad]), [row], cutoff=NOW, model='test')
                self.assertFalse(result['accepted'])
                self.assertTrue(result['rejected'])

    async def test_source_correction_hides_before_refresh_and_redacts_history(self):
        async with self.factory() as db:
            p, row, h, _ = await self.seed_hypothesis(db)
            p.note = '之前的内容有误'
            await db.commit()
            ident, hid = row.id, h.id
        res = await self.client.get('/api/understanding/evidence/'+ident)
        self.assertEqual(res.status_code, 404)
        data = (await self.client.get('/api/understanding')).json()
        self.assertEqual(data['hypotheses'][0]['details'], {})
        await self.client.post('/api/understanding/refresh')
        history = (await self.client.get(f'/api/understanding/hypotheses/{hid}/history')).json()
        self.assertTrue(history[0]['snapshot']['redacted'])

    async def test_review_is_versioned_and_deleted_fingerprint_cannot_resurrect(self):
        async with self.factory() as db:
            _, row, h, candidate = await self.seed_hypothesis(db)
            await review_hypothesis(db, self.uid, h.id, HypothesisReview(version=1, action='correct', correction='只适用于线性代数'))
            self.assertEqual(h.status, 'needs_review')
            self.assertEqual(h.review_status, 'corrected')
            with self.assertRaises(Exception):
                await review_hypothesis(db, self.uid, h.id, HypothesisReview(version=1, action='ignore'))
            await review_hypothesis(db, self.uid, h.id, HypothesisReview(version=2, action='delete'))
            self.assertEqual(h.details, {})
            result = await save_candidates(db, self.uid, CandidateBatch(candidates=[candidate]), [row], cutoff=NOW, model='test')
            self.assertFalse(result['accepted'])

    async def test_two_users_and_excluded_evidence(self):
        async with self.factory() as db:
            _, row, h, _ = await self.seed_hypothesis(db)
            await db.commit()
            ident, hid = row.id, h.id
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=self.other)
        for path in [f'/api/understanding/evidence/{ident}', f'/api/understanding/hypotheses/{hid}/history']:
            self.assertEqual((await self.client.get(path)).status_code, 404)
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=self.uid)
        self.assertEqual((await self.client.delete('/api/understanding/evidence/'+ident)).status_code, 200)
        await self.client.post('/api/understanding/refresh')
        self.assertEqual((await self.client.get('/api/understanding/evidence/'+ident)).status_code, 404)

    async def test_provider_run_is_durable_metered_and_idempotent(self):
        async with self.factory() as db:
            db.add(self.focus())
            job = await enqueue_understanding(db, self.uid, task='analyze', run_key='same')
            other = await enqueue_understanding(db, self.uid, task='analyze', run_key='same')
            self.assertEqual(job.id, other.id)
            await db.commit()
            ident = job.id
        with patch('app.ai.factory.AIProviderFactory.create_provider', return_value=ProposalProvider()):
            await run_understanding_once(self.factory)
        async with self.factory() as db:
            job = await db.get(AgentJob, ident)
            self.assertEqual(job.status, 'completed', job.result)
            self.assertEqual(len(job.checkpoint['calls']), 1)
            self.assertEqual(job.checkpoint['calls'][0]['usage']['total_tokens'], 140)
            self.assertEqual(len(job.result['accepted']), 1)
        self.assertEqual(await run_understanding_once(self.factory), 0)

    async def test_reservation_survives_failure_and_caps_future_calls(self):
        async with self.factory() as db:
            job = await enqueue_understanding(db, self.uid, task='analyze', run_key='budget')
            await reserve_understanding_call(db, job, category='hypothesis', estimated_tokens=100, daily_calls=1, daily_tokens=1000)
            await db.commit()
        async with self.factory() as db:
            job = await db.get(AgentJob, job.id)
            with self.assertRaisesRegex(ValueError, 'budget_exhausted'):
                await reserve_understanding_call(db, job, category='graphiti_extraction', estimated_tokens=100, daily_calls=1, daily_tokens=1000)

    async def test_expired_lease_restarts_and_old_writer_is_fenced(self):
        async with self.factory() as db:
            job = await enqueue_understanding(db, self.uid, task='analyze', run_key='restart')
            job.status, job.lease_owner = 'running', 'old'
            job.lease_expires_at = datetime(2020,1,1)
            await db.commit()
            ident = job.id
        await run_understanding_once(self.factory)
        meter = JobMeter(self.factory, ident, self.uid, 'old')
        async with self.factory() as db:
            with self.assertRaisesRegex(ValueError, 'lease_lost'):
                await meter.owned(db)

    async def test_chat_consumption_is_separate_and_sql_fallback_explicit(self):
        async with self.factory() as db:
            await self.seed_hypothesis(db)
            context = await understanding_context(db, self.uid)
            self.assertEqual(context['continuous_memory']['backend'], 'sql')
            pref = await db.get(UnderstandingPreference, self.uid)
            pref.consume_enabled = False
            await db.flush()
            self.assertEqual(await understanding_context(db, self.uid), {})

    async def test_plan_generation_preserves_content_and_linked_tasks_use_ids(self):
        async with self.factory() as db:
            goal = Goal(user_id=self.uid, title='数学')
            db.add(goal)
            await db.flush()
            task = Task(goal_id=goal.id, title='矩阵', planned_date=NOW.date(), status='pending')
            db.add(task)
            db.add(DailyPlan(user_id=self.uid,date='2026-09-01',content='我的原始复盘'))
            await db.commit()
            tid = task.id
        draft = (await self.client.post('/api/plans/generate/2026-09-01')).json()
        self.assertFalse(draft['saved'])
        self.assertIn(f'<!-- task:{tid}:v1 -->', draft['content'])
        self.assertEqual((await self.client.get('/api/plans/2026-09-01')).json()['content'], '我的原始复盘')
        body = {'content': draft['content'].replace('- [ ] 📝', '- [x] 📝'), 'expected_version': 1}
        saved = await self.client.put('/api/plans/2026-09-01',json=body)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['version'], 2)
        self.assertEqual((await self.client.put('/api/plans/2026-09-01',json=body)).status_code, 409)
        async with self.factory() as db:
            t = await db.get(Task, tid)
            self.assertEqual(t.status, 'completed')
            self.assertIsNotNone(t.completed_at)
            self.assertEqual(await db.scalar(select(func.count()).select_from(DailyPlanRevision)), 2)

    async def test_canonical_change_during_provider_call_fences_result_and_keeps_usage(self):
        import asyncio
        started, release = asyncio.Event(), asyncio.Event()
        class DelayedProvider(ProposalProvider):
            async def chat(self, *args, **kwargs):
                started.set()
                await release.wait()
                return await super().chat(*args, **kwargs)
        async with self.factory() as db:
            p = self.focus()
            db.add(p)
            await db.flush()
            pid = p.id
            await enqueue_understanding(db,self.uid,task='analyze')
            await db.commit()
        with patch('app.ai.factory.AIProviderFactory.create_provider',return_value=DelayedProvider()):
            running = asyncio.create_task(run_understanding_once(self.factory))
            await asyncio.wait_for(started.wait(),timeout=5)
            async with self.factory() as db:
                p = await db.get(Pomodoro,pid)
                await db.delete(p)
                await db.commit()
            release.set()
            await running
        async with self.factory() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(BehavioralHypothesis)),0)
            job = await db.scalar(select(AgentJob))
            self.assertEqual(job.status,'pending')
            self.assertEqual(job.checkpoint['calls'][0]['usage']['total_tokens'],140)

    async def test_graph_retry_does_not_repeat_completed_candidate_inference(self):
        async with self.factory() as db:
            db.add(self.focus())
            pref = await db.get(UnderstandingPreference,self.uid)
            pref.graph_enabled = True
            job = await enqueue_understanding(db,self.uid,task='analyze')
            await db.commit()
            ident = job.id
        with patch('app.ai.factory.AIProviderFactory.create_provider',return_value=ProposalProvider()) as factory, \
             patch('app.services.graphiti_episode_service.process_episode_job',side_effect=ConnectionError):
            await run_understanding_once(self.factory)
            self.assertEqual(factory.call_count,1)
        async with self.factory() as db:
            job = await db.get(AgentJob,ident)
            self.assertEqual(job.status,'pending')
            job.scheduled_for = NOW
            await db.commit()
        with patch('app.ai.factory.AIProviderFactory.create_provider',side_effect=AssertionError('no repeated inference')), \
             patch('app.services.graphiti_episode_service.process_episode_job',return_value={'processed':0}):
            await run_understanding_once(self.factory)
        async with self.factory() as db:
            job = await db.get(AgentJob,ident)
            self.assertEqual(job.status,'completed',job.result)
            self.assertEqual(len(job.checkpoint['calls']),1)

    async def test_legacy_stats_share_missingness_and_synthetic_exclusion(self):
        from app.routers.analytics import get_time_slot_efficiency, get_eda_report
        from app.routers.pomodoro import get_total_statistics
        async with self.factory() as db:
            db.add_all([self.focus(actual_duration=None),self.focus(record_origin='demo'),self.focus()])
            await db.flush()
            actor = SimpleNamespace(id=self.uid)
            stats = await get_total_statistics(db=db,current_user=actor)
            self.assertEqual(stats.total_count,2)
            self.assertEqual(stats.total_minutes,25)
            self.assertEqual(stats.unknown_duration_count,1)
            efficiency = await get_time_slot_efficiency(days=365,db=db,current_user=actor)
            self.assertIsNone(efficiency.best_slot)
            self.assertTrue(all(row.efficiency_score is None for row in efficiency.slots))
            report = await get_eda_report(days=365,db=db,current_user=actor)
            self.assertEqual(report.summary['total_minutes'],25)
            self.assertIsNone(report.profile.confidence)
            self.assertTrue(any(row['study_minutes'] is None for row in report.daily_points))

    async def test_user_correction_is_reported_without_repeating_the_old_hypothesis(self):
        async with self.factory() as db:
            _, _, h, _ = await self.seed_hypothesis(db)
            await review_hypothesis(db,self.uid,h.id,HypothesisReview(version=h.version,action='correct',correction='只有这次画图有帮助'))
            context = await understanding_context(db,self.uid)
            self.assertFalse(context['hypotheses'])
            self.assertEqual(context['user_corrections'][0]['text'],'只有这次画图有帮助')
            self.assertFalse(context['user_corrections'][0]['confirmed_fact'])

    async def test_demo_task_and_template_do_not_become_user_traits(self):
        from app.models.memory import UserMemory
        async with self.factory() as db:
            db.add(UserMemory(user_id=self.uid,memory_key='demo_mnemox_seeded',memory_value='1'))
            goal = Goal(user_id=self.uid,title='7 天建立主动学习闭环',description='用 Demo 资料体验：资料理解 → 任务执行 → 番茄钟 → 费曼复盘 → 间隔复习。')
            db.add(goal)
            await db.flush()
            db.add(Task(goal_id=goal.id,title='Demo 任务',status='completed',completed_at=NOW))
            db.add(DailyPlan(user_id=self.uid,date='2026-09-01',content='## 晚间费曼复盘\n请用自己的话写 3-5 句话回答：\n1. 我今天真正理解了什么？\n2. 如果要讲给一个完全没学过的人，我会怎么解释？\n3. 哪一步还讲不顺？明天要补哪一个最小缺口？'))
            await db.flush()
            live, _ = await refresh_experiences(db,self.uid,now=NOW)
            self.assertEqual(len(live),1)
            self.assertFalse(live[0].payload['eligible'])
            self.assertIn('synthetic_record',live[0].payload['quality_flags'])

    async def test_disabling_analysis_does_not_stop_source_invalidation(self):
        async with self.factory() as db:
            p, _, h, _ = await self.seed_hypothesis(db)
            pref = await db.get(UnderstandingPreference,self.uid)
            pref.analysis_enabled = False
            p.note = '需要删除旧判断的依据'
            db.add(self.focus(at=NOW+timedelta(days=1)))
            job = await enqueue_understanding(db,self.uid)
            self.assertEqual(job.task,'invalidate')
            await db.commit()
            ident = h.id
        with patch('app.ai.factory.AIProviderFactory.create_provider',side_effect=AssertionError('maintenance must not call model')):
            await run_understanding_once(self.factory)
        async with self.factory() as db:
            h = await db.get(BehavioralHypothesis,ident)
            self.assertEqual(h.status,'withdrawn')
            self.assertEqual(await db.scalar(select(func.count()).select_from(Experience)),1)
