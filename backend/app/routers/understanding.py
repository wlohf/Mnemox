"""Functional entry points for provisional understanding, independent of Neo4j."""
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.agent import AgentJob
from app.models.understanding import UnderstandingPreference, Experience, BehavioralHypothesis, HypothesisRevision
from app.schemas.understanding import PreferenceUpdate, HypothesisReview
from app.services.experience_service import live_experiences, public_experience, refresh_experiences
from app.services.hypothesis_service import hypothesis_dto, review_hypothesis, evaluate_all
from app.services.understanding_runtime import enqueue_understanding
from app.services.graphiti_episode_service import search_episode_memory, meaningful
from app.services.agent_budget_service import understanding_usage_summary
from app.utils.utc import utc_now_db, to_utc_iso
from app.utils.mutation_lock import lock_user_mutation

router = APIRouter()


def preferences(pref):
    return {name: bool(getattr(pref, name, False)) for name in ('analysis_enabled', 'graph_enabled', 'consume_enabled')}


def job_dto(job):
    calls = (job.checkpoint or {}).get('calls', [])
    return {'id': job.id, 'task': job.task, 'status': job.status, 'attempt_count': job.attempt_count,
            'result': job.result, 'calls': calls, 'usage': understanding_usage_summary(calls),
            'scheduled_for': to_utc_iso(job.scheduled_for), 'retry_of': (job.payload or {}).get('retry_of')}


async def visible_hypotheses(db, user_id, live):
    versions = {r.id: r.source_version for r in live}
    rows = (await db.scalars(select(BehavioralHypothesis).where(BehavioralHypothesis.user_id == user_id,
        BehavioralHypothesis.status != 'deleted').order_by(BehavioralHypothesis.updated_at.desc()).limit(100))).all()
    result = []
    for h in rows:
        refs = (h.details or {}).get('support', []) + (h.details or {}).get('counter', []) + (h.details or {}).get('context_refs', [])
        if any(versions.get(r['id']) != r['version'] for r in refs):
            result.append({'id': h.id, 'version': h.version, 'status': 'needs_review', 'review_status': h.review_status,
                'statement': '依据已变化，原判断暂不展示', 'details': {}, 'assessment': {'reason': 'source_changed'}, 'estimated': True})
        else:
            result.append(hypothesis_dto(h))
    return result


@router.get('')
async def overview(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    pref = await db.get(UnderstandingPreference, user.id)
    live, incomplete = await live_experiences(db, user.id)
    jobs = (await db.scalars(select(AgentJob).where(AgentJob.user_id == user.id,
        AgentJob.agent == 'understanding').order_by(AgentJob.created_at.desc()).limit(10))).all()
    checkpoints = (await db.scalars(select(AgentJob.checkpoint).where(AgentJob.user_id == user.id,
        AgentJob.agent == 'understanding'))).all()
    today = utc_now_db().date().isoformat()
    usage = understanding_usage_summary([c for cp in checkpoints for c in (cp or {}).get('calls', []) if c.get('date') == today])
    eligible = [r for r in live if meaningful(r)]
    return {'preferences': preferences(pref), 'capabilities': {'sql_understanding': settings.UNDERSTANDING_ENABLED,
        'graphiti_episodes': settings.GRAPHITI_EPISODES_ENABLED, 'retrieval': 'entity_linked_lexical'},
        'daily_usage': {**usage, 'date_utc': today, 'call_limit': settings.UNDERSTANDING_DAILY_MODEL_CALLS,
            'token_limit': settings.UNDERSTANDING_DAILY_TOKENS},
        'graph_projection': {'eligible': len(eligible), 'saved': sum(bool(r.extraction) for r in eligible),
            'pending': sum(not r.extraction or not r.graph_group or r.graph_pending for r in eligible)},
        'evidence_count': len(live), 'truncated_kinds': sorted(incomplete),
        'hypotheses': await visible_hypotheses(db, user.id, live), 'jobs': [job_dto(j) for j in jobs],
        'limitations': ['所有行为判断均为阶段性估计', '使用时长和记录数量不是可信度', '不自动确认事实或更新掌握度']}


@router.put('/preferences')
async def set_preferences(body: PreferenceUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if body.graph_enabled and not settings.GRAPHITI_EPISODES_ENABLED:
        raise HTTPException(409, '部署尚未启用 Graphiti 经历增强，SQL 分析仍可用')
    await lock_user_mutation(db, user.id)
    pref = await db.get(UnderstandingPreference, user.id)
    if pref is None:
        pref = UnderstandingPreference(user_id=user.id, revision=1)
        db.add(pref)
    else:
        pref.revision += 1
    for name, value in body.model_dump().items():
        setattr(pref, name, value)
    await db.flush()
    await enqueue_understanding(db, user.id, task='refresh' if body.analysis_enabled or body.graph_enabled else 'graph_cleanup')
    await db.commit()
    return preferences(pref)


class JobRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid4().hex, min_length=8, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')


class GraphJobRequest(JobRequest):
    experience_version: str | None = Field(default=None, min_length=64, max_length=64)


@router.post('/jobs/{ident}/retry', status_code=202)
async def retry_job(ident: str, body: JobRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await lock_user_mutation(db, user.id)
    old = await db.scalar(select(AgentJob).where(AgentJob.id == ident, AgentJob.user_id == user.id,
        AgentJob.agent == 'understanding'))
    if old is None:
        raise HTTPException(404, '任务不存在')
    if old.status != 'failed':
        raise HTTPException(409, '只可重试已失败的任务')
    pref = await db.get(UnderstandingPreference, user.id)
    if not pref or (old.task not in {'graph_cleanup', 'invalidate'} and
        (not settings.UNDERSTANDING_ENABLED or not (pref.analysis_enabled or pref.graph_enabled))):
        raise HTTPException(409, '请先开启对应分析功能')
    if old.task == 'analyze' and not pref.analysis_enabled:
        raise HTTPException(409, '请先启用阶段性分析')
    if old.task in {'graph_rebuild', 'graph_reextract', 'graph_drain'} and (
        not settings.GRAPHITI_EPISODES_ENABLED or not pref.graph_enabled):
        raise HTTPException(409, '请先开启 Graphiti 经历增强')
    job = await enqueue_understanding(db, user.id, task=old.task, run_key='retry:' + ident + ':' + body.request_id,
        payload={**(old.payload or {}), 'retry_of': ident})
    if not job.checkpoint.get('retry_initialized'):
        # Calls remain in the original ledger; successful stages are not billed again.
        completed = {k: v for k, v in (old.checkpoint or {}).items() if k in {'analysis_result', 'graph_result'}}
        job.checkpoint = {**job.checkpoint, **completed, 'retry_initialized': True}
    await db.commit()
    return job_dto(job)


@router.post('/analyze', status_code=202)
async def analyze(body: JobRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await lock_user_mutation(db, user.id)
    pref = await db.get(UnderstandingPreference, user.id)
    if not settings.UNDERSTANDING_ENABLED or not pref or not pref.analysis_enabled:
        raise HTTPException(409, '请先启用阶段性分析')
    job = await enqueue_understanding(db, user.id, task='analyze', run_key='analysis:' + body.request_id)
    await db.commit()
    return job_dto(job)


@router.post('/refresh')
async def refresh(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await lock_user_mutation(db, user.id)
    live, incomplete = await refresh_experiences(db, user.id)
    await evaluate_all(db, user.id, live)
    await enqueue_understanding(db, user.id)
    await db.commit()
    return {'evidence_count': len(live), 'truncated_kinds': sorted(incomplete), 'model_calls': 0}


@router.get('/evidence/{ident}')
async def evidence(ident: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    live, _ = await live_experiences(db, user.id)
    row = next((r for r in live if r.id == ident), None)
    if not row:
        raise HTTPException(404, '证据已失效或不存在')
    return {**public_experience(row), 'graph': {'eligible': meaningful(row),
        'saved': bool(row.extraction), 'extraction_revision': (row.extraction or {}).get('extraction_revision', 1 if row.extraction else 0),
        'extracted_at': (row.extraction or {}).get('extracted_at'),
        'model': (row.extraction or {}).get('extraction_model')}}


@router.delete('/evidence/{ident}')
async def exclude_evidence(ident: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await lock_user_mutation(db, user.id)
    row = await db.scalar(select(Experience).where(Experience.id == ident, Experience.user_id == user.id))
    if not row:
        raise HTTPException(404, '证据不存在')
    row.excluded, row.payload, row.extraction = True, {}, None
    row.graph_pending = bool(row.graph_group)
    # References and histories may contain verbatim source text; redact them now.
    for h in (await db.scalars(select(BehavioralHypothesis).where(BehavioralHypothesis.user_id == user.id))).all():
        refs = (h.details or {}).get('support', []) + (h.details or {}).get('counter', []) + (h.details or {}).get('context_refs', [])
        if any(r['id'] == ident for r in refs):
            h.status, h.statement, h.details, h.assessment = 'withdrawn', '依据已移除，原判断已撤回', {}, {}
            h.version += 1
            for rev in (await db.scalars(select(HypothesisRevision).where(HypothesisRevision.hypothesis_id == h.id,
                HypothesisRevision.user_id == user.id))).all():
                rev.snapshot = {'redacted': True, 'reason': 'evidence_excluded'}
    await enqueue_understanding(db, user.id, task='graph_cleanup')
    await db.commit()
    return {'excluded': True, 'canonical_record_deleted': False}


@router.post('/hypotheses/{ident}/review')
async def review(ident: str, body: HypothesisReview, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await lock_user_mutation(db, user.id)
    result = await review_hypothesis(db, user.id, ident, body)
    await db.commit()
    return result


@router.get('/hypotheses/{ident}/history')
async def history(ident: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    h = await db.scalar(select(BehavioralHypothesis).where(BehavioralHypothesis.id == ident,
        BehavioralHypothesis.user_id == user.id, BehavioralHypothesis.status != 'deleted'))
    if not h:
        raise HTTPException(404, '判断不存在')
    live, _ = await live_experiences(db, user.id)
    versions = {r.id: r.source_version for r in live}
    rows = (await db.scalars(select(HypothesisRevision).where(HypothesisRevision.hypothesis_id == ident,
        HypothesisRevision.user_id == user.id).order_by(HypothesisRevision.version))).all()
    result = []
    for rev in rows:
        snapshot = rev.snapshot
        refs = snapshot.get('details', {}).get('support', []) + snapshot.get('details', {}).get('counter', []) + snapshot.get('details', {}).get('context_refs', [])
        if any(versions.get(r['id']) != r['version'] for r in refs):
            snapshot = {'redacted': True, 'reason': 'source_changed'}
        result.append({'version': rev.version, 'reason': rev.reason, 'snapshot': snapshot})
    return result


@router.get('/memory')
async def memory(q: str = Query(default='上次卡在哪里，试过什么，现在有什么变化', max_length=500),
                 db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await search_episode_memory(db, user.id, q)


@router.post('/graph/{action}', status_code=202)
async def graph_action(action: str, body: GraphJobRequest, experience_id: str | None = None,
                       db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if action not in {'rebuild', 'reextract', 'cleanup'}:
        raise HTTPException(404)
    await lock_user_mutation(db, user.id)
    pref = await db.get(UnderstandingPreference, user.id)
    if not settings.GRAPHITI_EPISODES_ENABLED or not pref or (action != 'cleanup' and
        (not settings.UNDERSTANDING_ENABLED or not pref.graph_enabled)):
        raise HTTPException(409, 'Graphiti 经历增强未开启')
    if action == 'reextract':
        live, _ = await live_experiences(db, user.id)
        owned = next((r for r in live if r.id == experience_id and meaningful(r)), None)
        if owned is None:
            raise HTTPException(404, '经历不存在')
        if body.experience_version != owned.source_version:
            raise HTTPException(409, '依据版本已变化，请重新查看后再抽取')
    job = await enqueue_understanding(db, user.id, task='graph_' + action,
        run_key=action + ':' + body.request_id, payload={'experience_id': experience_id, 'experience_version': body.experience_version})
    await db.commit()
    return job_dto(job)
