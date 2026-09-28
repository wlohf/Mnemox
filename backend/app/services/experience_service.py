"""Canonical, owner-scoped experiences. Derived summaries are never observations."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from uuid import uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.models.coach import CoachActionAttempt, CoachNudge
from app.models.daily_plan import DailyPlan
from app.models.goal import Goal, Task
from app.models.pomodoro import Pomodoro
from app.models.memory import UserMemory
from app.models.understanding import Experience, BehavioralHypothesis, HypothesisRevision
from app.services.behavior_evidence_service import read_focus_evidence, resolve_analysis_time_zone
from app.utils.utc import utc_now_db, to_db_utc, to_utc_iso

LIMIT = 5000


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def parse_time(value):
    return to_db_utc(datetime.fromisoformat(value.replace('Z', '+00:00'))) if value else None


def reflection_text(content):
    """Only explicitly labelled self-reflection; exclude generated questions/prompts."""
    match = re.search(r'^## (?:晚间费曼复盘[^\n]*|今日总结|复盘)\s*\n(.*?)(?=^## |\Z)', content or '', re.M | re.S)
    if not match:
        return ''
    template_lines = {
        '1. 今天我真正理解了什么？', '1. 我今天真正理解了什么？',
        '2. 如果讲给一个完全没学过的人，我会怎么解释？',
        '2. 如果要讲给一个完全没学过的人，我会怎么解释？',
        '3. 哪个地方还讲不顺？明天要补的最小缺口是什么？',
        '3. 哪一步还讲不顺？明天要补哪一个最小缺口？',
        '3. 哪个地方还讲不顺？',
    }
    lines = [line for line in match.group(1).splitlines() if line.strip() and
             line.strip() not in template_lines and
             not line.strip().startswith(('>', '请用自己的话', '- [', '<!--'))]
    return '\n'.join(lines).strip()[:6000]


async def demo_goal_ids(db, user_id):
    seeded = await db.scalar(select(UserMemory.id).where(UserMemory.user_id == user_id,
        UserMemory.memory_key == 'demo_mnemox_seeded').limit(1))
    if not seeded:
        return set()
    return set((await db.scalars(select(Goal.id).where(Goal.user_id == user_id,
        Goal.title == '7 天建立主动学习闭环',
        Goal.description == '用 Demo 资料体验：资料理解 → 任务执行 → 番茄钟 → 费曼复盘 → 间隔复习。'))).all())


async def canonical_experiences(db, user_id, *, now=None):
    now = now or utc_now_db()
    tz, tz_source = await resolve_analysis_time_zone(db, user_id)
    focus, truncated = await read_focus_evidence(db, user_id, time_zone=tz, now=now)
    data, incomplete = {}, set()
    if truncated:
        incomplete.add('pomodoro')
    # Canonical Pomodoro row supplies notes/Coach links, never a derived event copy.
    pomos = {p.id: p for p in (await db.scalars(select(Pomodoro).where(
        Pomodoro.user_id == user_id, Pomodoro.id.in_([r.source.id for r in focus]),
    ).execution_options(populate_existing=True))).all()} if focus else {}
    def put(kind, ident, payload, occurred, recorded, group, eligible=True):
        key = f'{kind}:{ident}'
        payload = {**payload, 'kind': kind, 'time_zone': tz, 'time_zone_source': tz_source,
                   'occurred_at': to_utc_iso(occurred) if occurred else None,
                   'recorded_at': to_utc_iso(recorded) if recorded else None,
                   'eligible': eligible, 'evidence_group': group}
        data[key] = {'source_key': key, 'source_version': fingerprint(payload), 'kind': kind,
                     'occurred_at': occurred, 'recorded_at': recorded, 'evidence_group': group, 'payload': payload}
    for item in focus:
        p = pomos[item.source.id]
        payload = item.model_dump(mode='json')
        payload['note'] = (p.note or '')[:4000]
        # Task outcomes, reflection, and focus on one local day are conservatively
        # clustered; sessions extending midnight still retain their session group.
        group = f'day:{item.local_date}' if not p.session_id else item.evidence_group
        payload['independence_day'] = item.local_date
        put('pomodoro', p.id, payload, parse_time(item.source.occurred_at), parse_time(item.source.recorded_at),
            group, item.included)
    demo_goals = await demo_goal_ids(db, user_id)
    tasks = (await db.scalars(select(Task).join(Goal).where(Goal.user_id == user_id)
        .order_by(Task.updated_at.desc(), Task.id.desc()).limit(LIMIT + 1).execution_options(populate_existing=True))).all()
    if len(tasks) > LIMIT:
        incomplete.add('task')
    for t in tasks[:LIMIT]:
        occurred = t.completed_at if t.status == 'completed' else None
        local_day = occurred.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz)).date().isoformat() if occurred else None
        put('task', t.id, {'title': t.title, 'task_type': t.task_type, 'outcome': t.status,
            'sync_version': t.sync_version, 'planned_date': str(t.planned_date) if t.planned_date else None,
            'quality_flags': (['synthetic_record'] if t.goal_id in demo_goals else []) + ([] if occurred else ['unknown_outcome_time']), 'independence_day': local_day},
            occurred, t.updated_at, f'day:{local_day}' if local_day else f'task:{t.id}', bool(occurred and occurred <= now and t.goal_id not in demo_goals))
    plans = (await db.scalars(select(DailyPlan).where(DailyPlan.user_id == user_id)
        .order_by(DailyPlan.date.desc()).limit(LIMIT + 1).execution_options(populate_existing=True))).all()
    if len(plans) > LIMIT:
        incomplete.add('reflection')
    for p in plans[:LIMIT]:
        body = reflection_text(p.content)
        if not body:
            continue
        # A date is user-reported context, not a fabricated exact occurrence time.
        put('reflection', p.id, {'text': body, 'local_date': p.date, 'independence_day': p.date,
            'plan_version': p.version, 'quality_flags': ['self_report', 'date_only'], 'epistemic_type': 'user_report'},
            None, p.updated_at, f'day:{p.date}')
    attempts = (await db.execute(select(CoachActionAttempt, CoachNudge).join(CoachNudge,
        CoachActionAttempt.nudge_id == CoachNudge.id).where(CoachActionAttempt.user_id == user_id,
        CoachNudge.user_id == user_id).order_by(CoachActionAttempt.updated_at.desc()).limit(LIMIT + 1)
        .execution_options(populate_existing=True))).all()
    if len(attempts) > LIMIT:
        incomplete.add('coach')
    for a, n in attempts[:LIMIT]:
        occurred = a.completed_at or a.observed_at or a.started_at
        day = occurred.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz)).date().isoformat() if occurred else None
        put('coach', a.id, {'suggestion': n.title, 'suggested_action': a.action_type,
            'outcome': a.status, 'outcome_source': a.outcome_source, 'outcome_reason': a.outcome_reason,
            'independence_day': day, 'epistemic_type': 'action_record',
            'quality_flags': ['derived_action_link', 'not_independent_evidence'] +
                (['outcome_unknown'] if not a.completed_at else [])}, occurred, a.updated_at, f'day:{day}')
    return data, incomplete


def public_experience(row):
    return {'id': row.id, 'version': row.source_version, 'source': row.source_key,
            'group': row.evidence_group, 'first_seen_at': to_utc_iso(row.first_seen_at), **row.payload}


async def live_experiences(db, user_id, *, now=None):
    """Read validation protects all consumers even before the worker catches up."""
    canonical, incomplete = await canonical_experiences(db, user_id, now=now)
    rows = (await db.scalars(select(Experience).where(Experience.user_id == user_id,
        Experience.active.is_(True), Experience.excluded.is_(False)).execution_options(populate_existing=True))).all()
    return [r for r in rows if r.source_key in canonical and
            r.source_version == canonical[r.source_key]['source_version']], incomplete


async def refresh_experiences(db, user_id, *, now=None, collect_new=True):
    """Caller owns the transaction. Changed inputs invalidate saved extractions first."""
    now = now or utc_now_db()
    canonical, incomplete = await canonical_experiences(db, user_id, now=now)
    stored = {e.source_key: e for e in (await db.scalars(select(Experience).where(Experience.user_id == user_id))).all()}
    changed = set()
    for key, value in canonical.items():
        row = stored.get(key)
        if row is not None and row.excluded:
            # An exclusion is an enduring user tombstone, including later edits.
            continue
        if row is None and not collect_new:
            continue
        if row is None:
            row = Experience(id=uuid4().hex, user_id=user_id, first_seen_at=now, **value)
            db.add(row)
        elif row.source_version != value['source_version'] or not row.active:
            changed.add(row.id)
            for attr, val in value.items():
                setattr(row, attr, val)
            row.active = True
            row.extraction = None
            row.graph_pending = bool(row.graph_group)
    for key, row in stored.items():
        if key not in canonical and row.kind not in incomplete and row.active:
            changed.add(row.id)
            row.active = False
            row.payload = {}
            row.extraction = None
            row.graph_pending = bool(row.graph_group)
    if changed:
        hypotheses = (await db.scalars(select(BehavioralHypothesis).where(
            BehavioralHypothesis.user_id == user_id, BehavioralHypothesis.status != 'deleted'))).all()
        for h in hypotheses:
            refs = (h.details or {}).get('support', []) + (h.details or {}).get('counter', []) + (h.details or {}).get('context_refs', [])
            if any(ref.get('id') in changed for ref in refs):
                # Purge derived text as it can reproduce deleted source text. The
                # reason/version remains auditable; regeneration requires a new job.
                h.statement = '依据已修改或删除，原判断已撤回'
                h.details = {}
                h.assessment = {'reason': 'source_changed_or_deleted'}
                h.status = 'withdrawn'
                h.version += 1
                for rev in (await db.scalars(select(HypothesisRevision).where(
                    HypothesisRevision.hypothesis_id == h.id, HypothesisRevision.user_id == user_id))).all():
                    rev.snapshot = {'redacted': True, 'reason': 'source_changed_or_deleted'}
                db.add(HypothesisRevision(user_id=user_id, hypothesis_id=h.id, version=h.version,
                    reason='source_changed_or_deleted', snapshot={'status': h.status}))
    await db.flush()
    return await live_experiences(db, user_id, now=now)
