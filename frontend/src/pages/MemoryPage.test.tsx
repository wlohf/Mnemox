import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryPage } from './MemoryPage'

const memoryMocks = vi.hoisted(() => ({
  correctMemory: vi.fn(),
  deleteMemory: vi.fn(),
  listMemoryConflicts: vi.fn(),
  listMemoryDeclarations: vi.fn(),
  listMemories: vi.fn(),
  reviewMemoryCandidate: vi.fn(),
  updateMemory: vi.fn(),
}))

vi.mock('../services/memoryApi', () => memoryMocks)
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('@ant-design/icons', () => ({
  ArrowLeftOutlined: () => null,
  DeleteOutlined: () => null,
  EditOutlined: () => null,
}))

vi.mock('antd', () => {
  const Wrapper = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>
  const Layout = Object.assign(Wrapper, { Header: Wrapper, Content: Wrapper })
  const Button = ({ children, onClick, disabled }: {
    children?: React.ReactNode
    onClick?: () => void
    disabled?: boolean
  }) => <button disabled={disabled} onClick={onClick}>{children}</button>
  const Card = ({ children, title }: { children?: React.ReactNode; title?: React.ReactNode }) => (
    <section><div>{title}</div>{children}</section>
  )
  const Item = ({ children, actions }: { children?: React.ReactNode; actions?: React.ReactNode[] }) => (
    <article>{children}{actions}</article>
  )
  const ItemMeta = ({ title, description }: { title?: React.ReactNode; description?: React.ReactNode }) => (
    <div><div>{title}</div><div>{description}</div></div>
  )
  const ListItem = Object.assign(Item, { Meta: ItemMeta })
  const List = Object.assign(
    <T,>({ dataSource = [], renderItem }: { dataSource?: T[]; renderItem: (item: T) => React.ReactNode }) => (
      <div>{dataSource.map((item, index) => <div key={index}>{renderItem(item)}</div>)}</div>
    ),
    { Item: ListItem },
  )
  const ModalBase = ({ open, children, title }: {
    open?: boolean
    children?: React.ReactNode
    title?: React.ReactNode
  }) => open ? <section><div>{title}</div>{children}</section> : null
  const Modal = Object.assign(ModalBase, { confirm: vi.fn() })
  const InputBase = ({ value, onChange, type }: {
    value?: string
    onChange?: (event: React.ChangeEvent<HTMLInputElement>) => void
    type?: string
  }) => <input type={type} value={value} onChange={onChange} />
  const Input = Object.assign(InputBase, {
    TextArea: ({ value, onChange }: {
      value?: string
      onChange?: (event: React.ChangeEvent<HTMLTextAreaElement>) => void
    }) => <textarea value={value} onChange={onChange} />,
  })
  return {
    Layout,
    Card,
    Button,
    List,
    Space: Wrapper,
    Tag: Wrapper,
    Modal,
    Input,
    InputNumber: () => <input type="number" />,
    Checkbox: () => <input type="checkbox" />,
    message: { success: vi.fn(), error: vi.fn() },
  }
})

const currentDeclaration = {
  id: 11,
  memory_id: 1,
  subject: 'user:1',
  predicate: 'goal',
  fact_key: 'learning_goal',
  value: '本周重点学习向量检索',
  valid_from: '2026-08-23T09:00:00',
  valid_to: null,
  observed_at: '2026-08-23T09:00:00',
  confidence: 0.9,
  review_status: 'confirmed',
  source_event_id: 5,
  source_type: 'learning_event',
  source_id: '5',
  evidence: [],
  created_by: 'agent',
  model_version: 'v1',
  supersedes_id: null,
  conflicts_with_id: null,
  resolution_reason: null,
  created_at: '2026-08-23T09:00:00',
}

describe('MemoryPage temporal fact review', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    vi.clearAllMocks()
    memoryMocks.listMemories.mockResolvedValue([{
      id: 1,
      memory_key: 'learning_goal',
      memory_value: currentDeclaration.value,
      category: 'goal',
      confidence: 0.9,
      status: 'active',
      review_status: 'confirmed',
    }, {
      id: 2,
      memory_key: 'learning_goal',
      memory_value: '本周重点学习工具调用',
      category: 'goal',
      confidence: 0.8,
      status: 'staged',
      review_status: 'staged',
      conflicts_with_id: 11,
    }])
    memoryMocks.listMemoryConflicts.mockResolvedValue([{
      fact_key: 'learning_goal',
      current_memory_id: 1,
      candidate_memory_id: 2,
      current: currentDeclaration,
      candidate: { ...currentDeclaration, id: 12, memory_id: 2, value: '本周重点学习工具调用', review_status: 'staged', conflicts_with_id: 11 },
    }])
    memoryMocks.listMemoryDeclarations.mockResolvedValue([currentDeclaration])
    memoryMocks.reviewMemoryCandidate.mockResolvedValue({ id: 2, review_status: 'confirmed' })
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(async () => {
    await act(async () => root.unmount())
    container.remove()
  })

  it('shows current and conflicting facts and confirms the user-selected replacement', async () => {
    await act(async () => root.render(<MemoryPage />))

    expect(container.textContent).toContain('需要你确认的事实冲突')
    expect(container.textContent).toContain('本周重点学习向量检索')
    expect(container.textContent).toContain('本周重点学习工具调用')
    expect(container.textContent).toContain('与当前事实冲突')

    const confirmButton = Array.from(container.querySelectorAll('button'))
      .find((button) => button.textContent === '采用新事实')
    expect(confirmButton).toBeDefined()
    await act(async () => confirmButton?.click())

    expect(memoryMocks.reviewMemoryCandidate).toHaveBeenCalledWith(2, 'confirm', true)
  })

  it('shows the provenance and replacement reason for a selected fact', async () => {
    memoryMocks.listMemoryDeclarations.mockResolvedValue([{
      ...currentDeclaration,
      review_status: 'superseded',
      valid_to: '2026-08-23T10:00:00',
      resolution_reason: '用户确认了新的学习目标',
    }])
    await act(async () => root.render(<MemoryPage />))

    const historyButton = Array.from(container.querySelectorAll('button'))
      .find((button) => button.textContent === '查看依据')
    expect(historyButton).toBeDefined()
    await act(async () => historyButton?.click())

    expect(memoryMocks.listMemoryDeclarations).toHaveBeenCalledWith(1)
    expect(container.textContent).toContain('已被新事实替代')
    expect(container.textContent).toContain('用户确认了新的学习目标')
  })
})
