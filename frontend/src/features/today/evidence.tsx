import type { ReactNode } from 'react'
import { BookOpenCheck, Brain, CircleX, FileText, Library, NotebookPen, Timer } from 'lucide-react'
import type { AgentGoalContext, AgentBrief, AgentCoreProfile } from '../../services/agentApi'

/*
 * Evidence model: every recommendation on "今天" points back to the learner's
 * own records. Sources are numbered once per page so citation marks [1] [2]
 * stay stable between the plan, the reasoning and the evidence panel.
 */

export type SourceKind = 'wrong' | 'review' | 'note' | 'memory' | 'material' | 'signal' | 'focus'

export interface EvidenceSource {
  n: number
  key: string
  kind: SourceKind
  title: string
  meta: string
  excerpt?: string
  highlight?: string
  route?: string
}

export const SOURCE_KIND: Record<SourceKind, { label: string; icon: ReactNode }> = {
  wrong: { label: '错题', icon: <CircleX /> },
  review: { label: '复习', icon: <BookOpenCheck /> },
  note: { label: '笔记', icon: <FileText /> },
  memory: { label: '记忆', icon: <Brain /> },
  material: { label: '资料', icon: <Library /> },
  signal: { label: '学习信号', icon: <NotebookPen /> },
  focus: { label: '专注记录', icon: <Timer /> },
}

type Item = Record<string, unknown>

const str = (v: unknown, fallback = '') => (typeof v === 'string' && v.trim() ? v.trim() : fallback)
const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)

function shortDate(iso: unknown): string {
  if (typeof iso !== 'string') return ''
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

function cleanExcerpt(text: string, max = 150): string {
  const plain = text
    .replace(/[#>*`_-]{1,}\s?/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return plain.length > max ? `${plain.slice(0, max).trimEnd()}…` : plain
}

/** Build the numbered source list from goal-context + brief. */
export function buildEvidence(ctx: AgentGoalContext | undefined, brief: AgentBrief | undefined, core?: AgentCoreProfile | null): EvidenceSource[] {
  const out: EvidenceSource[] = []
  const push = (s: Omit<EvidenceSource, 'n'>) => {
    if (out.some(o => o.key === s.key)) return
    out.push({ ...s, n: out.length + 1 })
  }
  const sc = ctx?.supporting_context ?? {}

  for (const w of (sc.wrong_questions ?? []) as Item[]) {
    const count = num(w.wrong_count) ?? 0
    push({
      key: `wrong:${w.id}`,
      kind: 'wrong',
      title: `错题本 · ${str(w.knowledge_point) || str(w.title, '未分类')}`,
      meta: [count ? `错过 ${count} 次` : '', shortDate(w.next_review_at) ? `下次复习 ${shortDate(w.next_review_at)}` : ''].filter(Boolean).join(' · '),
      excerpt: str(w.content) || undefined,
      route: '/wrong-questions',
    })
  }

  const reviews = (sc.review_items ?? []) as Item[]
  if (reviews.length > 0) {
    const questions = reviews.filter(r => r.item_type === 'question').length
    const chapters = reviews.length - questions
    push({
      key: 'review:queue',
      kind: 'review',
      title: '到期复习队列',
      meta: `${reviews.length} 项到期${questions ? ` · 题目 ${questions}` : ''}${chapters ? ` · 章节 ${chapters}` : ''}`,
      excerpt: '到期后不复习，保持率会快速下降。先做主动回忆，再看答案。',
      highlight: '先做主动回忆',
      route: '/review',
    })
  }

  for (const n of ((sc.notes ?? []) as Item[]).slice(0, 2)) {
    push({
      key: `note:${n.id}`,
      kind: 'note',
      title: `笔记《${str(n.title, '未命名笔记')}》`,
      meta: shortDate(n.updated_at) ? `${shortDate(n.updated_at)} 更新` : '相关笔记',
      excerpt: str(n.excerpt) ? cleanExcerpt(str(n.excerpt)) : undefined,
      route: '/notes',
    })
  }

  for (const m of ((sc.materials ?? []) as Item[]).slice(0, 1)) {
    push({
      key: `material:${m.id}`,
      kind: 'material',
      title: `资料 · ${str(m.title, '未命名资料')}`,
      meta: [str(m.file_type).toUpperCase(), shortDate(m.updated_at)].filter(Boolean).join(' · '),
      route: '/materials',
    })
  }

  const profile = (ctx as unknown as { snapshot?: { profile?: Item } })?.snapshot?.profile
  const optimal = str(profile?.optimal_hours)
  const perf = (profile?.recent_performance ?? {}) as Item
  const interruption = num(perf.interruption_rate)
  if (optimal || interruption !== undefined) {
    push({
      key: 'signal:rhythm',
      kind: 'focus',
      title: '专注记录 · 学习节奏',
      meta: `由 ${num(profile?.total_pomodoros) ?? 0} 次番茄记录推断`,
      excerpt: [
        optimal ? `高效时段倾向 ${optimal}。` : '',
        interruption !== undefined ? `近 7 天中断率 ${Math.round(interruption * 100)}%。` : '',
      ].join(''),
      highlight: optimal ? `高效时段倾向 ${optimal}` : undefined,
      route: '/pomodoro',
    })
  }

  const coreItems = parseCoreProfile(core)
  const style = coreItems.find(c => c.category === 'style')?.items?.[0]
  if (style) {
    push({
      key: 'memory:style',
      kind: 'memory',
      title: '长期记忆 · 学习偏好',
      meta: '已确认 · 教练会据此调整讲解方式',
      excerpt: style,
      route: '/memory',
    })
  }

  for (const sig of (brief?.watch_signals ?? []).slice(0, 1)) {
    push({ key: `signal:${sig}`, kind: 'signal', title: '需要留意', meta: '来自今日学习状态', excerpt: sig })
  }

  return out
}

export interface CoreProfileGroup {
  category: string
  items: string[]
}

export function parseCoreProfile(core?: AgentCoreProfile | null): CoreProfileGroup[] {
  if (!core?.memory_value) return []
  try {
    const parsed = JSON.parse(core.memory_value) as { summary?: CoreProfileGroup[] }
    return Array.isArray(parsed.summary) ? parsed.summary.filter(g => Array.isArray(g.items)) : []
  } catch {
    return []
  }
}

/** Map a free-text signal ("错题薄弱点：费曼复盘") to the most relevant source numbers. */
export function citeFor(sources: EvidenceSource[], hints: Array<string | undefined>): number[] {
  const text = hints.filter(Boolean).join(' ')
  const picks: number[] = []
  const want = (kind: SourceKind) => {
    const hit = sources.find(s => s.kind === kind && !picks.includes(s.n))
    if (hit) picks.push(hit.n)
  }
  if (/错题|薄弱|错/.test(text)) want('wrong')
  if (/复习|到期|遗忘|保持率/.test(text)) want('review')
  if (/走神|专注|番茄|时段|中断/.test(text)) want('focus')
  if (/笔记|复盘|费曼/.test(text)) want('note')
  if (/资料|章节/.test(text)) want('material')
  if (/偏好|记忆|习惯/.test(text)) want('memory')
  return picks.slice(0, 3)
}
