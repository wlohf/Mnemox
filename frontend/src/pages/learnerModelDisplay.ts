import type { EvidenceCategory } from '../services/learnerModelApi'

const CATEGORY_LABELS: Record<EvidenceCategory, string> = {
  direct: '直接证据',
  indirect: '间接信号',
  manual: '人工修正',
  legacy: 'Legacy 来源',
}

const TYPE_LABELS: Record<string, string> = {
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

const BASIS_LABELS: Record<string, string> = {
  direct_evidence: '直接证据',
  'legacy Concept.mastery migration': 'Legacy 掌握度迁移',
  no_evidence: '暂无证据',
}

export function evidenceCategoryLabel(category: EvidenceCategory): string {
  return CATEGORY_LABELS[category]
}

export function evidenceTypeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type
}

export function explanationRows(summary: Record<string, unknown>): Array<[string, string]> {
  const rows: Array<[string, string]> = []
  const basis = summary.basis
  if (typeof basis === 'string') rows.push(['计算依据', BASIS_LABELS[basis] ?? basis])
  const direct = summary.direct_evidence_count
  if (typeof direct === 'number') rows.push(['直接证据', `${direct} 条`])
  const indirect = summary.indirect_signal_count
  if (typeof indirect === 'number') rows.push(['间接信号', `${indirect} 条`])
  const legacy = summary.legacy_evidence_count
  if (typeof legacy === 'number') rows.push(['Legacy 来源', `${legacy} 条`])
  if (summary.manual_override_active === true) rows.push(['人工修正', '生效中'])
  return rows
}
