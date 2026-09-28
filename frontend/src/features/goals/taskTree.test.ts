import { describe, expect, it } from 'vitest'
import type { OfflineGoalTaskItem } from '../../hooks/useOfflineGoalTasks'
import { buildTaskTree, deadlineLabel, dueLabel, flattenTree, progressOf } from './taskTree'

let seq = 0
function task(p: Partial<OfflineGoalTaskItem>): OfflineGoalTaskItem {
  seq += 1
  return {
    _localId: `l${seq}`,
    _serverId: seq,
    _syncStatus: 'synced',
    goal_id: 1,
    _localGoalId: 'g1',
    parent_task_id: null,
    chapter_id: null,
    chapter_title: null,
    title: `t${seq}`,
    description: null,
    task_type: 'learn',
    planned_date: null,
    status: 'pending',
    completed_at: null,
    created_at: `2026-09-0${Math.min(seq, 9)}T00:00:00Z`,
    updated_at: `2026-09-0${Math.min(seq, 9)}T00:00:00Z`,
    ...p,
  }
}

describe('buildTaskTree', () => {
  it('nests tasks under synced parents and puts milestones first', () => {
    const loose = task({ title: 'loose', planned_date: '2026-09-20' })
    const m = task({ title: 'milestone', task_type: 'milestone' })
    const child = task({ title: 'child', parent_task_id: m._serverId })
    const tree = buildTaskTree([loose, child, m])
    expect(tree.map(n => n.task.title)).toEqual(['milestone', 'loose'])
    expect(tree[0].children.map(n => n.task.title)).toEqual(['child'])
  })

  it('keeps children of an unknown parent at the root instead of dropping them', () => {
    const orphan = task({ title: 'orphan', parent_task_id: 9999 })
    expect(buildTaskTree([orphan]).map(n => n.task.title)).toEqual(['orphan'])
  })

  it('survives a parent cycle without recursing forever', () => {
    const a = task({ title: 'a' })
    const b = task({ title: 'b', parent_task_id: a._serverId })
    a.parent_task_id = b._serverId
    const tree = buildTaskTree([a, b])
    expect(flattenTree(tree).length).toBeLessThanOrEqual(2)
  })

  it('orders dated work by date and puts undated work last', () => {
    const late = task({ title: 'late', planned_date: '2026-09-28' })
    const none = task({ title: 'none' })
    const early = task({ title: 'early', planned_date: '2026-09-21' })
    expect(buildTaskTree([late, none, early]).map(n => n.task.title)).toEqual(['early', 'late', 'none'])
  })
})

describe('progressOf', () => {
  it('counts actionable tasks, not milestones', () => {
    const p = progressOf([
      task({ task_type: 'milestone', status: 'completed' }),
      task({ status: 'completed' }),
      task({}),
    ])
    expect(p).toEqual({ done: 1, total: 2, ratio: 0.5 })
  })

  it('returns zero for an empty goal', () => {
    expect(progressOf([])).toEqual({ done: 0, total: 0, ratio: 0 })
  })
})

describe('date labels', () => {
  const today = '2026-09-25'
  it('describes planned dates relative to today', () => {
    expect(dueLabel('2026-09-23', today)).toEqual({ text: '逾期 2 天', tone: 'overdue' })
    expect(dueLabel('2026-09-25', today)).toEqual({ text: '今天', tone: 'today' })
    expect(dueLabel('2026-09-26', today)).toEqual({ text: '明天', tone: 'soon' })
    expect(dueLabel('2026-10-02', today)).toEqual({ text: '10月2日' })
    expect(dueLabel('2026-09-23', today, true)).toEqual({ text: '9月23日' })
    expect(dueLabel(null, today)).toBeNull()
  })

  it('describes goal deadlines', () => {
    expect(deadlineLabel('2026-10-02', today)).toEqual({ text: '还剩 7 天', tone: undefined })
    expect(deadlineLabel('2026-09-27', today)).toEqual({ text: '还剩 2 天', tone: 'soon' })
    expect(deadlineLabel('2026-09-25', today)).toEqual({ text: '今天截止', tone: 'today' })
    expect(deadlineLabel('2026-09-20', today)).toEqual({ text: '已过期 5 天', tone: 'overdue' })
  })
})
