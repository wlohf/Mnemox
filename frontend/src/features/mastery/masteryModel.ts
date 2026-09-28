import type { ConceptState, ConceptSummary, EvidenceCategory, LearningRecommendation } from '../../services/learnerModelApi'
import type { MasteryMapData } from '../../services/learningApi'

/*
 * View model for 掌握度. Mastery lives on a 0–100 scale; the UI speaks in five
 * steps (the --mx-m1…m5 ramp) so a glance says "shaky" or "solid" without
 * reading numbers. Every figure keeps a path back to its evidence.
 */

export type Level = 0 | 1 | 2 | 3 | 4 | 5

/** 0 = no evidence yet; 1–5 from shaky to solid. */
export function levelOf(mastery: number | null | undefined, hasEvidence = true): Level {
  if (!hasEvidence) return 0
  const v = Math.max(0, Math.min(100, Number(mastery ?? 0)))
  if (v >= 85) return 5
  if (v >= 70) return 4
  if (v >= 50) return 3
  if (v >= 30) return 2
  return 1
}

export const LEVEL_LABEL: Record<Level, string> = {
  0: '还没有证据',
  1: '很不牢',
  2: '有点印象',
  3: '基本理解',
  4: '比较扎实',
  5: '很扎实',
}

export function levelColor(level: Level): string {
  return level === 0 ? 'var(--mx-sunken)' : `var(--mx-m${level})`
}

export function pct(v: number | null | undefined): number {
  return Math.round(Math.max(0, Math.min(100, Number(v ?? 0))))
}

/** Probabilities (0–1) as whole percents. */
export function pct01(v: number | null | undefined): number {
  return pct(Number(v ?? 0) * 100)
}

export function riskLabel(risk: number | null | undefined): { text: string; tone: 'success' | 'warning' | 'danger' | 'neutral' } {
  const r = Number(risk ?? 0)
  if (r >= 0.65) return { text: '快要忘了', tone: 'danger' }
  if (r >= 0.35) return { text: '该复习了', tone: 'warning' }
  if (r > 0) return { text: '记得还牢', tone: 'success' }
  return { text: '未知', tone: 'neutral' }
}

/* ---------------- Concepts ---------------- */

export type ConceptFilter = 'all' | 'weak' | 'pending' | 'confirmed'

export function filterConcepts(concepts: ConceptSummary[], filter: ConceptFilter, query: string): ConceptSummary[] {
  const q = query.trim().toLowerCase()
  return concepts.filter(c => {
    if (filter === 'pending' && c.review_status !== 'pending') return false
    if (filter === 'confirmed' && c.review_status !== 'confirmed') return false
    if (filter === 'weak' && !(c.review_status === 'confirmed' && pct(c.mastery) < 50)) return false
    return !q || c.name.toLowerCase().includes(q)
  })
}

/** Confirmed first, then weakest first so gaps surface; stable by name. */
export function sortConcepts(concepts: ConceptSummary[]): ConceptSummary[] {
  const rank = (c: ConceptSummary) => (c.review_status === 'confirmed' ? 0 : c.review_status === 'pending' ? 1 : 2)
  return concepts.slice().sort((a, b) => rank(a) - rank(b) || a.mastery - b.mastery || a.name.localeCompare(b.name, 'zh-CN'))
}

export interface Overview {
  confirmed: number
  pending: number
  average: number | null
  weak: number
}

export function overviewOf(concepts: ConceptSummary[]): Overview {
  const confirmed = concepts.filter(c => c.review_status === 'confirmed')
  const pending = concepts.filter(c => c.review_status === 'pending').length
  const average = confirmed.length ? pct(confirmed.reduce((s, c) => s + c.mastery, 0) / confirmed.length) : null
  const weak = confirmed.filter(c => pct(c.mastery) < 50).length
  return { confirmed: confirmed.length, pending, average, weak }
}

/* ---------------- Chapters ---------------- */

export interface ChapterRow {
  id: number
  title: string
  mastery: number
  level: Level
}

export interface MaterialMastery {
  id: number
  title: string
  average: number
  chapters: ChapterRow[]
}

export function chapterMatrix(data: MasteryMapData | null | undefined): MaterialMastery[] {
  return (data?.materials ?? []).map(m => ({
    id: m.material_id,
    title: m.material_title,
    average: pct(m.average_mastery),
    chapters: m.chapters.map(c => ({ id: c.chapter_id, title: c.chapter_title, mastery: pct(c.mastery_level), level: levelOf(c.mastery_level) })),
  }))
}

/* ---------------- Recommendations ---------------- */

export const RECOMMENDATION_META: Record<LearningRecommendation['task_type'], { label: string; tone: 'evidence' | 'danger' | 'ink' | 'neutral' }> = {
  review_due: { label: '到期复习', tone: 'evidence' },
  prerequisite_gap: { label: '先补前置', tone: 'danger' },
  retrieval_practice: { label: '无提示回忆', tone: 'ink' },
  continue_goal: { label: '接着推进目标', tone: 'neutral' },
  targeted_practice: { label: '针对性练习', tone: 'ink' },
}

/** Where a recommendation should take the learner. */
export function recommendationRoute(r: LearningRecommendation): string {
  if (r.task_type === 'review_due') return '/review'
  if (r.task_type === 'continue_goal') return '/goals'
  return `/?${new URLSearchParams({ ask: r.suggested_action || `帮我练习「${r.concept_name}」`, context: r.concept_name })}`
}

/* ---------------- Evidence ---------------- */

export const CATEGORY_META: Record<EvidenceCategory, { label: string; hint: string }> = {
  direct: { label: '直接证据', hint: '作答、回忆、讲解这类能直接说明掌握程度的表现' },
  indirect: { label: '间接信号', hint: '学习时长、频率、中断等只能侧面反映的信号' },
  manual: { label: '你的修正', hint: '你手动调整过的掌握度' },
  legacy: { label: '早期记录', hint: '旧版本迁移过来的掌握度' },
}

const TYPE_LABEL: Record<string, string> = {
  answer: '作答表现',
  recall: '主动回忆',
  explanation: '概念讲解',
  application: '迁移应用',
  hint_count: '提示依赖',
  review_result: '复习结果',
  study_duration: '学习时长',
  study_frequency: '学习频率',
  repeated_question: '重复提问',
  interruption: '中断信号',
  recovery: '恢复信号',
  legacy_mastery: '旧掌握度',
  manual_override: '人工修正',
}

export function evidenceTypeLabel(type: string): string {
  return TYPE_LABEL[type] ?? type
}

/** Plain-language basis for the current estimate. */
export function basisOf(state: ConceptState | null | undefined): string {
  if (!state) return ''
  const s = state.explanation_summary ?? {}
  if (state.manual_override?.active) return '你手动修正过这个概念的掌握度，下面的证据仍然保留。'
  const direct = typeof s.direct_evidence_count === 'number' ? s.direct_evidence_count : 0
  const indirect = typeof s.indirect_signal_count === 'number' ? s.indirect_signal_count : 0
  if (direct === 0 && indirect === 0) return '还没有和这个概念相关的练习记录。做一次回忆或练习后，这里会给出估计。'
  if (direct === 0) return `只有 ${indirect} 条间接信号，还不足以判断掌握程度，所以估计比较保守。`
  return `根据 ${direct} 条直接证据${indirect ? `和 ${indirect} 条间接信号` : ''}估计。`
}
