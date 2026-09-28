import type { MemoryConflict, MemoryDeclaration, MemoryItem } from '../../services/memoryApi'

/*
 * View model for 长期记忆. The ledger groups what the coach believes about the
 * learner by kind, separates what is in force from what awaits review, and
 * keeps machine rows (system flags, the aggregate profile) out of the list.
 */

export type MemoryState = 'active' | 'staged' | 'ignored' | 'expired' | 'superseded'

export const CATEGORY_META: Record<string, { label: string; order: number }> = {
  goal: { label: '目标', order: 0 },
  style: { label: '偏好与风格', order: 1 },
  weakness: { label: '薄弱点', order: 2 },
  misconception: { label: '易错理解', order: 3 },
  pattern: { label: '学习规律', order: 4 },
  study: { label: '学习习惯', order: 5 },
  practice: { label: '练习', order: 6 },
  review: { label: '复习', order: 7 },
  note_signal: { label: '笔记线索', order: 8 },
  association_evidence: { label: '知识关联', order: 9 },
  agent_feedback: { label: '对教练的反馈', order: 10 },
  coach_feedback: { label: '对教练的反馈', order: 10 },
  preference: { label: '偏好与风格', order: 1 },
}

export function categoryLabel(category: string | null | undefined): string {
  return (category && CATEGORY_META[category]?.label) || '其他'
}

/** System bookkeeping and the aggregate profile blob are not user facts. */
export function isUserFacing(m: Pick<MemoryItem, 'category' | 'memory_type' | 'memory_key'>): boolean {
  if (m.category === 'system') return false
  if (m.memory_type === 'profile') return false
  return !m.memory_key.startsWith('agent_learning_profile')
}

export function stateOf(m: Pick<MemoryItem, 'status' | 'review_status'>): MemoryState {
  if (m.review_status === 'staged' || m.status === 'staged') return 'staged'
  if (m.status === 'ignored' || m.review_status === 'ignored' || m.review_status === 'inaccurate') return 'ignored'
  if (m.status === 'expired' || m.review_status === 'expired') return 'expired'
  if (m.status === 'superseded' || m.review_status === 'superseded') return 'superseded'
  return 'active'
}

export const STATE_META: Record<MemoryState, { label: string; tone: 'success' | 'evidence' | 'neutral' | 'warning' }> = {
  active: { label: '生效中', tone: 'success' },
  staged: { label: '待你确认', tone: 'evidence' },
  ignored: { label: '已忽略', tone: 'neutral' },
  expired: { label: '已过期', tone: 'warning' },
  superseded: { label: '已被取代', tone: 'neutral' },
}

export type MemoryView = 'active' | 'staged' | 'archive'

export function viewOf(m: MemoryItem): MemoryView {
  const st = stateOf(m)
  if (st === 'active') return 'active'
  if (st === 'staged') return 'staged'
  return 'archive'
}

export interface MemoryGroup {
  category: string
  label: string
  items: MemoryItem[]
}

/** Group by category (in a stable, meaningful order), locked items first. */
export function groupMemories(items: MemoryItem[]): MemoryGroup[] {
  const byLabel = new Map<string, MemoryGroup>()
  for (const m of items) {
    const label = categoryLabel(m.category)
    const g = byLabel.get(label)
    if (g) g.items.push(m)
    else byLabel.set(label, { category: m.category, label, items: [m] })
  }
  const order = (g: MemoryGroup) => CATEGORY_META[g.category]?.order ?? 99
  return [...byLabel.values()]
    .map(g => ({
      ...g,
      items: g.items.slice().sort((a, b) => (b.is_locked ?? 0) - (a.is_locked ?? 0) || (b.confidence ?? 0) - (a.confidence ?? 0) || b.id - a.id),
    }))
    .sort((a, b) => order(a) - order(b) || a.label.localeCompare(b.label, 'zh-CN'))
}

/** Candidates that are already shown as part of a conflict are not repeated. */
export function stagedWithoutConflicts(items: MemoryItem[], conflicts: MemoryConflict[]): MemoryItem[] {
  const inConflict = new Set(conflicts.map(c => c.candidate_memory_id))
  return items.filter(m => stateOf(m) === 'staged' && !inConflict.has(m.id))
}

export function confidenceLabel(c: number | null | undefined): string {
  const v = Number(c ?? 0)
  if (v >= 0.85) return '很有把握'
  if (v >= 0.65) return '比较有把握'
  if (v >= 0.4) return '推测'
  return '把握不大'
}

/* ---------------- Provenance ---------------- */

const CREATOR: Record<string, string> = { user: '你', model: '对话提炼', agent: '教练', system: '系统' }

export function creatorLabel(createdBy: string | null | undefined): string {
  return (createdBy && CREATOR[createdBy]) || createdBy || '未知'
}

const SOURCE: Record<string, string> = {
  learning_event_aggregate: '学习记录汇总',
  conversation: '对话',
  chat: '对话',
  note: '笔记',
  wrong_question: '错题',
  review: '复习',
  pomodoro: '专注记录',
  manual: '手动填写',
  agent_feedback: '你对建议的反馈',
  showcase_seed: '示例数据',
  demo_seed: '示例数据',
}

export function sourceLabel(sourceType: string | null | undefined): string {
  if (!sourceType) return '早期记录'
  return SOURCE[sourceType] ?? sourceType
}

/** Readable lines from a declaration's evidence payload. */
export function evidenceLines(evidence: unknown): string[] {
  if (!evidence) return []
  const list = Array.isArray(evidence) ? evidence : [evidence]
  return list
    .map(e => {
      if (typeof e === 'string') return e
      if (e && typeof e === 'object') {
        const o = e as Record<string, unknown>
        if (typeof o.excerpt === 'string') return o.excerpt
        if (typeof o.text === 'string') return o.text
        if (o.kind === 'aggregate') {
          if (typeof o.event_type === 'string' && typeof o.duration_seconds === 'number')
            return `${o.event_type} 累计 ${Math.round(o.duration_seconds / 60)} 分钟`
          if (typeof o.category === 'string' && typeof o.count === 'number') return `${o.category} 类行为 ${o.count} 次`
        }
        return Object.entries(o)
          .filter(([k]) => k !== 'kind')
          .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
          .join(' · ')
      }
      return String(e)
    })
    .filter(Boolean)
    .slice(0, 6)
}

/** Declarations newest first, so the history reads as a timeline. */
export function timeline(declarations: MemoryDeclaration[]): MemoryDeclaration[] {
  return declarations
    .slice()
    .sort((a, b) => (b.observed_at ?? b.created_at ?? '').localeCompare(a.observed_at ?? a.created_at ?? '') || b.id - a.id)
}
