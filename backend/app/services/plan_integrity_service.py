"""Versioned plan edits; task checkboxes refer to domain IDs, never titles."""
import re
from fastapi import HTTPException
from sqlalchemy import select
from app.models.daily_plan import DailyPlan, DailyPlanRevision
from app.models.goal import Goal, Task
from app.utils.mutation_lock import lock_user_mutation

LINK = re.compile(r'^\s*[-*]\s+\[([ xX])\].*?<!-- task:(\d+):v(\d+) -->\s*$')


def links(content):
    result = {}
    for line in (content or '').splitlines():
        match = LINK.match(line)
        if match:
            checked, task_id, version = match.groups()
            key = int(task_id)
            value = (checked.lower() == 'x', int(version))
            if key in result and result[key] != value:
                raise HTTPException(422, '同一任务存在相互矛盾的勾选')
            result[key] = value
    return result


async def render_plan(db, row):
    """Refresh task state and task version together without creating a plan edit."""
    content = row.content or ''
    refs = links(content)
    if not refs:
        return content
    tasks = (await db.scalars(select(Task).join(Goal).where(
        Goal.user_id == row.user_id, Task.id.in_(refs),
    ))).all()
    states = {t.id: (t.status == 'completed', t.sync_version) for t in tasks}
    lines = []
    for line in content.splitlines():
        match = LINK.match(line)
        if match:
            task_id = int(match.group(2))
            if task_id in states:
                done, version = states[task_id]
                line = re.sub(r'\[[ xX]\]', '[x]' if done else '[ ]', line, count=1)
                line = re.sub(r'<!-- task:.*? -->', f'<!-- task:{task_id}:v{version} -->', line)
            else:
                line = re.sub(r'<!-- task:.*? -->', '(关联任务已删除)', line)
        lines.append(line)
    return '\n'.join(lines)


async def save_plan(db, user, day, content, expected_version):
    await lock_user_mutation(db, user.id)
    row = await db.scalar(select(DailyPlan).where(DailyPlan.user_id == user.id, DailyPlan.date == day))
    current = row.version if row else 0
    if expected_version is None or expected_version != current:
        raise HTTPException(409, {'message': '计划已变化，请保留草稿并重新读取后合并', 'version': current})
    refs = links(content)
    if refs:
        from app.routers.goals import update_task, TaskUpdate
        tasks = (await db.scalars(select(Task).join(Goal).where(Goal.user_id == user.id, Task.id.in_(refs)))).all()
        if len(tasks) != len(refs):
            raise HTTPException(422, '关联任务不存在或不属于当前用户')
        for task in tasks:
            done, version = refs[task.id]
            if version != task.sync_version:
                raise HTTPException(409, '关联任务已变化，请重新读取计划后合并')
            if done != (task.status == 'completed'):
                await update_task(task_id=task.id, body=TaskUpdate(status='completed' if done else 'pending'),
                                  if_match=str(version), idempotency_key=None, db=db, current_user=user)
                content = content.replace(f'<!-- task:{task.id}:v{version} -->', f'<!-- task:{task.id}:v{task.sync_version} -->')
    if row:
        if row.content == content:
            return row
        old = await db.scalar(select(DailyPlanRevision.id).where(DailyPlanRevision.plan_id == row.id, DailyPlanRevision.version == row.version))
        if old is None:
            db.add(DailyPlanRevision(plan_id=row.id, user_id=user.id, version=row.version, content=row.content or ''))
        row.content = content
    else:
        row = DailyPlan(user_id=user.id, date=day, content=content)
        db.add(row)
    await db.flush()
    db.add(DailyPlanRevision(plan_id=row.id, user_id=user.id, version=row.version, content=row.content or ''))
    await db.flush()
    from app.services.understanding_runtime import enqueue_understanding
    await enqueue_understanding(db, user.id)
    return row
