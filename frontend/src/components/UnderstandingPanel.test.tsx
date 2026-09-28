import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { UnderstandingPanel } from './UnderstandingPanel'
import { setApiSessionUser } from '../services/sessionScope'
import type { Overview } from '../services/understandingApi'
const api = vi.hoisted(() => ({ getUnderstanding: vi.fn(), setUnderstandingPreferences: vi.fn(), refreshUnderstanding: vi.fn(),
  analyzeUnderstanding: vi.fn(), reviewUnderstanding: vi.fn(), getUnderstandingEvidence: vi.fn(), getUnderstandingHistory: vi.fn(),
  searchUnderstandingMemory: vi.fn(), rebuildUnderstandingGraph: vi.fn(), excludeUnderstandingEvidence: vi.fn(),
  retryUnderstandingJob: vi.fn(), reextractUnderstandingEvidence: vi.fn(), cleanupUnderstandingGraph: vi.fn() }))
vi.mock('../services/understandingApi', () => api)
vi.mock('antd', () => {
  const Box = ({ children, title }: { children?: ReactNode; title?: ReactNode }) => <div>{title}{children}</div>
  const List = ({ dataSource, renderItem }: { dataSource: unknown[]; renderItem: (s: unknown) => ReactNode }) => <div>{dataSource.map(renderItem)}</div>
  List.Item = Box
  const Input = () => <input />
  Input.Search = ({ onSearch }: { onSearch: () => void }) => <button onClick={onSearch}>回看经历</button>
  return { Card: Box, Space: Box, Tag: Box, List, Input, Typography: { Text: Box },
    Alert: ({ message }: { message: string }) => <div>{message}</div>,
    Switch: ({ checked, disabled, onChange, ...props }: { checked: boolean; disabled: boolean; onChange: (v: boolean) => void }) => <input {...props} type="checkbox" checked={checked} disabled={disabled} onChange={e => onChange(e.target.checked)} />,
    Collapse: ({ items }: { items: { key: string; children: ReactNode }[] }) => <div>{items.map(item => <div key={item.key}>{item.children}</div>)}</div>,
    Button: ({ onClick, children, disabled }: { onClick: () => void; children: ReactNode; disabled: boolean }) => <button disabled={disabled} onClick={onClick}>{children}</button>,
    message: { error: vi.fn() },
  }
})
const hypothesis = { id: 'h1', version: 3, status: 'contested', review_status: 'unreviewed', statement: '近期画图可能对矩阵乘法有帮助',
  details: { context: '矩阵乘法', support: [{ id: 'e1', version: 'v1', quote: '先画图' }], unknowns: ['其他任务未知'], next_signal: '观察后续独立做题' },
  assessment: { support_groups: 1, counter_groups: 1, unknown_groups: 2 } }
const data = { preferences: { analysis_enabled: true, graph_enabled: false, consume_enabled: false },
  capabilities: { graphiti_episodes: false }, evidence_count: 4, hypotheses: [hypothesis], jobs: [] }
let root: ReturnType<typeof createRoot> | undefined
let container: HTMLDivElement
async function render(overrides: Partial<Overview> = {}) {
  setApiSessionUser(1)
  api.getUnderstanding.mockResolvedValue({ ...data, ...overrides })
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
  await act(async () => { root!.render(<UnderstandingPanel />) })
}
async function click(label: string) {
  const button = [...container.querySelectorAll('button')].find(n => n.textContent === label)!
  await act(async () => { button.click() })
}
afterEach(() => { act(() => root?.unmount()); container?.remove(); vi.clearAllMocks() })
describe('understanding controls', () => {
  it('labels estimates and counterevidence without claiming a probability or calling a model', async () => {
    await render()
    expect(container.textContent).toContain('出现反例')
    expect(container.textContent).toContain('估计 · v3')
    expect(container.textContent).toContain('支持 1，反例 1，未知 2')
    expect(container.textContent).toContain('当前部署使用 SQL')
    expect(api.analyzeUnderstanding).not.toHaveBeenCalled()
  })
  it('passes the displayed revision to ignore/delete and opens the exact evidence reference', async () => {
    await render()
    await click('忽略')
    expect(api.reviewUnderstanding).toHaveBeenCalledWith(hypothesis, 'ignore', null)
    api.getUnderstandingEvidence.mockResolvedValue({ id: 'e1', source: 'pomodoro:1', note: '先画图' })
    await click('查看依据：先画图')
    expect(api.getUnderstandingEvidence).toHaveBeenCalledWith('e1')
    await click('从分析和图记忆移除此经历（保留原记录）')
    expect(api.excludeUnderstandingEvidence).toHaveBeenCalledWith('e1')
  })
  it('shows later counterexamples in chronological recall and opens their evidence', async () => {
    api.searchUnderstandingMemory.mockResolvedValue({ backend: 'graphiti_episode', reason: 'entity_linked_recall',
      experiences: [
        { id: 'later', note: '后来画方格没有帮助', local_date: '2026-09-03', retrieved_by: 'graphiti_episode' },
        { id: 'early', note: '开始先画方格', local_date: '2026-09-01', retrieved_by: 'graphiti_episode' },
      ], timeline: [{ id: 'early' }, { id: 'later' }], connections: [{ from_id: 'early', to_id: 'later', entity: '矩阵' }] })
    await render()
    await click('回看经历')
    const text = container.textContent || ''
    expect(text.indexOf('开始先画方格')).toBeLessThan(text.indexOf('后来画方格没有帮助'))
    expect(text).toContain('关联主题：矩阵')
    expect(text).toContain('不能单凭先后顺序判断因果')
    const buttons = [...container.querySelectorAll('button')].filter(b => b.textContent === '查看原始依据')
    api.getUnderstandingEvidence.mockResolvedValue({ id: 'later', source: 'pomodoro:2' })
    await act(async () => { buttons[1].click() })
    expect(api.getUnderstandingEvidence).toHaveBeenCalledWith('later')
  })
  it('shows unknown usage and retries the selected failed job explicitly', async () => {
    await render({ jobs: [{ id: 'failed', task: 'graph_drain', status: 'failed', calls: [],
      usage: { model_calls: 1, usage_missing_calls: 1, actual_tokens: null, reported_tokens: 0, reserved_tokens: 1000, configured_cost_usd: null } }] })
    expect(container.textContent).toContain('1 次用量未知')
    expect(container.textContent).toContain('费用未知')
    await click('重试失败任务')
    expect(api.retryUnderstandingJob).toHaveBeenCalledWith('failed')
  })
  it('reextracts only the source version currently displayed', async () => {
    await render({ preferences: { ...data.preferences, graph_enabled: true }, capabilities: { graphiti_episodes: true } })
    const evidence = { id: 'e1', version: 'current-version', source: 'pomodoro:1', graph: { eligible: true, saved: true, extraction_revision: 1 } }
    api.getUnderstandingEvidence.mockResolvedValue(evidence)
    await click('查看依据：先画图')
    await click('重新抽取此经历（使用 AI）')
    expect(api.reextractUnderstandingEvidence).toHaveBeenCalledWith(evidence)
  })
})
