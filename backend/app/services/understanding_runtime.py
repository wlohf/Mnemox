"""Understanding jobs on the existing AgentJob lease/recovery/budget facilities."""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import json
from uuid import uuid4
from sqlalchemy import select, or_
from app.ai.factory import AIProviderFactory
from app.config import settings
from app.models.agent import AgentJob
from app.models.understanding import UnderstandingPreference, Experience, BehavioralHypothesis
from app.services.agent_budget_service import reserve_understanding_call, settle_understanding_call
from app.services.experience_service import refresh_experiences, live_experiences, public_experience
from app.services.hypothesis_service import SYSTEM_PROMPT, evaluate_all, save_candidates, hypothesis_dto
from app.schemas.understanding import CandidateBatch
from app.utils.mutation_lock import lock_user_mutation
from app.utils.utc import utc_now_db

SCENARIO = 'dynamic_understanding_v1'


async def enqueue_understanding(db, user_id, *, task='refresh', run_key=None, payload=None):
    pref = await db.get(UnderstandingPreference, user_id)
    if not pref:
        return None
    enabled = settings.UNDERSTANDING_ENABLED and (pref.analysis_enabled or pref.graph_enabled)
    if not enabled and task not in {'graph_cleanup', 'invalidate'}:
        # Switching off inference must not stop invalidation of already retained
        # source text. Maintenance neither collects new records nor calls models.
        retained = await db.scalar(select(Experience.id).where(Experience.user_id == user_id).limit(1))
        if task != 'refresh' or retained is None:
            return None
        task = 'invalidate'
    if run_key:
        existing = await db.scalar(select(AgentJob).where(AgentJob.user_id == user_id,
            AgentJob.run_key == 'understanding:' + run_key))
        if existing:
            return existing
    # Coalesce change notifications only while pending. A running refresh has
    # already captured its snapshot; the next event must create another job.
    if task in {'refresh', 'invalidate'}:
        existing = await db.scalar(select(AgentJob).where(AgentJob.user_id == user_id,
            AgentJob.agent == 'understanding', AgentJob.task == task, AgentJob.status == 'pending'))
        if existing:
            return existing
    job = AgentJob(id=uuid4().hex, user_id=user_id, agent='understanding', task=task,
        scenario=SCENARIO, status='pending', run_key='understanding:' + run_key if run_key else None,
        payload=payload or {}, checkpoint={'calls': []}, scheduled_for=utc_now_db())
    db.add(job)
    await db.flush()
    return job


@asynccontextmanager
async def transaction(factory):
    async with factory() as db:
        try:
            yield db
            await db.commit()
        except BaseException:
            await db.rollback()
            raise


class JobMeter:
    def __init__(self, factory, job_id, user_id, lease):
        self.factory, self.job_id, self.user_id, self.lease = factory, job_id, user_id, lease
        self.serial = asyncio.Lock()

    async def owned(self, db):
        job = await db.get(AgentJob, self.job_id)
        if not job or job.status != 'running' or job.lease_owner != self.lease or job.lease_expires_at <= utc_now_db():
            raise ValueError('understanding_lease_lost')
        pref = await db.get(UnderstandingPreference, self.user_id)
        if not pref or pref.revision != (job.payload or {}).get('preference_revision'):
            raise ValueError('understanding_preference_changed')
        expected = (job.checkpoint or {}).get('fenced_sources', {})
        if expected:
            live, _ = await live_experiences(db, self.user_id)
            versions = {r.id:r.source_version for r in live}
            if any(versions.get(ident) != version for ident,version in expected.items()):
                raise ValueError('source_changed_during_run')
        return job

    async def call(self, provider, messages, system_prompt=None, category='hypothesis'):
        # Graphiti may ask concurrently; serializing protects per-provider usage
        # and the durable budget. No SQL transaction spans the external request.
        async with self.serial:
            estimate = len(json.dumps([messages, system_prompt], ensure_ascii=False).encode()) + provider.max_output_tokens
            async with transaction(self.factory) as db:
                await lock_user_mutation(db, self.user_id)
                job = await self.owned(db)
                index = await reserve_understanding_call(db, job, category=category, estimated_tokens=estimate,
                    daily_calls=settings.UNDERSTANDING_DAILY_MODEL_CALLS,
                    daily_tokens=settings.UNDERSTANDING_DAILY_TOKENS)
            success = False
            provider.clear_last_usage()
            try:
                raw = await asyncio.wait_for(provider.chat(messages=messages, system_prompt=system_prompt, temperature=0.1),
                    timeout=settings.UNDERSTANDING_MODEL_TIMEOUT)
                success = True
                return raw
            finally:
                async with transaction(self.factory) as db:
                    await lock_user_mutation(db, self.user_id)
                    job = await db.get(AgentJob, self.job_id)
                    if not job or job.status != 'running' or job.lease_owner != self.lease:
                        raise ValueError('understanding_lease_lost')
                    await settle_understanding_call(db, job, index, provider.get_last_usage(), success)


def parse_json(raw):
    text = raw.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[-1].rsplit('```', 1)[0]
    return json.loads(text)


async def load_understanding_provider(db, user_id):
    try:
        return await AIProviderFactory.create_provider(scenario='coach', db=db, user_id=user_id)
    except ValueError as exc:
        raise ValueError('understanding_ai_configuration_required') from exc


async def run_understanding_once(factory):
    """One bounded job, called by the existing recovery lifecycle worker."""
    now = utc_now_db()
    lease = uuid4().hex
    async with transaction(factory) as db:
        busy_users = select(AgentJob.user_id).where(AgentJob.agent == 'understanding',
            AgentJob.status == 'running', AgentJob.lease_expires_at >= now)
        candidate = await db.scalar(select(AgentJob).where(AgentJob.agent == 'understanding',
            AgentJob.user_id.notin_(busy_users),
            or_(AgentJob.status == 'pending', (AgentJob.status == 'running') & (AgentJob.lease_expires_at < now)),
            or_(AgentJob.scheduled_for.is_(None), AgentJob.scheduled_for <= now))
            .order_by(AgentJob.created_at, AgentJob.id).limit(1))
        if not candidate:
            return 0
        uid, job_id = candidate.user_id, candidate.id
        await lock_user_mutation(db, uid)
        await db.refresh(candidate)
        if candidate.status == 'running' and candidate.lease_expires_at >= now:
            return 0
        if candidate.status not in {'pending', 'running'}:
            return 0
        # One running understanding job per user; other users remain independent.
        active = await db.scalar(select(AgentJob.id).where(AgentJob.user_id == uid,
            AgentJob.agent == 'understanding', AgentJob.id != job_id, AgentJob.status == 'running',
            AgentJob.lease_expires_at >= now).limit(1))
        if active:
            return 0
        pref = await db.get(UnderstandingPreference, uid)
        if not pref or ((not settings.UNDERSTANDING_ENABLED or (not pref.analysis_enabled and not pref.graph_enabled)) and candidate.task not in {'graph_cleanup', 'invalidate'}):
            candidate.status, candidate.finished_at = 'cancelled', now
            return 1
        if candidate.attempt_count >= 3:
            candidate.status, candidate.finished_at = 'failed', now
            candidate.result = {'error': 'retry_limit_reached'}
            if candidate.task != 'graph_cleanup' and (candidate.checkpoint or {}).get('graph_groups'):
                await enqueue_understanding(db, uid, task='graph_cleanup', run_key='cleanup:' + candidate.id)
            return 1
        candidate.status = 'running'
        candidate.attempt_count += 1
        candidate.started_at = candidate.started_at or now
        candidate.lease_owner = lease
        candidate.lease_expires_at = now + timedelta(seconds=240)
        candidate.payload = {**(candidate.payload or {}), 'preference_revision': pref.revision}
        candidate.checkpoint = {**(candidate.checkpoint or {}), 'fenced_sources': {}}
        task, payload = candidate.task, candidate.payload
        analysis_enabled, graph_enabled = pref.analysis_enabled, pref.graph_enabled
        saved_analysis = (candidate.checkpoint or {}).get('analysis_result')
        saved_graph = (candidate.checkpoint or {}).get('graph_result')
    meter = JobMeter(factory, job_id, uid, lease)
    provider = None
    try:
        async with transaction(factory) as db:
            await lock_user_mutation(db, uid)
            await meter.owned(db)
            live, incomplete = await refresh_experiences(db, uid, collect_new=task not in {'invalidate', 'graph_cleanup'})
            await evaluate_all(db, uid, live)
            discovery = [r for r in sorted(live, key=lambda r: (r.recorded_at or r.first_seen_at, r.id), reverse=True)
                         if r.payload.get('eligible')][:60]
            # Bound characters before serialization; never silently alter source text.
            chosen, size = [], 0
            for r in discovery:
                text = json.dumps(public_experience(r), ensure_ascii=False)
                if size + len(text) > 20000:
                    continue
                chosen.append(r)
                size += len(text)
            discovery = chosen
            source_versions = {r.id: r.source_version for r in discovery}
            cutoff = utc_now_db()
            old = (await db.scalars(select(BehavioralHypothesis).where(BehavioralHypothesis.user_id == uid,
                BehavioralHypothesis.status.notin_(['deleted', 'withdrawn', 'superseded']),
                BehavioralHypothesis.review_status != 'ignored').order_by(BehavioralHypothesis.updated_at.desc()).limit(10))).all()
            old_dtos = [hypothesis_dto(h) for h in old]
            # Automatic refresh evaluates deterministically and ingests changed
            # episodes. Open candidate discovery is an explicit budgeted action.
            if task == 'analyze' and analysis_enabled and discovery and saved_analysis is None:
                job = await db.get(AgentJob, job_id)
                job.checkpoint = {**(job.checkpoint or {}), 'fenced_sources': source_versions}
                provider = await load_understanding_provider(db, uid)
        outcome = {'refreshed': len(live), 'truncated_kinds': sorted(incomplete)}
        if saved_analysis is not None:
            outcome.update(saved_analysis)
        if task == 'analyze' and analysis_enabled and saved_analysis is None:
            if discovery:
                provider.configure_extraction(2400)
                raw = await meter.call(provider, [{'role': 'user', 'content': json.dumps({
                    'schema': CandidateBatch.model_json_schema(), 'experiences': [public_experience(r) for r in discovery],
                    'previous_provisional_hypotheses': old_dtos, 'sampling': 'recent_bounded_not_representative'}, ensure_ascii=False)}], SYSTEM_PROMPT)
                batch = CandidateBatch.model_validate(parse_json(raw))
                async with transaction(factory) as db:
                    await lock_user_mutation(db, uid)
                    await meter.owned(db)
                    live, _ = await refresh_experiences(db, uid)
                    valid = {r.id: r for r in live}
                    if any(i not in valid or valid[i].source_version != v for i, v in source_versions.items()):
                        raise ValueError('source_changed_during_analysis')
                    analysis_result = await save_candidates(db, uid, batch, [valid[i] for i in source_versions],
                        cutoff=cutoff, model=provider.model)
                    outcome.update(analysis_result)
                    job = await meter.owned(db)
                    job.checkpoint = {**(job.checkpoint or {}), 'analysis_result': analysis_result, 'fenced_sources': {}}
            else:
                outcome.update(accepted=[], abstention_reason='尚无可用的原始经历，暂不判断')
        if graph_enabled or task in {'graph_rebuild', 'graph_cleanup', 'graph_reextract', 'invalidate'}:
            from app.services.graphiti_episode_service import process_episode_job
            outcome['graph'] = saved_graph if saved_graph is not None else await asyncio.wait_for(
                process_episode_job(factory, meter, task, payload), timeout=170)
        async with transaction(factory) as db:
            await lock_user_mutation(db, uid)
            job = await meter.owned(db)
            job.status, job.result, job.finished_at = 'completed', outcome, utc_now_db()
            job.lease_owner, job.lease_expires_at = None, None
    except Exception as exc:
        async with transaction(factory) as db:
            await lock_user_mutation(db, uid)
            job = await db.get(AgentJob, job_id)
            if job and job.lease_owner == lease and job.status == 'running':
                # Structural error code only: no prompts, responses, credentials.
                reason = str(exc) if isinstance(exc, ValueError) and str(exc).startswith(('understanding_', 'source_')) else type(exc).__name__
                job.result = {'error': reason[:120]}
                job.status = 'pending' if job.attempt_count < 3 else 'failed'
                job.scheduled_for = utc_now_db() + timedelta(minutes=job.attempt_count)
                job.finished_at = utc_now_db() if job.status == 'failed' else None
                job.lease_owner, job.lease_expires_at = None, None
                if reason in {'understanding_ai_configuration_required', 'understanding_call_exceeds_daily_budget'}:
                    job.status, job.finished_at = 'failed', utc_now_db()
                elif reason == 'source_changed_before_reextraction':
                    job.status, job.finished_at = 'failed', utc_now_db()
                elif reason == 'understanding_daily_budget_exhausted':
                    job.status = 'pending'
                    job.attempt_count = max(0, job.attempt_count - 1)
                    job.scheduled_for = utc_now_db().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                    job.finished_at = None
                if job.status == 'failed' and task != 'graph_cleanup' and (job.checkpoint or {}).get('graph_groups'):
                    await enqueue_understanding(db, uid, task='graph_cleanup', run_key='cleanup:' + job.id)
    finally:
        if provider:
            await provider.close_extraction()
    return 1
