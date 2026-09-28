"""Real SDK + isolated Neo4j. Scripted extraction is NOT a model quality eval."""
import json
import os
from datetime import timedelta
from unittest.mock import patch
import pytest
from sqlalchemy import select
from app.ai.base import AIProvider
from app.config import settings
from app.models.understanding import Experience, UnderstandingPreference
from app.models.agent import AgentJob
from app.services.understanding_runtime import enqueue_understanding, run_understanding_once
from app.services.graphiti_episode_service import create_episode_graph, delete_group, search_episode_memory
import test_dynamic_understanding as fixtures
NOW = fixtures.NOW


class ScriptedExtraction(AIProvider):
    def __init__(self, fact=None):
        super().__init__('test','scripted-extraction-test',max_output_tokens=1500)
        self.fact = fact or 'Alice tried Matrix diagrams to understand matrix multiplication.'
    async def chat(self, messages, system_prompt=None, temperature=0.1):
        schema = json.loads(system_prompt.split('JSON schema: ')[-1])
        title = schema['title']
        self.record_last_usage(input_tokens=100,output_tokens=50)
        names = ['Alice', 'Matrix diagrams']
        values = {
            'ExtractedEntities': {'extracted_entities':[{'name': name,'entity_type_id':0} for name in names]},
            'ExtractedEdges': {'edges':[{'source_entity_name': names[0], 'target_entity_name':names[1],
                'relation_type':'TRIED', 'fact':self.fact,
                'valid_at':'2026-09-01T12:00:00Z','invalid_at':None}]},
            'NodeResolutions': {'entity_resolutions':[{'id':i,'name':name,'duplicate_candidate_id':-1} for i,name in enumerate(names)]},
            'EdgeDuplicate': {'duplicate_facts':[],'contradicted_facts':[]},
            'EntitySummary': {'summary':'Alice tried Matrix diagrams.'},
            'SummarizedEntities': {'summaries':[{'name':name,'summary':'Alice tried Matrix diagrams.'} for name in names]},
            'BatchEdgeTimestamps': {'timestamps':[{'valid_at':'2026-09-01T12:00:00Z','invalid_at':None}]},
        }
        if title not in values:
            raise AssertionError('Unsupported scripted schema: '+title)
        return json.dumps(values[title])
    async def chat_stream(self, *args, **kwargs):
        yield ''


async def drain(factory, maximum=12):
    for _ in range(maximum):
        if not await run_understanding_once(factory):
            return
    raise AssertionError('episode continuation did not finish within the bound')


@pytest.mark.asyncio
async def test_real_episode_rebuild_search_and_delete():
    if os.getenv('MNEMOX_EPISODE_INTEGRATION') != '1':
        pytest.skip('Requires disposable Neo4j on loopback; never run against production')
    fixture = fixtures.DynamicUnderstandingTests()
    await fixture.asyncSetUp()
    groups = set()
    try:
        with patch.object(settings,'GRAPHITI_EPISODES_ENABLED',True), patch.object(settings,'NEO4J_URI','bolt://127.0.0.1:7687'), \
             patch.object(settings,'NEO4J_USER','neo4j'), patch.object(settings,'NEO4J_PASSWORD','di012-isolated-password'), \
             patch.object(settings,'UNDERSTANDING_DAILY_TOKENS',1000000), \
             patch('app.ai.factory.AIProviderFactory.create_provider',return_value=ScriptedExtraction()):
            async with fixture.factory() as db:
                pref = await db.get(UnderstandingPreference,fixture.uid)
                pref.graph_enabled = True
                db.add(fixture.focus(note='Alice tried Matrix diagrams to understand matrix multiplication.'))
                await enqueue_understanding(db,fixture.uid,task='refresh')
                await db.commit()
            await run_understanding_once(fixture.factory)
            async with fixture.factory() as db:
                job = await db.scalar(select(AgentJob).where(AgentJob.agent=='understanding'))
                groups.update((job.checkpoint or {}).get('graph_groups',[]))
                assert job.status == 'completed', job.result
                assert len(job.checkpoint['calls']) > 0
                exp = await db.scalar(select(Experience))
                assert exp.extraction['nodes'] and exp.extraction['edges']
                first = exp.extraction
                ident = exp.id
                memory = await search_episode_memory(db,fixture.uid,'Matrix diagrams')
                assert memory['backend'] == 'graphiti_episode', memory
                assert memory['graph_hits'] == 1, memory
                assert memory['experiences'][0]['id'] == ident
                other = await search_episode_memory(db,fixture.other,'Matrix diagrams')
                assert not other['experiences']
                job = await enqueue_understanding(db,fixture.uid,task='graph_rebuild')
                rebuild_id = job.id
                await db.commit()
            # Remove actual graph; rebuild must be replayed from SQL only.
            graph = create_episode_graph()
            await delete_group(graph, first['group_id'])
            await graph.close()
            with patch('app.ai.factory.AIProviderFactory.create_provider', side_effect=AssertionError('rebuild must not call provider')):
                await drain(fixture.factory)
            async with fixture.factory() as db:
                rebuilt = await db.get(AgentJob,rebuild_id)
                assert rebuilt.status == 'completed', rebuilt.result
                assert rebuilt.checkpoint['calls'] == []
                memory = await search_episode_memory(db,fixture.uid,'Matrix diagrams')
                assert memory['graph_hits'] == 1
                # New independent episode yields cross-session recall.
                db.add(fixture.focus(at=NOW+timedelta(days=2),note='The visual grid no longer helps for block products; tried worked examples.'))
                await enqueue_understanding(db,fixture.uid)
                await db.commit()
            with patch('app.ai.factory.AIProviderFactory.create_provider',return_value=ScriptedExtraction(
                'The visual grid no longer helps Alice with block products.')):
                await drain(fixture.factory)
            async with fixture.factory() as db:
                jobs = (await db.scalars(select(AgentJob))).all()
                for job in jobs:
                    groups.update((job.checkpoint or {}).get('graph_groups',[]))
                assert all(j.status=='completed' for j in jobs), [j.result for j in jobs]
                memory = await search_episode_memory(db,fixture.uid,'Matrix diagrams')
                assert len(memory['experiences']) == 2
                assert any('no longer' in r.get('note','') for r in memory['experiences'])
                assert memory['connections'], memory
                baseline = await search_episode_memory(db,fixture.uid,'Matrix diagrams',limit=1,use_graph=False)
                linked = await search_episode_memory(db,fixture.uid,'Matrix diagrams',limit=1)
                assert 'no longer' not in baseline['experiences'][0]['note']
                assert 'no longer' in linked['experiences'][0]['note'], linked
                assert linked['graph_attempted'] and linked['graph_hits'] == 1
                # Rebuild more than one source in bounded continuation jobs.
                calls_before = sum(len(j.checkpoint['calls']) for j in jobs)
                await enqueue_understanding(db,fixture.uid,task='graph_rebuild')
                await db.commit()
            with patch('app.ai.factory.AIProviderFactory.create_provider',side_effect=AssertionError('no model on rebuild')):
                await drain(fixture.factory)
            async with fixture.factory() as db:
                jobs = (await db.scalars(select(AgentJob))).all()
                assert all(j.status == 'completed' for j in jobs), [j.result for j in jobs]
                assert sum(len(j.checkpoint['calls']) for j in jobs) == calls_before
                for job in jobs:
                    groups.update((job.checkpoint or {}).get('graph_groups', []))
                memory = await search_episode_memory(db,fixture.uid,'Matrix diagrams')
                assert memory['graph_hits'] == 2
                from app.services.understanding_context_service import understanding_context
                context = await understanding_context(db, fixture.uid, 'Matrix diagrams')
                assert context['continuous_memory']['backend'] == 'graphiti_episode'
                row = await db.get(Experience, ident)
                previous_group, version = row.graph_group, row.source_version
            reextract = await fixture.client.post('/api/understanding/graph/reextract?experience_id=' + ident,
                json={'request_id': 'integration-reextract', 'experience_version': version})
            assert reextract.status_code == 202
            await drain(fixture.factory)
            async with fixture.factory() as db:
                row = await db.get(Experience, ident)
                assert row.extraction['extraction_revision'] == 2 and row.graph_group != previous_group
                for job in (await db.scalars(select(AgentJob))).all():
                    groups.update((job.checkpoint or {}).get('graph_groups', []))
                # Cleanup while opted out, followed by opt-in, restores saved
                # projections without another paid extraction.
                pref = await db.get(UnderstandingPreference, fixture.uid)
                pref.graph_enabled = False
                await enqueue_understanding(db, fixture.uid, task='graph_cleanup')
                await db.commit()
            await drain(fixture.factory)
            async with fixture.factory() as db:
                assert (await db.get(Experience, ident)).graph_group is None
                (await db.get(UnderstandingPreference, fixture.uid)).graph_enabled = True
                await enqueue_understanding(db, fixture.uid)
                await db.commit()
            with patch('app.ai.factory.AIProviderFactory.create_provider', side_effect=AssertionError('saved projection must be reused')):
                await drain(fixture.factory)
            await fixture.client.delete('/api/understanding/evidence/'+ident)
            await drain(fixture.factory)
            async with fixture.factory() as db:
                memory = await search_episode_memory(db,fixture.uid,'Matrix diagrams')
                assert all(r['id'] != ident for r in memory['experiences'])
                with patch('app.services.episode_recall_service.create_episode_graph',side_effect=ConnectionError):
                    fallback = await search_episode_memory(db,fixture.uid,'Matrix diagrams')
                    assert fallback['backend'] == 'sql'
                    assert fallback['reason'] == 'graphiti_unavailable'
            graph = create_episode_graph()
            async with fixture.factory() as db:
                for job in (await db.scalars(select(AgentJob))).all():
                    groups.update((job.checkpoint or {}).get('graph_groups', []))
            for group in groups:
                await delete_group(graph, group)
            await graph.close()
    finally:
        await fixture.asyncTearDown()


@pytest.mark.asyncio
async def test_evaluation_runner_records_both_paths_and_cleans_partial_groups(tmp_path):
    if os.getenv('MNEMOX_EPISODE_INTEGRATION') != '1':
        pytest.skip('Requires disposable Neo4j on loopback')
    from types import SimpleNamespace
    from scripts.evaluate_dynamic_understanding import run
    class EvaluationProvider(ScriptedExtraction):
        async def chat(self, messages, system_prompt=None, temperature=0.1):
            if 'JSON schema: ' not in (system_prompt or ''):
                self.record_last_usage(input_tokens=100, output_tokens=10)
                return json.dumps({'candidates': [], 'abstention_reason': 'Synthetic pipeline test abstains'})
            return await super().chat(messages, system_prompt, temperature)
    args = SimpleNamespace(user_id=1, isolated_graph_uri='bolt://127.0.0.1:7687',
        output=tmp_path / 'scripted-runner.json', preflight=False, max_model_calls=40, max_tokens=1000000)
    with patch.object(settings, 'NEO4J_USER', 'neo4j'), patch.object(settings, 'NEO4J_PASSWORD', 'di012-isolated-password'), \
         patch.object(settings, 'UNDERSTANDING_DAILY_TOKENS', 1000000), \
         patch('app.ai.factory.AIProviderFactory.create_provider', side_effect=lambda **kw: EvaluationProvider()):
        result = await run(args)
    assert result['engineering_completed'], result.get('jobs', result)
    assert result['quality_verdict'] == 'requires_human_review'
    assert len(result['comparisons']) == 3
    assert result['usage']['model_calls'] > 0 and result['usage']['actual_tokens'] > 0
    assert result['usage']['configured_cost_usd'] is None
    assert result['cleanup']['remaining_groups'] == []
    assert all(not row['sql_baseline']['result']['graph_attempted'] for row in result['comparisons'])
    assert all(row['human_review']['graph_benefit_over_sql'] is None for row in result['comparisons'])
    assert json.loads(args.output.read_text())['usage'] == result['usage']
