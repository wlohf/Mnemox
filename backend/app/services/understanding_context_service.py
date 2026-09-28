"""Read-only, explicitly provisional context for chat and Coach."""
import json
from sqlalchemy import select
from app.config import settings
from app.models.understanding import UnderstandingPreference, BehavioralHypothesis
from app.services.experience_service import live_experiences
from app.services.graphiti_episode_service import search_episode_memory
from app.services.hypothesis_service import hypothesis_dto
from app.utils.prompt_safety import wrap_untrusted_context


async def understanding_context(db, user_id, query='上次学习的卡点、尝试与结果、近期变化'):
    pref = await db.get(UnderstandingPreference, user_id)
    if not settings.UNDERSTANDING_ENABLED or not pref or not pref.consume_enabled:
        return {}
    preference_revision = pref.revision
    memory = await search_episode_memory(db, user_id, query)
    pref = await db.get(UnderstandingPreference, user_id, populate_existing=True)
    if not pref or not pref.consume_enabled or pref.revision != preference_revision:
        return {}
    live, _ = await live_experiences(db, user_id)
    versions = {r.id: r.source_version for r in live}
    rows = (await db.scalars(select(BehavioralHypothesis).where(BehavioralHypothesis.user_id == user_id,
        BehavioralHypothesis.review_status.in_(['unreviewed', 'corrected']), BehavioralHypothesis.status.in_(['candidate', 'observing', 'contested', 'needs_review']))
        .order_by(BehavioralHypothesis.updated_at.desc()).limit(6))).all()
    hypotheses, corrections = [], []
    if pref.analysis_enabled:
        for h in rows:
            refs = h.details.get('support', []) + h.details.get('counter', []) + h.details.get('context_refs', [])
            if refs and all(versions.get(r['id']) == r['version'] for r in refs):
                if h.review_status == 'corrected':
                    corrections.append({'hypothesis_id':h.id,'version':h.version,'type':'user_report',
                        'text':h.details.get('user_correction'),'confirmed_fact':False})
                else:
                    hypotheses.append(hypothesis_dto(h))
    return {'hypotheses': hypotheses, 'user_corrections': corrections, 'continuous_memory': memory,
        'instruction': '仅作阶段性估计；引用来源并区分事实、用户自述和猜测。反例、缺失和已尝试结果须保留。图不可用时说明当前为 SQL 记录回退。不得自动改变任务、确认事实或更新掌握度。'}


async def understanding_prompt(db, user_id, query='上次学习的卡点、尝试与结果、近期变化'):
    context = await understanding_context(db, user_id, query)
    if not context:
        return ''
    return '\n\n' + wrap_untrusted_context('阶段性理解与连续经历（估计，不是永久特性）',
        json.dumps(context, ensure_ascii=False), source='understanding_sql_validated', max_chars=12000)
