"""DI-2 retrieval and recovery boundaries, independent of model quality."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio
from sqlalchemy import select
from app.config import settings
from app.models.agent import AgentJob
from app.models.understanding import Experience, UnderstandingPreference
from app.services.agent_budget_service import understanding_usage_summary
from app.services.experience_service import refresh_experiences
from app.services.graphiti_episode_service import process_episode_job, search_episode_memory
from app.services.episode_recall_service import graph_recall
from app.services.understanding_context_service import understanding_context
from app.services.understanding_runtime import enqueue_understanding, run_understanding_once, JobMeter
from app.utils.utc import utc_now_db
import test_dynamic_understanding as fixtures


@pytest_asyncio.fixture
async def fixture():
    value = fixtures.DynamicUnderstandingTests()
    await value.asyncSetUp()
    try:
        yield value
    finally:
        await value.asyncTearDown()


async def source(fixture):
    async with fixture.factory() as db:
        p = fixture.focus(note='Matrix diagrams initially helped; unresolved exercises remain.')
        db.add(p)
        await db.flush()
        rows, _ = await refresh_experiences(db, fixture.uid)
        row = rows[0]
        row.graph_group = 'mnemox-experience-test-source'
        row.extraction = {'group_id': row.graph_group, 'source_version': row.source_version,
            'episode': {'uuid': 'episode', 'group_id': row.graph_group, 'entity_edges': ['edge']},
            'nodes': [{'uuid': 'node', 'name': 'Matrix diagrams', 'group_id': row.graph_group}],
            'edges': [{'uuid': 'edge', 'group_id': row.graph_group, 'source_node_uuid': 'node',
                'target_node_uuid': 'node', 'episodes': ['episode']}], 'episodic_edges': []}
        (await db.get(UnderstandingPreference, fixture.uid)).graph_enabled = True
        await db.commit()
        return row.id, row.source_version, p.id


@pytest.mark.asyncio
async def test_source_changed_during_graph_read_is_not_returned_from_identity_map(fixture):
    ident, _, p_id = await source(fixture)
    graph = SimpleNamespace(close=AsyncMock())
    async def change_source(*_args):
        async with fixture.factory() as writer:
            from app.models.pomodoro import Pomodoro
            p = await writer.get(Pomodoro, p_id)
            p.note = 'Corrected and private replacement'
            await writer.commit()
        return {'mnemox-experience-test-source'}, set(), []
    with patch.object(settings, 'GRAPHITI_EPISODES_ENABLED', True), \
         patch('app.services.episode_recall_service.create_episode_graph', return_value=graph), \
         patch('app.services.episode_recall_service.graph_recall', side_effect=change_source):
        async with fixture.factory() as db:
            result = await search_episode_memory(db, fixture.uid, 'Matrix diagrams')
            assert result['experiences'] == []
            assert result['graph_hits'] == 0 and result['backend'] == 'sql'
            assert ident not in str(result)


@pytest.mark.asyncio
async def test_disabling_consumption_during_retrieval_drops_context(fixture):
    await source(fixture)
    async def disable(*_args):
        async with fixture.factory() as db:
            pref = await db.get(UnderstandingPreference, fixture.uid)
            pref.consume_enabled, pref.revision = False, pref.revision + 1
            await db.commit()
        return {'experiences': [{'note': 'should never reach prompt'}]}
    with patch('app.services.understanding_context_service.search_episode_memory', side_effect=disable):
        async with fixture.factory() as db:
            assert await understanding_context(db, fixture.uid) == {}


@pytest.mark.asyncio
async def test_entity_neighbors_must_match_saved_provenance_and_owner_groups():
    saved = {
        'first': {'nodes': [{'uuid': 'n1', 'name': 'Matrix diagrams'}], 'edges': []},
        'later': {'nodes': [{'uuid': 'n2', 'name': 'Matrix diagrams'}],
                  'edges': [{'uuid': 'e2', 'source_node_uuid': 'n2', 'target_node_uuid': 'n3'}]},
    }
    graph = SimpleNamespace(search_=AsyncMock(return_value=SimpleNamespace(edges=[],
        nodes=[SimpleNamespace(uuid='n1', group_id='first')])), driver=SimpleNamespace(execute_query=AsyncMock(return_value=([
            {'group_id': 'later', 'node_id': 'n2', 'edge_id': 'e2', 'name': 'matrix diagrams'},
            {'group_id': 'foreign', 'node_id': 'n2', 'edge_id': 'e2', 'name': 'matrix diagrams'},
            {'group_id': 'later', 'node_id': 'n2', 'edge_id': 'forged', 'name': 'matrix diagrams'},
        ], None, None))))
    seeds, linked, connections = await graph_recall(graph, 'Matrix diagrams', saved, 4)
    assert seeds == {'first'} and linked == {'later'}
    assert connections == [{'from_group': 'first', 'to_group': 'later', 'entity': 'matrix diagrams'}]
    assert set(graph.driver.execute_query.call_args.kwargs['params']['groups']) == {'first', 'later'}


@pytest.mark.asyncio
async def test_late_rebuild_uses_new_group_and_cannot_resurrect_excluded_source(fixture):
    ident, _, _ = await source(fixture)
    async with fixture.factory() as db:
        job = await enqueue_understanding(db, fixture.uid, task='graph_rebuild')
        pref = await db.get(UnderstandingPreference, fixture.uid)
        job.status, job.lease_owner = 'running', 'test-lease'
        job.lease_expires_at = utc_now_db() + timedelta(minutes=3)
        job.payload = {'preference_revision': pref.revision}
        await db.commit()
        meter = JobMeter(fixture.factory, job.id, fixture.uid, 'test-lease')
        job_id = job.id
    written = []
    graph = SimpleNamespace(close=AsyncMock(), driver=SimpleNamespace(execute_query=AsyncMock()))
    async def stale_replay(_graph, saved):
        written.append(saved['group_id'])
        assert saved['group_id'] != 'mnemox-experience-test-source'
        assert saved['edges'][0]['source_node_uuid'] == saved['nodes'][0]['uuid']
        assert saved['edges'][0]['episodes'] == [saved['episode']['uuid']]
        response = await fixture.client.delete('/api/understanding/evidence/' + ident)
        assert response.status_code == 200
    with patch.object(settings, 'GRAPHITI_EPISODES_ENABLED', True), \
         patch('app.services.graphiti_episode_service.create_episode_graph', return_value=graph), \
         patch('app.services.graphiti_episode_service.replay_extraction', side_effect=stale_replay), \
         patch('app.ai.factory.AIProviderFactory.create_provider', side_effect=AssertionError('rebuild must be model-free')):
        with pytest.raises(ValueError, match='source_changed'):
            await process_episode_job(fixture.factory, meter, 'graph_rebuild', {})
        async with fixture.factory() as db:
            row = await db.get(Experience, ident)
            assert row.excluded and row.extraction is None
            job = await db.get(AgentJob, job_id)
            assert written[0] in job.checkpoint['graph_groups']
            job.status = 'failed'
            await db.commit()
        await run_understanding_once(fixture.factory)
        deleted = [call.kwargs['params']['group_id'] for call in graph.driver.execute_query.call_args_list]
        assert written[0] in deleted


@pytest.mark.asyncio
async def test_retry_is_owned_idempotent_and_preserves_paid_stage(fixture):
    async with fixture.factory() as db:
        job = await enqueue_understanding(db, fixture.uid, task='analyze')
        job.status, job.result = 'failed', {'error': 'graph_unavailable'}
        job.checkpoint = {'calls': [{'date': utc_now_db().date().isoformat(), 'reserved_tokens': 200,
            'state': 'failed', 'usage': None}], 'analysis_result': {'accepted': ['existing'], 'abstention_reason': None}}
        await db.commit()
        ident = job.id
    url = '/api/understanding/jobs/' + ident + '/retry'
    first = await fixture.client.post(url, json={'request_id': 'same-request'})
    again = await fixture.client.post(url, json={'request_id': 'same-request'})
    assert first.status_code == 202 and first.json()['id'] == again.json()['id']
    with patch('app.ai.factory.AIProviderFactory.create_provider', side_effect=AssertionError('paid stage must not repeat')):
        await run_understanding_once(fixture.factory)
    data = (await fixture.client.get('/api/understanding')).json()
    assert data['daily_usage']['actual_tokens'] is None
    assert data['daily_usage']['configured_cost_usd'] is None
    assert data['daily_usage']['model_calls'] == 1
    from app.auth import get_current_user
    fixture.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=fixture.other)
    assert (await fixture.client.post(url, json={'request_id': 'other-request'})).status_code == 404


@pytest.mark.asyncio
async def test_reextract_requires_current_version_and_cleanup_survives_opt_out(fixture):
    ident, version, _ = await source(fixture)
    with patch.object(settings, 'GRAPHITI_EPISODES_ENABLED', True):
        url = '/api/understanding/graph/reextract?experience_id=' + ident
        assert (await fixture.client.post(url, json={'request_id': 'missing-version'})).status_code == 409
        accepted = await fixture.client.post(url, json={'request_id': 'current-version', 'experience_version': version})
        assert accepted.status_code == 202
        async with fixture.factory() as db:
            pref = await db.get(UnderstandingPreference, fixture.uid)
            pref.analysis_enabled = pref.graph_enabled = False
            await db.commit()
        assert (await fixture.client.post('/api/understanding/graph/cleanup', json={'request_id': 'cleanup-optout'})).status_code == 202


def test_usage_summary_does_not_turn_partial_reporting_into_zero_cost():
    usage = understanding_usage_summary([
        {'reserved_tokens': 100, 'usage': {'total_tokens': 20, 'configured_cost_usd': .001}},
        {'reserved_tokens': 80, 'usage': None},
    ])
    assert usage['actual_tokens'] is None and usage['reported_tokens'] == 20
    assert usage['configured_cost_usd'] is None and usage['reserved_tokens'] == 180


@pytest.mark.asyncio
async def test_busy_user_does_not_starve_another_users_pending_job(fixture):
    async with fixture.factory() as db:
        running = await enqueue_understanding(db, fixture.uid, task='analyze')
        running.status, running.lease_owner = 'running', 'live-worker'
        running.lease_expires_at = utc_now_db() + timedelta(minutes=3)
        await enqueue_understanding(db, fixture.uid)
        db.add(UnderstandingPreference(user_id=fixture.other, analysis_enabled=True))
        await db.flush()
        other = await enqueue_understanding(db, fixture.other)
        other_id = other.id
        await db.commit()
    assert await run_understanding_once(fixture.factory) == 1
    async with fixture.factory() as db:
        assert (await db.get(AgentJob, other_id)).status == 'completed'


@pytest.mark.asyncio
async def test_projection_checkpoint_resumes_without_repeating_graph_or_model(fixture):
    async with fixture.factory() as db:
        (await db.get(UnderstandingPreference, fixture.uid)).graph_enabled = True
        job = await enqueue_understanding(db, fixture.uid, task='graph_rebuild')
        job.status, job.lease_owner = 'running', 'crashed-after-save'
        job.lease_expires_at = utc_now_db() - timedelta(seconds=1)
        job.checkpoint = {'calls': [], 'graph_result': {'rebuilt': 1, 'backend': 'graphiti_episode'}}
        ident = job.id
        await db.commit()
    with patch('app.services.graphiti_episode_service.process_episode_job', side_effect=AssertionError('already saved')):
        await run_understanding_once(fixture.factory)
    async with fixture.factory() as db:
        job = await db.get(AgentJob, ident)
        assert job.status == 'completed' and job.result['graph']['rebuilt'] == 1


@pytest.mark.asyncio
async def test_configuration_failure_still_enqueues_abandoned_group_cleanup(fixture):
    ident, _, _ = await source(fixture)
    async with fixture.factory() as db:
        row = await db.get(Experience, ident)
        row.extraction = None
        job = await enqueue_understanding(db, fixture.uid, task='graph_drain')
        job.checkpoint = {'calls': [], 'graph_groups': ['mnemox-experience-abandoned-attempt']}
        job_id = job.id
        await db.commit()
    with patch.object(settings, 'GRAPHITI_EPISODES_ENABLED', True), \
         patch('app.ai.factory.AIProviderFactory.create_provider', side_effect=ValueError('no key')):
        await run_understanding_once(fixture.factory)
    async with fixture.factory() as db:
        assert (await db.get(AgentJob, job_id)).status == 'failed'
        cleanup = await db.scalar(select(AgentJob).where(AgentJob.task == 'graph_cleanup'))
        assert cleanup is not None and cleanup.status == 'pending'


@pytest.mark.asyncio
async def test_single_oversized_call_fails_without_infinite_daily_retries(fixture):
    await source(fixture)
    with patch.object(settings, 'UNDERSTANDING_DAILY_TOKENS', 1024), \
         patch.object(settings, 'GRAPHITI_EPISODES_ENABLED', False), \
         patch('app.ai.factory.AIProviderFactory.create_provider', return_value=fixtures.ProposalProvider()) as provider:
        async with fixture.factory() as db:
            job = await enqueue_understanding(db, fixture.uid, task='analyze')
            ident = job.id
            await db.commit()
        await run_understanding_once(fixture.factory)
        async with fixture.factory() as db:
            job = await db.get(AgentJob, ident)
            assert job.status == 'failed'
            assert job.result['error'] == 'understanding_call_exceeds_daily_budget'
            assert job.checkpoint['calls'] == []
        assert provider.return_value.get_last_usage() == {}


@pytest.mark.asyncio
async def test_evaluation_preflight_and_cleanup_failure_preserve_report(fixture, tmp_path):
    from scripts.evaluate_dynamic_understanding import run, cleanup_groups
    args = SimpleNamespace(user_id=fixture.uid, isolated_graph_uri='bolt://127.0.0.1:7687',
        output=tmp_path / 'preflight.json', preflight=True, max_model_calls=5, max_tokens=10000)
    graph = SimpleNamespace(close=AsyncMock(), driver=SimpleNamespace(execute_query=AsyncMock()))
    with patch.object(settings, 'DATABASE_URL', str(fixture.engine.url)), \
         patch('app.ai.factory.AIProviderFactory.create_provider', side_effect=ValueError('missing secret')), \
         patch('scripts.evaluate_dynamic_understanding.create_episode_graph', return_value=graph):
        report = await run(args)
    assert report['status'] == 'blocked_configuration'
    assert report['preflight']['graph_available'] and not report['preflight']['ai_configuration_ready']
    assert report['quality_verdict'] == 'not_run' and 'missing secret' not in args.output.read_text()
    async with fixture.factory() as db:
        job = await enqueue_understanding(db, fixture.uid)
        job.checkpoint = {'graph_groups': ['mnemox-experience-test-orphan']}
        await db.commit()
    report = {'usage': {'model_calls': 2}}
    with patch('scripts.evaluate_dynamic_understanding.create_episode_graph', side_effect=ConnectionError):
        await cleanup_groups(fixture.factory, report)
    assert report['usage']['model_calls'] == 2
    assert report['cleanup']['remaining_groups'] == ['mnemox-experience-test-orphan']
