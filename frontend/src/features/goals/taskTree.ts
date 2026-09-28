import type { OfflineGoalTaskItem } from '../../hooks/useOfflineGoalTasks'

/*
 * Pure helpers for the goal outline: build the milestone → task → subtask
 * tree, order it like a study plan (not by last edit), and describe dates in
 * the learner's terms. No React here so it stays unit-testable.
 */

export type TaskType = 'milestone' | 'learn' | 'review' | 'practice' | 'summarize'

export const TASK_TYPES: Array<{ value: Exclude<TaskType, 'milestone'>; label: string }> = [
  { value: 'learn', label: '学习' },
  { value: 'review', label: '复习' },
  { value: 'practice', label: '练习' },
  { value: 'summarize', label: '总结' },
]

export function taskTypeLabel(type: string | null | undefined): string {
  if (type === 'milestone') return '里程碑'
  return TASK_TYPES.find(t => t.value === type)?.label ?? '学习'
}

export interface TaskNode {
  task: OfflineGoalTaskItem
  children: TaskNode[]
}

/** Plan order: undated work after dated work, then by date, then creation. */
export function comparePlanOrder(a: OfflineGoalTaskItem, b: OfflineGoalTaskItem): number {
  const ad = a.planned_date ?? ''
  const bd = b.planned_date ?? ''
  if (ad !== bd) {
    if (!ad) return 1
    if (!bd) return -1
    return ad < bd ? -1 : 1
  }
  const ac = a.created_at ?? a.updated_at
  const bc = b.created_at ?? b.updated_at
  if (ac !== bc) return ac < bc ? -1 : 1
  // Stable tiebreak so equal rows never swap between renders.
  const as = a._serverId ?? Number.MAX_SAFE_INTEGER
  const bs = b._serverId ?? Number.MAX_SAFE_INTEGER
  if (as !== bs) return as - bs
  return a._localId < b._localId ? -1 : a._localId > b._localId ? 1 : 0
}

/**
 * Parent links are server ids, so a task can only hang under a synced parent.
 * Unsynced or dangling children fall back to the root instead of vanishing,
 * and a cycle in bad data can never recurse forever.
 */
export function buildTaskTree(tasks: OfflineGoalTaskItem[]): TaskNode[] {
  const serverIds = new Set(tasks.map(t => t._serverId).filter((id): id is number => id != null))
  const byParent = new Map<number | null, OfflineGoalTaskItem[]>()
  for (const t of tasks) {
    const parent =
      t.parent_task_id != null && serverIds.has(t.parent_task_id) && t.parent_task_id !== t._serverId ? t.parent_task_id : null
    const bucket = byParent.get(parent)
    if (bucket) bucket.push(t)
    else byParent.set(parent, [t])
  }

  const build = (parent: number | null, ancestors: Set<number>): TaskNode[] =>
    (byParent.get(parent) ?? [])
      .slice()
      .sort(comparePlanOrder)
      .map(task => {
        const id = task._serverId
        if (id == null || ancestors.has(id)) return { task, children: [] }
        const next = new Set(ancestors).add(id)
        return { task, children: build(id, next) }
      })

  const roots = build(null, new Set())
  // Milestones lead the outline; loose tasks follow in plan order.
  return [...roots.filter(n => n.task.task_type === 'milestone'), ...roots.filter(n => n.task.task_type !== 'milestone')]
}

export interface Progress {
  done: number
  total: number
  ratio: number
}

/** Progress over actionable work: milestones are containers, not tasks. */
export function progressOf(tasks: OfflineGoalTaskItem[]): Progress {
  const work = tasks.filter(t => t.task_type !== 'milestone')
  const counted = work.length > 0 ? work : tasks
  const done = counted.filter(t => t.status === 'completed').length
  return { done, total: counted.length, ratio: counted.length ? done / counted.length : 0 }
}

export function flattenTree(nodes: TaskNode[]): OfflineGoalTaskItem[] {
  return nodes.flatMap(n => [n.task, ...flattenTree(n.children)])
}

/* ---------------- Dates ---------------- */

export { deadlineLabel, dueLabel, localDay, minutesSince, type DueLabel } from '../../lib/dates'
