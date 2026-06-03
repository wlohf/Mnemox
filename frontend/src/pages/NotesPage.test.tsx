import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { NotesPage } from './NotesPage'

const mockNotes = [
  {
    _localId: '1',
    _serverId: null,
    _syncStatus: 'synced',
    title: '科研记录',
    content: '# 科研记录\n\n今天整理实验。',
    note_type: 'general',
    material_id: null,
    chapter_id: null,
    tags: ['科研'],
    links: [],
    created_at: null,
    updated_at: '2026-06-02T00:00:00.000Z',
  },
]

vi.mock('../components/PageShell', () => ({
  PageShell: ({ children, title, rightExtra }: { children: React.ReactNode; title: React.ReactNode; rightExtra?: React.ReactNode }) => (
    <div>
      <div>{title}</div>
      <div>{rightExtra}</div>
      {children}
    </div>
  ),
}))

vi.mock('../components/MarkdownLiveEditor', () => ({
  MarkdownLiveEditor: ({ value }: { value: string }) => <div data-testid="markdown-editor">{value}</div>,
}))

vi.mock('../hooks/useOfflineNotes', () => ({
  useOfflineNotes: vi.fn(() => ({
    notes: mockNotes,
    createNote: vi.fn(),
    updateNote: vi.fn(),
    deleteNote: vi.fn(),
  })),
}))

vi.mock('../services/imageApi', () => ({
  uploadImage: vi.fn(),
}))

vi.mock('../services/obsidianImportApi', () => ({
  importObsidianNote: vi.fn(),
}))

vi.mock('../services/noteApi', () => ({
  assistNoteWithAI: vi.fn(),
}))

vi.mock('antd', async () => {
  const Button = ({ children, onClick, ...props }: any) => <button onClick={onClick} {...props}>{children}</button>
  const Input = ({ value = '', onChange, ...props }: any) => <input value={value} onChange={onChange} {...props} />
  Input.Search = ({ value = '', onChange, onSearch, ...props }: any) => (
    <input
      value={value}
      onChange={onChange}
      onKeyDown={(event: any) => {
        if (event.key === 'Enter') onSearch?.(event.currentTarget.value)
      }}
      {...props}
    />
  )
  Input.TextArea = ({ value = '', onChange, ...props }: any) => <textarea value={value} onChange={onChange} {...props} />
  const Modal = ({ open, children }: any) => open ? <div className="ant-modal">{children}</div> : null
  Modal.confirm = vi.fn()
  const Select = () => <div />
  const Space = ({ children }: any) => <div>{children}</div>
  const Tag = ({ children }: any) => <span>{children}</span>
  const Tabs = ({ items = [] }: any) => <div>{items.map((item: any) => <div key={item.key}>{item.children}</div>)}</div>
  const Typography = {
    Text: ({ children }: any) => <span>{children}</span>,
  }
  const Upload = ({ children }: any) => <div>{children}</div>
  const Empty = ({ description }: any) => <div>{description}</div>
  return {
    Button,
    Empty,
    Input,
    Modal,
    Select,
    Space,
    Tag,
    Tabs,
    Typography,
    Upload,
    message: {
      success: vi.fn(),
      error: vi.fn(),
      warning: vi.fn(),
    },
  }
})

describe('NotesPage folder switching', () => {
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

  it('clears the editor when switching to an empty folder', async () => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)

    await act(async () => {
      root!.render(
        <MemoryRouter>
          <NotesPage />
        </MemoryRouter>,
      )
    })

    expect(container.querySelector('[data-testid="markdown-editor"]')?.textContent).toContain('今天整理实验')

    const untaggedButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes('未分类'))
    expect(untaggedButton).toBeDefined()

    await act(async () => {
      untaggedButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(container.querySelector('[data-testid="markdown-editor"]')).toBeNull()
    expect(container.textContent).toContain('选择或新建一篇笔记')
  })
})
