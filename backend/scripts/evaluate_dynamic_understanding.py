"""Real-provider DI-2 evaluation on synthetic input and disposable stores.

Uses the selected owner's Coach configuration, never their business records.
Model quality requires human review; SQL and graph use exactly the same inputs.
"""
import argparse
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
from unittest.mock import patch
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app.models  # noqa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.ai.factory import AIProviderFactory
from app.config import settings
from app.database import Base
from app.models.user import User
from app.models.coach import CoachPreference
from app.models.daily_plan import DailyPlan
from app.models.agent import AgentJob
from app.models.understanding import UnderstandingPreference, Experience, BehavioralHypothesis
from app.services.agent_budget_service import understanding_usage_summary
from app.services.understanding_runtime import enqueue_understanding, run_understanding_once
from app.services.graphiti_episode_service import create_episode_graph, delete_group, search_episode_memory
from app.utils.utc import utc_now_db

CASES = [
    ('卡点与尝试', '学习矩阵乘法时卡在维度对应，今天试了先画方格再计算，完成了两个例题；还没有独立做题。'),
    ('变化与反例', '今天继续学矩阵乘法，画方格没有帮助理解分块矩阵。我改为逐步代入具体数字，仍有一个题没有弄懂。'),
    ('已解决的范围', '我能独立解出普通矩阵乘法的三个例题了；分块矩阵的维度对应仍不清楚，不能说整个主题已掌握。'),
]
QUERIES = [
    ('上次矩阵乘法卡在哪里，试过什么？', [0, 1], '保留维度卡点、画方格和代入数字的尝试'),
    ('画方格这个方法现在还有帮助吗？', [0, 1], '保留后来失效的情境，不能只引用早期成功'),
    ('矩阵乘法已经完全掌握了吗？', [2], '普通例题能独立完成，分块矩阵仍未解决；不能泛化为全部掌握'),
]


def write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


async def collect_report(factory, uid, output):
    async with factory() as db:
        jobs = (await db.scalars(select(AgentJob))).all()
        calls = [c for job in jobs for c in (job.checkpoint or {}).get('calls', [])]
        rows = (await db.scalars(select(Experience).order_by(Experience.source_key))).all()
        by_case = {i: next((r.id for r in rows if text in r.payload.get('text', '')), None) for i, (_, text) in enumerate(CASES)}
        output.update(jobs=[{'status': j.status, 'task': j.task, 'result': j.result} for j in jobs], calls=calls,
            usage=understanding_usage_summary(calls),
            extraction=[{'id': r.id, 'source': r.source_key, 'input_version': r.source_version,
                'input': r.payload, 'extraction_revision': (r.extraction or {}).get('extraction_revision'),
                'entities': [n['name'] for n in (r.extraction or {}).get('nodes', [])],
                'relations': [e['fact'] for e in (r.extraction or {}).get('edges', [])]} for r in rows],
            hypotheses=[{'statement': h.statement, 'details': h.details, 'assessment': h.assessment}
                for h in (await db.scalars(select(BehavioralHypothesis))).all()], comparisons=[])
        for query, expected, boundary in QUERIES:
            results = {}
            for name, graph_enabled in [('sql_baseline', False), ('graph_enhanced', True)]:
                start = perf_counter()
                recall = await search_episode_memory(db, uid, query, use_graph=graph_enabled, limit=3)
                retrieved = {r['id'] for r in recall['experiences']}
                results[name] = {'elapsed_ms': round((perf_counter() - start) * 1000, 2), 'result': recall,
                    'expected_source_coverage': sum(by_case[i] in retrieved for i in expected) / len(expected)}
            output['comparisons'].append({'question': query, 'expected_boundary': boundary,
                'expected_source_ids': [by_case[i] for i in expected], **results,
                'human_review': {'supported': None, 'counterexamples_preserved': None,
                    'unjustified_generalization': None, 'graph_benefit_over_sql': None}})
        output['engineering_completed'] = bool(jobs) and all(j.status == 'completed' for j in jobs) and all(r.extraction for r in rows)
        output['limitations'] = ['Synthetic input, real model; not evidence of long-term user benefit.',
            'Source coverage is not answer correctness; every quality comparison needs human review.',
            'Unknown token usage or unconfigured prices remain null, not zero.']


async def cleanup_groups(factory, output):
    # Even a partial/failed extraction has its new graph group in the durable ledger.
    async with factory() as db:
        jobs = (await db.scalars(select(AgentJob))).all()
        groups = {g for job in jobs for g in (job.checkpoint or {}).get('graph_groups', [])}
    output['cleanup'] = {'attempted_groups': len(groups), 'remaining_groups': []}
    if not groups:
        return
    graph = None
    try:
        graph = create_episode_graph()
        for group in groups:
            try:
                await asyncio.wait_for(delete_group(graph, group), timeout=5)
            except Exception:
                output['cleanup']['remaining_groups'].append(group)
    except Exception:
        output['cleanup']['remaining_groups'] = sorted(groups)
    finally:
        if graph:
            try:
                await graph.close()
            except Exception:
                output['cleanup']['close_failed'] = True


async def run(args):
    uri = urlparse(args.isolated_graph_uri)
    if uri.scheme not in {'bolt', 'neo4j'} or uri.hostname not in {'localhost', '127.0.0.1'}:
        raise ValueError('An explicitly isolated loopback Neo4j is required')
    source_engine = create_async_engine(settings.DATABASE_URL)
    source_sessions = async_sessionmaker(source_engine, expire_on_commit=False)
    original_factory = AIProviderFactory.create_provider
    async def provider_factory(**_ignored):
        async with source_sessions() as db:
            return await original_factory(scenario='coach', db=db, user_id=args.user_id)
    output = {'schema_version': 2, 'input_kind': 'synthetic_real_model_eval', 'cases': CASES,
        'quality_verdict': 'not_run', 'engineering_completed': False, 'preflight': {}}
    try:
        try:
            provider = await provider_factory()
            output['model'] = provider.model
            await provider.close_extraction()
            output['preflight']['ai_configuration_ready'] = True
        except Exception:
            output['preflight'].update(ai_configuration_ready=False, ai_error='owned_coach_ai_configuration_required')
        with patch.object(settings, 'NEO4J_URI', args.isolated_graph_uri):
            graph = None
            try:
                graph = create_episode_graph()
                await asyncio.wait_for(graph.driver.execute_query('RETURN 1 AS ready'), timeout=5)
                output['preflight']['graph_available'] = True
            except Exception:
                output['preflight']['graph_available'] = False
            finally:
                if graph:
                    try:
                        await graph.close()
                    except Exception:
                        pass
        ready = output['preflight'].get('ai_configuration_ready') and output['preflight'].get('graph_available')
        if args.preflight or not ready:
            output['status'] = 'preflight_ready' if ready else 'blocked_configuration'
            return output
        with tempfile.TemporaryDirectory(prefix='mnemox-real-di-eval-') as directory:
            engine = create_async_engine('sqlite+aiosqlite:///' + str(Path(directory) / 'eval.db'))
            factory = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                with patch.object(settings, 'UNDERSTANDING_ENABLED', True), \
                     patch.object(settings, 'GRAPHITI_EPISODES_ENABLED', True), \
                     patch.object(settings, 'NEO4J_URI', args.isolated_graph_uri), \
                     patch.object(settings, 'UNDERSTANDING_DAILY_MODEL_CALLS', min(args.max_model_calls, settings.UNDERSTANDING_DAILY_MODEL_CALLS)), \
                     patch.object(settings, 'UNDERSTANDING_DAILY_TOKENS', min(args.max_tokens, settings.UNDERSTANDING_DAILY_TOKENS)), \
                     patch('app.ai.factory.AIProviderFactory.create_provider', side_effect=provider_factory):
                    try:
                        async with factory() as db:
                            user = User(username='synthetic-eval', email='eval@example.invalid', hashed_password='not-a-login')
                            db.add(user)
                            await db.flush()
                            uid = user.id
                            db.add_all([CoachPreference(user_id=uid, time_zone='Asia/Shanghai'),
                                UnderstandingPreference(user_id=uid, analysis_enabled=True, graph_enabled=True, consume_enabled=True)])
                            for offset, (_, text) in enumerate(CASES):
                                day = (utc_now_db() - timedelta(days=7-offset)).date().isoformat()
                                db.add(DailyPlan(user_id=uid, date=day, content='## 复盘\n' + text))
                            await enqueue_understanding(db, uid, task='analyze')
                            await db.commit()
                        for _ in range(12):
                            if not await run_understanding_once(factory):
                                break
                        await collect_report(factory, uid, output)
                        output.update(status='evaluation_recorded', quality_verdict='requires_human_review')
                    except Exception as exc:
                        output.update(status='evaluation_failed', error_type=type(exc).__name__)
                    finally:
                        # A cleanup outage is recorded without losing the paid-call report.
                        if 'usage' not in output:
                            try:
                                async with factory() as db:
                                    jobs = (await db.scalars(select(AgentJob))).all()
                                    output['calls'] = [c for job in jobs for c in (job.checkpoint or {}).get('calls', [])]
                                    output['usage'] = understanding_usage_summary(output['calls'])
                            except Exception as exc:
                                output['usage_error_type'] = type(exc).__name__
                        try:
                            await cleanup_groups(factory, output)
                        except Exception as exc:
                            output['cleanup'] = {'error_type': type(exc).__name__}
            finally:
                await engine.dispose()
        return output
    finally:
        await source_engine.dispose()
        write_report(args.output, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', type=int, required=True, help='Owner of the configured Coach AI credential')
    parser.add_argument('--isolated-graph-uri', required=True, help='Disposable loopback Neo4j, never production')
    parser.add_argument('--output', default='../docs/evaluation/di2-real-model-result.json')
    parser.add_argument('--preflight', action='store_true', help='Check owned AI configuration and graph; zero model calls')
    parser.add_argument('--max-model-calls', type=int, default=24)
    parser.add_argument('--max-tokens', type=int, default=120000)
    args = parser.parse_args()
    if args.max_model_calls < 1 or args.max_tokens < 1024:
        parser.error('model call limit must be positive and token limit at least 1024')
    result = asyncio.run(run(args))
    print(json.dumps({'artifact': args.output, 'status': result['status'], 'quality_verdict': result['quality_verdict'],
        'usage': result.get('usage'), 'engineering_completed': result['engineering_completed']}, ensure_ascii=False))
    return 0 if result['status'] == 'preflight_ready' or result['engineering_completed'] else 2


if __name__ == '__main__':
    sys.exit(main())
