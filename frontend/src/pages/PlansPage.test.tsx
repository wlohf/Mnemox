import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { PlansPage } from './PlansPage'

vi.mock('../components/PageShell', () => ({
  PageShell: ({ children, title, rightExtra }: { children: React.ReactNode; title: React.ReactNode; rightExtra?: React.ReactNode }) => (
    <div>
      <div data-testid="page-title">{title}</div>
      <div data-testid="page-extra">{rightExtra}</div>
      {children}
    </div>
  ),
}))

vi.mock('../components/MarkdownLiveEditor', () => ({
  MarkdownLiveEditor: ({ value, placeholder }: { value: string; placeholder?: string }) => (
    <div data-testid="markdown-editor" data-placeholder={placeholder}>{value}</div>
  ),
}))

vi.mock('../services/apiClient', () => ({
  apiFetch: vi.fn(async (url: string, options?: RequestInit) => {
    if (url.startsWith('/api/plans/?')) {
      return [
        { date: '2026-06-02', content: '# 2026-06-02\n\n- [ ] 修计划页\n- [x] 修番茄钟' },
        { date: '2026-06-01', content: '# 2026-06-01\n\n- [ ] 复习错题' },
      ]
    }
    if (url === '/api/plans/2026-06-02' && options?.method === 'PUT') {
      return { date: '2026-06-02', content: '# 2026-06-02\n\n- [ ] 修计划页\n- [x] 修番茄钟' }
    }
    return []
  }),
  getApiErrorMessage: vi.fn(() => '生成计划失败'),
}))

vi.mock('../services/learningApi', () => ({
  generateDailyPlan: vi.fn(async () => ({
    date: '2026-06-02',
    content: '# 2026-06-02\n\n- [ ] AI 生成的新任务',
    item_count: 1,
    items: [],
  })),
}))

vi.mock('../services/feynmanProbeApi', () => ({
  generateFeynmanProbe: vi.fn(async () => ({
    name: '明镜追问',
    tagline: '追问你是否真的讲清楚了',
    date: '2026-06-02',
    source_excerpt: '',
    questions: [{ type: '概念', question: '为什么先做这个？', why: '确认优先级判断' }],
    strongest_part: '任务拆分很清楚',
    next_focus: '补充任务排序依据',
    fallback: false,
  })),
}))

vi.mock('antd', async () => {
  const passthrough = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>
  const Button = ({ children, onClick, icon, ...props }: any) => <button onClick={onClick} {...props}>{icon}{children}</button>
  const Segmented = ({ options, value, onChange }: any) => (
    <div>
      {options.map((option: any) => {
        const current = typeof option === 'object' ? option : { label: option, value: option }
        return (
          <button key={current.value} data-active={value === current.value} onClick={() => onChange?.(current.value)}>
            {current.label}
          </button>
        )
      })}
    </div>
  )
  const Calendar = ({ onSelect }: any) => <button data-testid="calendar-select" onClick={() => onSelect?.({ format: () => '2026-06-01' })}>calendar</button>
  const List = ({ dataSource = [], renderItem, locale }: any) => (
    <div>
      {dataSource.length === 0 ? locale?.emptyText : dataSource.map((item: any, index: number) => <div key={index}>{renderItem(item)}</div>)}
    </div>
  )
  List.Item = passthrough
  const Timeline = ({ items = [] }: any) => <div>{items.map((item: any, index: number) => <div key={index}>{item.children}</div>)}</div>
  const Space = passthrough
  const Tag = ({ children }: any) => <span>{children}</span>
  const Empty = ({ description }: any) => <div>{description}</div>
  const Alert = ({ message }: any) => <div>{message}</div>
  const Typography = {
    Text: ({ children }: any) => <span>{children}</span>,
    Paragraph: ({ children }: any) => <p>{children}</p>,
  }
  const DatePicker = {
    RangePicker: () => <div>range</div>,
  }
  return {
    Button,
    Calendar,
    DatePicker,
    Empty,
    List,
    Segmented,
    Space,
    Tag,
    Timeline,
    Alert,
    Typography,
    message: {
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
    },
  }
})

describe('PlansPage workbench', () => {
  let container: HTMLDivElement | null = null
  let root: ReturnType<typeof createRoot> | null = null

  afterEach(() => {
    if (root) {
      act(() => {
        root?.unmount()
      })
      root = null
    }
    if (container) {
      container.remove()
      container = null
    }
    vi.restoreAllMocks()
  })

  it('renders a document-style plan editor instead of a modal input flow', async () => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)

    await act(async () => {
      root!.render(
        <MemoryRouter initialEntries={['/plans?date=2026-06-02']}>
          <Routes>
            <Route path="/plans" element={<PlansPage />} />
          </Routes>
        </MemoryRouter>,
      )
    })

    expect(container.querySelector('.mnemox-plan-workbench')).not.toBeNull()
    expect(container.querySelector('.mnemox-doc-header')?.textContent).toContain('2026-06-02')
    expect(container.querySelector('[data-testid="markdown-editor"]')?.textContent).toContain('修计划页')
    expect(container.textContent).toContain('当天任务')
    expect(container.textContent).toContain('修番茄钟')
    expect(container.querySelector('.ant-modal')).toBeNull()
  })
})
