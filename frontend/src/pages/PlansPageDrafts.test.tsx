import { act, type ReactNode } from 'react'
import { Simulate } from 'react-dom/test-utils'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PlansPage } from './PlansPage'
import { readPlanDraft, writePlanDraft } from '../services/planApi'
import { setApiSessionUser } from '../services/sessionScope'
const api = vi.hoisted(() => ({ listPlans: vi.fn(), savePlan: vi.fn(), getPlan: vi.fn(), generateDailyPlan: vi.fn() }))
vi.mock('../services/planApi', async importOriginal => ({ ...(await importOriginal<object>()), listPlans: api.listPlans, savePlan: api.savePlan, getPlan: api.getPlan }))
vi.mock('../services/learningApi', () => ({ generateDailyPlan: api.generateDailyPlan }))
vi.mock('../components/PageShell', () => ({ PageShell: ({ children }: { children: ReactNode }) => <div>{children}</div> }))
vi.mock('../components/MarkdownLiveEditor', () => ({ MarkdownLiveEditor: ({ value, onChange }: { value: string; onChange: (s: string) => void }) => <textarea aria-label="editor" value={value} onChange={e => onChange(e.target.value)} /> }))
vi.mock('antd', () => {
  const Box = ({ children }: { children?: ReactNode }) => <div>{children}</div>
  const List = ({ dataSource, renderItem }: { dataSource: unknown[]; renderItem: (s: unknown) => ReactNode }) => <div>{dataSource.map((v,i) => <div key={i}>{renderItem(v)}</div>)}</div>
  List.Item = Box
  const Empty = () => <div />
  const DatePicker = Object.assign(Empty, { RangePicker: Empty })
  return { Space: Box, Tag: Box, List, Calendar: Empty, DatePicker, Empty, Segmented: Empty, Timeline: Empty,
    Typography: { Text: Box, Paragraph: Box }, Input: { TextArea: ({ value }: { value: string }) => <textarea readOnly value={value} /> },
    Alert: ({ message, description }: { message: string; description?: ReactNode }) => <div>{message}{description}</div>,
    Button: ({ children, onClick, disabled }: { children: ReactNode; onClick: () => void; disabled: boolean }) => <button disabled={disabled} onClick={onClick}>{children}</button>,
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  }
})
let root: ReturnType<typeof createRoot> | undefined
let container: HTMLDivElement
const day = '2026-09-28'
async function render() {
  localStorage.clear(); setApiSessionUser(1)
  api.listPlans.mockResolvedValue([{ date: day, content: '原始内容', version: 2 }])
  container = document.createElement('div'); document.body.append(container); root = createRoot(container)
  await act(async () => { root!.render(<MemoryRouter initialEntries={[`/plans?date=${day}`]}><PlansPage /></MemoryRouter>) })
}
const editor = () => container.querySelector('textarea[aria-label="editor"]') as HTMLTextAreaElement
async function edit(value: string) { await act(async () => { Simulate.change(editor(), { target: { value } } as unknown as Parameters<typeof Simulate.change>[1]) }) }
async function click(label: string) {
  const button = [...container.querySelectorAll('button')].find(n => n.textContent?.trim() === label)!
  await act(async () => { button.click() })
}
afterEach(() => { act(() => root?.unmount()); container?.remove(); vi.clearAllMocks() })
describe('plan editor preserves user work', () => {
  it('appends generation to edits made while generation was in flight without saving', async () => {
    await render()
    let resolve!: (value: unknown) => void
    api.generateDailyPlan.mockReturnValue(new Promise(r => { resolve = r }))
    await click('生成草稿')
    await edit('生成期间新增的复盘')
    await act(async () => { resolve({ date: day, content: '新待办草稿', item_count: 1, base_version: 2, saved: false }) })
    expect(editor().value).toContain('生成期间新增的复盘')
    expect(editor().value).toContain('新待办草稿')
    expect(api.savePlan).not.toHaveBeenCalled()
    expect(readPlanDraft(day)?.version).toBe(2)
  })
  it('does not discard typing that happened during a save', async () => {
    await render()
    await edit('第一个版本')
    let resolve!: (value: unknown) => void
    api.savePlan.mockReturnValue(new Promise(r => { resolve = r }))
    await click('保存')
    await edit('保存期间又写了一段')
    await act(async () => { resolve({ date: day, content: '第一个版本', version: 3 }) })
    expect(editor().value).toBe('保存期间又写了一段')
    expect(readPlanDraft(day)?.content).toBe('保存期间又写了一段')
  })
  it('retains both sides after a conflict and adopts the reviewed server version', async () => {
    await render()
    await edit('本地写作')
    api.savePlan.mockRejectedValue({ status: 409 })
    api.getPlan.mockResolvedValue({ date: day, content: '另一设备写作', version: 7 })
    await click('保存')
    expect(readPlanDraft(day)?.content).toBe('本地写作')
    await click('保留两份并继续编辑')
    expect(editor().value).toContain('另一设备写作')
    expect(editor().value).toContain('本地写作')
    expect(readPlanDraft(day)?.version).toBe(7)
    writePlanDraft(day, null)
  })
})
