import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeHighlight from 'rehype-highlight'
import rehypeKatex from 'rehype-katex'
import { useNavigate } from 'react-router-dom'
import { Button, Empty, Input, Modal, Segmented, Select, Space, Tag, Tabs, Typography, Upload, message } from 'antd'
import {
  CopyOutlined,
  DeleteOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  ImportOutlined,
  PictureOutlined,
  PlusOutlined,
  RobotOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { useOfflineNotes, type OfflineNoteItem } from '../hooks/useOfflineNotes'
import { uploadImage } from '../services/imageApi'
import { importObsidianNote } from '../services/obsidianImportApi'
import {
  askAgentAboutNote,
  assistNoteWithAI,
  draftNoteReviewPrompt,
  draftTaskFromNoteSelection,
  type AskAgentFromNoteResult,
  type NoteAIAssistAction,
  type NoteActionDraftResult,
  type NoteLink,
} from '../services/noteApi'
import { MarkdownLiveEditor, type MarkdownLiveEditorHandle, type MarkdownLiveEditorImageResult } from '../components/MarkdownLiveEditor'
import { PageShell } from '../components/PageShell'
import '../components/ChatMessageBubble.css'

const { Text } = Typography

const NOTE_AI_ACTIONS: Array<{ key: NoteAIAssistAction; label: string; description: string }> = [
  { key: 'continue', label: '续写', description: '根据当前内容继续补充例子、解释或小结' },
  { key: 'review', label: '检查遗漏', description: '检查是否遗漏重点并给出复习问题' },
  { key: 'restructure', label: '整理结构', description: '重组为更清晰的 Markdown 笔记' },
  { key: 'summarize', label: '摘要', description: '提炼摘要、关键词和三句话总结' },
]

type FolderKey = 'all' | 'untagged' | 'pending' | `tag:${string}`
type EditorMode = 'edit' | 'preview' | 'split'

const NOTE_DRAFT_PREFIX = 'mnemox_note_draft:'

function getNoteExcerpt(content: string) {
  const line = content
    .split('\n')
    .map((item) => item.trim())
    .find((item) => item && !item.startsWith('#'))
  return line?.replace(/^[-*]\s+/, '').replace(/\[( |x)\]\s*/i, '') || '空白笔记'
}

function getWordCount(content: string) {
  const compact = content.replace(/\s/g, '')
  return compact.length
}

function getFolderTitle(folderKey: FolderKey) {
  if (folderKey === 'all') return '全部笔记'
  if (folderKey === 'untagged') return '未分类'
  if (folderKey === 'pending') return '待同步'
  return folderKey.replace(/^tag:/, '')
}

function getDraftKey(localId: string) {
  return `${NOTE_DRAFT_PREFIX}${localId}`
}

function parseNumericId(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const parsed = Number.parseInt(trimmed, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

function formatLinks(links: NoteLink[]) {
  return (links || [])
    .map((link) => `${link.link_type}:${link.link_id}${link.label ? ` ${link.label}` : ''}`)
    .join('\n')
}

function parseLinks(text: string): NoteLink[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map<NoteLink | null>((line) => {
      const [head, ...labelParts] = line.split(/\s+/)
      const [type, idText] = head.includes(':') ? head.split(':', 2) : ['material', head]
      const parsedId = Number.parseInt(idText, 10)
      if (!type || !Number.isFinite(parsedId) || parsedId <= 0) return null
      return {
        link_type: type,
        link_id: parsedId,
        label: labelParts.join(' ') || null,
      }
    })
    .filter((item): item is NoteLink => item !== null)
}

function renderMarkdown(content: string) {
  return (
    <div className="chat-markdown mnemox-notes-preview">
      {content.trim() ? (
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeHighlight, rehypeKatex]}
          skipHtml
        >
          {content}
        </ReactMarkdown>
      ) : (
        <Text type="secondary">预览会显示在这里。</Text>
      )}
    </div>
  )
}

function hasNoteChanged(current: OfflineNoteItem, latest: OfflineNoteItem) {
  return (
    current._serverId !== latest._serverId ||
    current._syncStatus !== latest._syncStatus ||
    current.title !== latest.title ||
    current.content !== latest.content ||
    current.note_type !== latest.note_type ||
    current.material_id !== latest.material_id ||
    current.chapter_id !== latest.chapter_id ||
    current.updated_at !== latest.updated_at ||
    JSON.stringify(current.tags || []) !== JSON.stringify(latest.tags || []) ||
    JSON.stringify(current.links || []) !== JSON.stringify(latest.links || [])
  )
}

function isAskAgentPreview(result: NoteActionDraftResult | AskAgentFromNoteResult): result is AskAgentFromNoteResult {
  return Boolean((result as AskAgentFromNoteResult).preview?.agent_prompt_preview)
}

export function NotesPage() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [folderKey, setFolderKey] = useState<FolderKey>('all')
  const { notes, createNote, updateNote, deleteNote } = useOfflineNotes()

  const [active, setActive] = useState<OfflineNoteItem | null>(null)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [tagsText, setTagsText] = useState('')
  const [materialIdText, setMaterialIdText] = useState('')
  const [chapterIdText, setChapterIdText] = useState('')
  const [linksText, setLinksText] = useState('')
  const [editorMode, setEditorMode] = useState<EditorMode>('split')
  const [draftStatus, setDraftStatus] = useState<'clean' | 'dirty' | 'saved' | 'restored' | 'saving'>('clean')
  const [draftSavedAt, setDraftSavedAt] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const editorRef = useRef<MarkdownLiveEditorHandle | null>(null)

  const [aiOpen, setAiOpen] = useState(false)
  const [aiAction, setAiAction] = useState<NoteAIAssistAction>('continue')
  const [aiInstruction, setAiInstruction] = useState('')
  const [aiSelectedText, setAiSelectedText] = useState('')
  const [aiSuggestion, setAiSuggestion] = useState('')
  const [aiPreviewMode, setAiPreviewMode] = useState<'preview' | 'edit'>('preview')
  const [aiLoading, setAiLoading] = useState(false)

  const [importOpen, setImportOpen] = useState(false)
  const [importMdFiles, setImportMdFiles] = useState<File[]>([])
  const [importAttachments, setImportAttachments] = useState<File[]>([])
  const [importing, setImporting] = useState(false)
  const [noteActionLoading, setNoteActionLoading] = useState<'review' | 'task' | 'ask' | null>(null)
  const [noteActionResult, setNoteActionResult] = useState<NoteActionDraftResult | AskAgentFromNoteResult | null>(null)
  const [noteActionOpen, setNoteActionOpen] = useState(false)
  const [agentQuestion, setAgentQuestion] = useState('')

  const tagStats = useMemo(() => {
    const counts = new Map<string, number>()
    for (const note of notes) {
      for (const tag of note.tags || []) {
        counts.set(tag, (counts.get(tag) || 0) + 1)
      }
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'))
      .map(([tag, count]) => ({ tag, count }))
  }, [notes])

  const visibleNotes = useMemo(() => {
    const query = q.trim().toLowerCase()
    return notes.filter((note) => {
      const tags = note.tags || []
      if (folderKey === 'untagged' && tags.length > 0) return false
      if (folderKey === 'pending' && note._syncStatus === 'synced') return false
      if (folderKey.startsWith('tag:') && !tags.includes(folderKey.slice(4))) return false
      if (!query) return true
      return note.title.toLowerCase().includes(query) || note.content.toLowerCase().includes(query)
    })
  }, [folderKey, notes, q])

  const activeLatest = useMemo(
    () => active ? notes.find((note) => note._localId === active._localId) || null : null,
    [active?._localId, notes],
  )

  const openNote = (note: OfflineNoteItem) => {
    setActive(note)
    let nextTitle = note.title || ''
    let nextContent = note.content || ''
    let restored = false
    const draftText = localStorage.getItem(getDraftKey(note._localId))
    if (draftText) {
      try {
        const draft = JSON.parse(draftText) as { title?: string; content?: string; tagsText?: string; materialIdText?: string; chapterIdText?: string; linksText?: string; savedAt?: string }
        nextTitle = draft.title ?? nextTitle
        nextContent = draft.content ?? nextContent
        setTagsText(draft.tagsText ?? (note.tags || []).join(', '))
        setMaterialIdText(draft.materialIdText ?? (note.material_id ? String(note.material_id) : ''))
        setChapterIdText(draft.chapterIdText ?? (note.chapter_id ? String(note.chapter_id) : ''))
        setLinksText(draft.linksText ?? formatLinks(note.links || []))
        setDraftSavedAt(draft.savedAt ?? null)
        restored = true
      } catch {
        localStorage.removeItem(getDraftKey(note._localId))
      }
    }
    if (!restored) {
      setTagsText((note.tags || []).join(', '))
      setMaterialIdText(note.material_id ? String(note.material_id) : '')
      setChapterIdText(note.chapter_id ? String(note.chapter_id) : '')
      setLinksText(formatLinks(note.links || []))
      setDraftSavedAt(null)
    }
    setTitle(nextTitle)
    setContent(nextContent)
    setDraftStatus(restored ? 'restored' : 'clean')
  }

  const clearActive = () => {
    setActive(null)
    setTitle('')
    setContent('')
    setTagsText('')
    setMaterialIdText('')
    setChapterIdText('')
    setLinksText('')
    setDraftStatus('clean')
    setDraftSavedAt(null)
  }

  useEffect(() => {
    if (visibleNotes.length === 0) {
      clearActive()
      return
    }
    if (!active) {
      openNote(visibleNotes[0])
      return
    }
    if (!visibleNotes.some((note) => note._localId === active._localId)) {
      openNote(visibleNotes[0])
    }
  }, [active?._localId, notes.length, visibleNotes.length, folderKey, q])

  useEffect(() => {
    if (!active || !activeLatest || !hasNoteChanged(active, activeLatest)) return
    setActive(activeLatest)
    if (draftStatus === 'clean') {
      setTitle(activeLatest.title || '')
      setContent(activeLatest.content || '')
      setTagsText((activeLatest.tags || []).join(', '))
      setMaterialIdText(activeLatest.material_id ? String(activeLatest.material_id) : '')
      setChapterIdText(activeLatest.chapter_id ? String(activeLatest.chapter_id) : '')
      setLinksText(formatLinks(activeLatest.links || []))
    }
  }, [active, activeLatest, draftStatus])

  useEffect(() => {
    if (!active) return
    const activeTagsText = (active.tags || []).join(', ')
    const activeMaterialText = active.material_id ? String(active.material_id) : ''
    const activeChapterText = active.chapter_id ? String(active.chapter_id) : ''
    const activeLinksText = formatLinks(active.links || [])
    const dirty =
      title !== (active.title || '') ||
      content !== (active.content || '') ||
      tagsText !== activeTagsText ||
      materialIdText !== activeMaterialText ||
      chapterIdText !== activeChapterText ||
      linksText !== activeLinksText
    if (!dirty) {
      setDraftStatus((prev) => prev === 'restored' ? prev : 'clean')
      return
    }
    setDraftStatus('dirty')
    const timeoutId = window.setTimeout(() => {
      const savedAt = new Date().toISOString()
      localStorage.setItem(getDraftKey(active._localId), JSON.stringify({
        title,
        content,
        tagsText,
        materialIdText,
        chapterIdText,
        linksText,
        savedAt,
      }))
      setDraftSavedAt(savedAt)
      setDraftStatus('saved')
    }, 700)
    return () => window.clearTimeout(timeoutId)
  }, [active, title, content, tagsText, materialIdText, chapterIdText, linksText])

  const doUploadImage = async (file: File) => {
    setUploading(true)
    const result = await uploadImage(file)
    setUploading(false)
    if (!result) {
      message.error('图片上传失败')
      return null
    }
    return result
  }

  const handleEditorImageUpload = async (file: File): Promise<MarkdownLiveEditorImageResult | null> => {
    const result = await doUploadImage(file)
    if (!result) return null
    return {
      url: result.url,
      markdown: result.markdown,
      alt: result.original_name || result.filename,
    }
  }

  const handleImageUpload = async (file: File) => {
    const result = await doUploadImage(file)
    if (!result) return
    const markdown = result.markdown || `![${result.original_name || 'image'}](${result.url})`
    const insertText = markdown.endsWith('\n') ? markdown : `${markdown}\n`
    if (!editorRef.current) {
      setContent((prev) => `${prev}${insertText}`)
      message.success('图片已插入')
      return
    }
    editorRef.current.insertText(insertText)
    message.success('图片已插入')
  }

  const handleObsidianImport = async () => {
    if (importMdFiles.length === 0) {
      message.warning('请选择 Markdown 文件，可一次选择多个')
      return
    }
    setImporting(true)
    let successCount = 0
    let warningCount = 0
    let lastCreated: OfflineNoteItem | null = null
    try {
      for (const mdFile of importMdFiles) {
        const result = await importObsidianNote(mdFile, importAttachments)
        if (!result) continue
        warningCount += result.warnings.length
        const created = await createNote({
          title: result.title,
          content: result.content,
          note_type: 'general',
          tags: [],
        })
        lastCreated = created
        successCount += 1
      }
    } finally {
      setImporting(false)
    }

    if (successCount === 0) {
      message.error('导入失败')
      return
    }

    if (warningCount > 0) {
      message.warning(`导入完成，但有 ${warningCount} 个警告`)
    }
    message.success(`已导入 ${successCount} 篇笔记`)
    setImportOpen(false)
    setImportMdFiles([])
    setImportAttachments([])
    if (lastCreated) openNote(lastCreated)
  }

  const handleCreate = async () => {
    const selectedTag = folderKey.startsWith('tag:') ? folderKey.slice(4) : ''
    const created = await createNote({
      title: '新笔记',
      content: '',
      note_type: 'general',
      tags: selectedTag ? [selectedTag] : [],
    })
    message.success('已创建笔记')
    openNote(created)
  }

  const handleSave = async () => {
    if (!active) {
      message.warning('请先选择笔记')
      return
    }
    const tags = tagsText
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
      .slice(0, 12)
    const material_id = parseNumericId(materialIdText)
    const chapter_id = parseNumericId(chapterIdText)
    const links = parseLinks(linksText)
    setSaving(true)
    const saved = await updateNote(active._localId, {
      title,
      content,
      tags,
      material_id,
      chapter_id,
      links,
    })
    setSaving(false)
    if (!saved) {
      message.error('保存失败')
      return
    }
    localStorage.removeItem(getDraftKey(active._localId))
    setDraftStatus('clean')
    setDraftSavedAt(null)
    message.success('已保存')
    openNote(saved)
  }

  const openAIAssist = () => {
    if (!active) {
      message.warning('请先选择笔记')
      return
    }
    if (!active._serverId || active._syncStatus !== 'synced') {
      message.warning('请先保存并同步笔记后再使用 AI 辅助')
      return
    }
    const latestEditorContent = editorRef.current?.getMarkdown() ?? content
    if (latestEditorContent !== active.content) {
      message.warning('当前编辑区有未保存修改，请先保存后再使用 AI 辅助')
      return
    }
    setAiSelectedText((editorRef.current?.getSelectedText() || '').trim().slice(0, 3000))
    setAiOpen(true)
    setAiSuggestion('')
    setAiPreviewMode('preview')
  }

  const refreshAISelectedText = () => {
    const selectedText = (editorRef.current?.getSelectedText() || aiSelectedText).trim().slice(0, 3000)
    setAiSelectedText(selectedText)
    return selectedText
  }

  const handleAIGenerate = async () => {
    if (!active?._serverId) {
      message.warning('请先保存并同步笔记后再使用 AI 辅助')
      return
    }
    if (!content.trim()) {
      message.warning('当前笔记内容为空，先写一点内容再让 AI 辅助吧')
      return
    }
    const latestEditorContent = editorRef.current?.getMarkdown() ?? content
    if (latestEditorContent !== active.content) {
      message.warning('当前编辑区有未保存修改，请先保存后再生成 AI 建议')
      return
    }
    const selectedText = refreshAISelectedText()
    setAiLoading(true)
    const result = await assistNoteWithAI(active._serverId, {
      action: aiAction,
      instruction: aiInstruction.trim() || undefined,
      selected_text: selectedText || undefined,
    })
    setAiLoading(false)
    if (!result || !result.ok) {
      message.error(result?.message || 'AI 辅助暂不可用，请检查 AI 设置或稍后重试')
      return
    }
    setAiSuggestion(result.suggestion)
    setAiPreviewMode('preview')
    message.success(result.message || '已生成 AI 建议')
  }

  const appendAISuggestion = () => {
    if (!aiSuggestion.trim()) return
    setContent((prev) => `${prev.trimEnd()}\n\n${aiSuggestion.trim()}\n`)
    message.success('已追加到笔记末尾，请确认后保存')
  }

  const replaceWithAISuggestion = () => {
    if (!aiSuggestion.trim()) return
    Modal.confirm({
      title: '替换当前笔记内容？',
      content: 'AI 建议会替换编辑区全文，但不会自动保存；确认无误后请点击保存。',
      okText: '替换',
      cancelText: '取消',
      onOk: () => {
        setContent(aiSuggestion.trim())
        message.success('已替换编辑区内容，请确认后保存')
      },
    })
  }

  const copyAISuggestion = async () => {
    if (!aiSuggestion.trim()) return
    try {
      await navigator.clipboard.writeText(aiSuggestion)
      message.success('已复制 AI 建议')
    } catch {
      message.error('复制失败，请手动复制')
    }
  }

  const handleDelete = () => {
    if (!active) return
    Modal.confirm({
      title: '删除笔记',
      content: '确定删除这条笔记吗？',
      okType: 'danger',
      onOk: async () => {
        const ok = await deleteNote(active._localId)
        if (!ok) {
          message.error('删除失败')
          return
        }
        message.success('已删除')
        clearActive()
      },
    })
  }

  const requireSyncedServerNote = () => {
    if (!active) {
      message.warning('请先选择笔记')
      return null
    }
    if (!active._serverId || active._syncStatus !== 'synced') {
      message.warning('请先保存并同步笔记后再使用 Agent 动作')
      return null
    }
    return active._serverId
  }

  const openNoteActionResult = (result: NoteActionDraftResult | AskAgentFromNoteResult | null, fallback: string) => {
    if (!result) {
      message.error(fallback)
      return
    }
    setNoteActionResult(result)
    setNoteActionOpen(true)
  }

  const draftReviewPrompt = async () => {
    const serverId = requireSyncedServerNote()
    if (!serverId) return
    setNoteActionLoading('review')
    const result = await draftNoteReviewPrompt(serverId)
    setNoteActionLoading(null)
    openNoteActionResult(result, '生成复习提示草案失败')
  }

  const draftTaskFromSelection = async () => {
    const serverId = requireSyncedServerNote()
    if (!serverId) return
    const selectedText = (editorRef.current?.getSelectedText() || '').trim().slice(0, 3000)
    if (!selectedText) {
      message.warning('请先在笔记中选择一段内容')
      return
    }
    setNoteActionLoading('task')
    const result = await draftTaskFromNoteSelection(serverId, { selected_text: selectedText })
    setNoteActionLoading(null)
    openNoteActionResult(result, '生成任务草案失败')
  }

  const askAgentCurrentNote = async () => {
    const serverId = requireSyncedServerNote()
    if (!serverId) return
    const selectedText = (editorRef.current?.getSelectedText() || '').trim().slice(0, 3000)
    setNoteActionLoading('ask')
    const result = await askAgentAboutNote(serverId, {
      question: agentQuestion.trim() || undefined,
      selected_text: selectedText || undefined,
    })
    setNoteActionLoading(null)
    openNoteActionResult(result, '询问 Agent 失败')
  }

  const draftStatusLabel = (() => {
    if (!active) return '未选择'
    if (saving) return '正在写入同步队列'
    if (draftStatus === 'dirty') return '本地草稿待保存'
    if (draftStatus === 'saved') return draftSavedAt ? `本地草稿 ${dayjs(draftSavedAt).format('HH:mm:ss')}` : '本地草稿已保存'
    if (draftStatus === 'restored') return '已恢复本地草稿'
    if (active._syncStatus !== 'synced') return '等待同步'
    return '已同步'
  })()

  const folderRows: Array<{ key: FolderKey; label: string; count: number }> = [
    { key: 'all', label: '全部笔记', count: notes.length },
    { key: 'untagged', label: '未分类', count: notes.filter((note) => (note.tags || []).length === 0).length },
    { key: 'pending', label: '待同步', count: notes.filter((note) => note._syncStatus !== 'synced').length },
    ...tagStats.map((item) => ({ key: `tag:${item.tag}` as FolderKey, label: item.tag, count: item.count })),
  ]

  return (
    <PageShell
      title="笔记系统"
      onBack={() => navigate('/')}
      rightExtra={(
        <Space wrap>
          <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入 Obsidian</Button>
          <Button icon={<PlusOutlined />} onClick={handleCreate}>新建笔记</Button>
          <Button icon={<RobotOutlined />} onClick={openAIAssist} disabled={!active}>AI 辅助</Button>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave} disabled={!active}>保存</Button>
          <Button danger icon={<DeleteOutlined />} onClick={handleDelete} disabled={!active}>删除</Button>
        </Space>
      )}
      maxWidth={1580}
    >
      <div className="mnemox-notes-workbench">
        <aside className="mnemox-notes-folder-pane">
          <div className="mnemox-panel-heading">
            <span>Obsidian</span>
            <Tag>{notes.length}</Tag>
          </div>
          <div className="mnemox-folder-list">
            {folderRows.map((folder) => (
              <button
                key={folder.key}
                type="button"
                className={`mnemox-folder-item${folderKey === folder.key ? ' is-active' : ''}`}
                onClick={() => setFolderKey(folder.key)}
              >
                <FolderOpenOutlined />
                <span>{folder.label}</span>
                <small>{folder.count}</small>
              </button>
            ))}
          </div>
        </aside>

        <aside className="mnemox-notes-file-pane">
          <div className="mnemox-panel-heading">
            <span>{getFolderTitle(folderKey)}</span>
            <Tag>{visibleNotes.length}</Tag>
          </div>
          <Input.Search
            allowClear
            className="mnemox-notes-search"
            placeholder="搜索标题或正文"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            onSearch={(value) => setQ(value.trim())}
          />
          <div className="mnemox-file-list">
            {visibleNotes.length === 0 ? (
              <Empty description="暂无笔记" />
            ) : (
              visibleNotes.map((note) => {
                const selected = active?._localId === note._localId
                return (
                  <button
                    key={note._localId}
                    type="button"
                    className={`mnemox-note-file${selected ? ' is-active' : ''}`}
                    onClick={() => openNote(note)}
                  >
                    <span className="mnemox-note-file-title">
                      <FileTextOutlined />
                      <span>{note.title || '无标题'}</span>
                    </span>
                    <span className="mnemox-note-file-preview">{getNoteExcerpt(note.content)}</span>
                    <span className="mnemox-note-file-meta">
                      <span>{note.updated_at ? dayjs(note.updated_at).format('MM-DD HH:mm') : '-'}</span>
                      {note._syncStatus !== 'synced' && <Tag color="orange">未同步</Tag>}
                    </span>
                  </button>
                )
              })
            )}
          </div>
        </aside>

        <main className="mnemox-notes-document">
          {active ? (
            <>
              <div className="mnemox-doc-breadcrumb">笔记 / {getFolderTitle(folderKey)} / {active.title || '无标题'}</div>
              <Input
                className="mnemox-note-title-input"
                placeholder="笔记标题"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
              <Input
                className="mnemox-note-tags-input"
                placeholder="标签，用逗号分隔"
                value={tagsText}
                onChange={(event) => setTagsText(event.target.value)}
              />
              <div className="mnemox-doc-toolbar">
                <Space size={6} wrap>
                  {uploading && <Tag color="blue">上传中</Tag>}
                  <Segmented
                    size="small"
                    value={editorMode}
                    onChange={(value) => setEditorMode(value as EditorMode)}
                    options={[
                      { label: '编辑', value: 'edit' },
                      { label: '预览', value: 'preview' },
                      { label: '分屏', value: 'split' },
                    ]}
                  />
                  <Button size="small" icon={<RobotOutlined />} onClick={openAIAssist} disabled={!active}>AI 辅助</Button>
                  <Upload
                    accept="image/png,image/jpeg,image/gif,image/webp,image/bmp"
                    showUploadList={false}
                    beforeUpload={(file) => {
                      void handleImageUpload(file)
                      return false
                    }}
                  >
                    <Button size="small" icon={<PictureOutlined />}>插入图片</Button>
                  </Upload>
                  <Button size="small" type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存</Button>
                </Space>
                <Space size={6} wrap>
                  <Tag color={draftStatus === 'dirty' ? 'orange' : active._syncStatus === 'synced' ? 'green' : 'gold'}>{draftStatusLabel}</Tag>
                  {(tagsText.split(',').map((item) => item.trim()).filter(Boolean)).map((tag) => (
                    <Tag key={tag}>{tag}</Tag>
                  ))}
                  <Tag>{getWordCount(content)} 字</Tag>
                </Space>
              </div>
              <div className={`mnemox-notes-editor-shell mode-${editorMode}`}>
                {editorMode !== 'preview' && (
                  <MarkdownLiveEditor
                    ref={editorRef}
                    value={content}
                    onChange={setContent}
                    height="calc(100vh - 360px)"
                    className="mnemox-notes-editor"
                    onUploadImage={handleEditorImageUpload}
                    placeholder="支持 Markdown；可直接输入、粘贴图片、拖拽图片或点击工具栏图片按钮..."
                  />
                )}
                {editorMode !== 'edit' && renderMarkdown(content)}
              </div>
            </>
          ) : (
            <div className="mnemox-notes-empty">
              <Empty description="选择或新建一篇笔记" />
            </div>
          )}
        </main>

        <aside className="mnemox-notes-relation-pane">
          <div className="mnemox-panel-heading">
            <span>关系与 Agent</span>
            {active?._serverId ? <Tag color="green">#{active._serverId}</Tag> : <Tag>本地</Tag>}
          </div>
          {active ? (
            <div className="mnemox-note-relations">
              <label>
                <span>Goal / Material</span>
                <Input
                  size="small"
                  value={materialIdText}
                  onChange={(event) => setMaterialIdText(event.target.value)}
                  placeholder="material_id"
                />
              </label>
              <label>
                <span>Chapter</span>
                <Input
                  size="small"
                  value={chapterIdText}
                  onChange={(event) => setChapterIdText(event.target.value)}
                  placeholder="chapter_id"
                />
              </label>
              <label>
                <span>Links</span>
                <Input.TextArea
                  value={linksText}
                  onChange={(event) => setLinksText(event.target.value)}
                  placeholder="goal:1 期末目标&#10;task:8 复盘任务&#10;wrong_question:12 错题"
                  autoSize={{ minRows: 4, maxRows: 8 }}
                />
              </label>
              <div className="mnemox-note-relation-tags">
                {parseLinks(linksText).length === 0 ? (
                  <Text type="secondary">暂无显式关系</Text>
                ) : (
                  parseLinks(linksText).map((link) => (
                    <Tag key={`${link.link_type}-${link.link_id}`}>{link.link_type} #{link.link_id}</Tag>
                  ))
                )}
              </div>
              <div className="mnemox-note-agent-actions">
                <Button
                  size="small"
                  block
                  loading={noteActionLoading === 'review'}
                  onClick={() => void draftReviewPrompt()}
                >
                  转复习提示草案
                </Button>
                <Button
                  size="small"
                  block
                  loading={noteActionLoading === 'task'}
                  onClick={() => void draftTaskFromSelection()}
                >
                  从选区创建任务草案
                </Button>
                <Input.TextArea
                  value={agentQuestion}
                  onChange={(event) => setAgentQuestion(event.target.value)}
                  placeholder="问 Agent 当前笔记，例如：下一步该复习什么？"
                  autoSize={{ minRows: 2, maxRows: 4 }}
                />
                <Button
                  size="small"
                  type="primary"
                  block
                  icon={<RobotOutlined />}
                  loading={noteActionLoading === 'ask'}
                  onClick={() => void askAgentCurrentNote()}
                >
                  询问 Agent
                </Button>
              </div>
            </div>
          ) : (
            <div className="mnemox-pane-empty">选择笔记后显示关系和 Agent 动作</div>
          )}
        </aside>
      </div>

      <Modal
        title="AI 辅助笔记"
        open={aiOpen}
        onCancel={() => setAiOpen(false)}
        footer={null}
        width={860}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Text type="secondary">
            AI 只生成建议，不会自动覆盖笔记。确认满意后可以追加、替换编辑区或复制。
            {aiSelectedText ? ` 已检测到选中文本（${aiSelectedText.length} 字），本次会优先围绕选中部分处理。` : ' 如需局部处理，可先在编辑器中选中文本再打开 AI 辅助。'}
          </Text>
          <Select
            value={aiAction}
            onChange={(value) => {
              setAiAction(value)
              setAiSuggestion('')
              setAiPreviewMode('preview')
              refreshAISelectedText()
            }}
            options={NOTE_AI_ACTIONS.map((item) => ({
              value: item.key,
              label: `${item.label} · ${item.description}`,
            }))}
            style={{ width: '100%' }}
          />
          <Input.TextArea
            value={aiInstruction}
            onChange={(event) => setAiInstruction(event.target.value)}
            placeholder="补充要求（可选）：例如更偏考试重点、保持口语化、围绕某一段展开..."
            autoSize={{ minRows: 2, maxRows: 4 }}
            maxLength={500}
            showCount
          />
          <Space>
            <Button type="primary" icon={<RobotOutlined />} loading={aiLoading} onClick={handleAIGenerate}>
              生成建议
            </Button>
            <Button icon={<CopyOutlined />} onClick={copyAISuggestion} disabled={!aiSuggestion.trim()}>
              复制
            </Button>
            <Button onClick={appendAISuggestion} disabled={!aiSuggestion.trim()}>
              追加到文末
            </Button>
            <Button danger onClick={replaceWithAISuggestion} disabled={!aiSuggestion.trim()}>
              替换编辑区全文
            </Button>
          </Space>
          <Tabs
            activeKey={aiPreviewMode}
            onChange={(key) => setAiPreviewMode(key as 'preview' | 'edit')}
            items={[
              {
                key: 'preview',
                label: '预览',
                children: (
                  <div className="chat-markdown" style={{ minHeight: 260, maxHeight: 520, overflow: 'auto', border: '1px solid var(--border-light)', borderRadius: 8, padding: 16 }}>
                    {aiSuggestion.trim() ? (
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm, remarkMath]}
                        rehypePlugins={[rehypeHighlight, rehypeKatex]}
                        skipHtml
                      >
                        {aiSuggestion}
                      </ReactMarkdown>
                    ) : (
                      <Text type="secondary">AI 建议会显示在这里。生成后可切换到“编辑原文”进行微调。</Text>
                    )}
                  </div>
                ),
              },
              {
                key: 'edit',
                label: '编辑原文',
                children: (
                  <Input.TextArea
                    value={aiSuggestion}
                    onChange={(event) => setAiSuggestion(event.target.value)}
                    placeholder="AI 建议会显示在这里，你可以先编辑再追加/替换/复制。"
                    autoSize={{ minRows: 12, maxRows: 22 }}
                  />
                ),
              },
            ]}
          />
        </Space>
      </Modal>

      <Modal
        title="Agent 笔记动作"
        open={noteActionOpen}
        onCancel={() => setNoteActionOpen(false)}
        footer={[
          <Button key="close" type="primary" onClick={() => setNoteActionOpen(false)}>关闭</Button>,
        ]}
        width={720}
      >
        {noteActionResult ? (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            {'answer' in noteActionResult && noteActionResult.answer ? (
              <div className="chat-markdown mnemox-note-action-result">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeHighlight, rehypeKatex]}
                  skipHtml
                >
                  {noteActionResult.answer}
                </ReactMarkdown>
              </div>
            ) : isAskAgentPreview(noteActionResult) ? (
              <div className="mnemox-note-action-preview">
                <div>
                  <Text strong>问题</Text>
                  <p>{noteActionResult.preview?.question || '请解释这段笔记的重点，并给出下一步学习建议。'}</p>
                </div>
                {noteActionResult.preview?.source_note && (
                  <div>
                    <Text strong>证据笔记</Text>
                    <p>{noteActionResult.preview.source_note.title || '未命名笔记'}</p>
                    <Text type="secondary">{noteActionResult.preview.source_note.excerpt || '无摘录'}</Text>
                  </div>
                )}
                <div>
                  <Text strong>安全预览</Text>
                  <pre className="mnemox-note-action-json">{noteActionResult.preview?.agent_prompt_preview}</pre>
                </div>
              </div>
            ) : (
              <pre className="mnemox-note-action-json">{JSON.stringify(('draft' in noteActionResult && noteActionResult.draft) ? noteActionResult.draft : noteActionResult, null, 2)}</pre>
            )}
            {'requires_confirmation' in noteActionResult && noteActionResult.requires_confirmation && (
              <Text type="secondary">这是草案预览。需要你在对应流程中确认后才会写入任务、复习或笔记。</Text>
            )}
            {'sources' in noteActionResult && noteActionResult.sources && noteActionResult.sources.length > 0 && (
              <Space wrap>
                {noteActionResult.sources.slice(0, 6).map((source) => (
                  <Tag key={`${source.type}-${source.id}`}>{source.type || 'source'} {source.title || source.id}</Tag>
                ))}
              </Space>
            )}
          </Space>
        ) : (
          <Empty description="暂无动作结果" />
        )}
      </Modal>

      <Modal
        title="导入 Obsidian 笔记"
        open={importOpen}
        onCancel={() => { setImportOpen(false); setImportMdFiles([]); setImportAttachments([]) }}
        onOk={handleObsidianImport}
        confirmLoading={importing}
        okText="导入"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <div style={{ marginBottom: 6, fontWeight: 500 }}>Markdown 文件</div>
            <Upload
              accept=".md,.markdown"
              multiple
              beforeUpload={(_file, fileList) => {
                setImportMdFiles((prev) => {
                  const next = [...prev]
                  for (const item of fileList) {
                    if (!next.some((p) => p.name === item.name && p.size === item.size)) {
                      next.push(item)
                    }
                  }
                  return next
                })
                return false
              }}
              onRemove={(file) => {
                setImportMdFiles((prev) => prev.filter((item) => item.name !== file.name || item.size !== file.size))
              }}
              fileList={importMdFiles.map((file, index) => ({ uid: `md-${index}`, name: file.name, status: 'done' as const }))}
            >
              <Button>选择 .md 文件（可多选）</Button>
            </Upload>
            {importMdFiles.length > 0 && (
              <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 4 }}>
                已选择 {importMdFiles.length} 个 Markdown 文件
              </div>
            )}
          </div>
          <div>
            <div style={{ marginBottom: 6, fontWeight: 500 }}>附件图片（可选）</div>
            <Upload
              accept="image/png,image/jpeg,image/gif,image/webp,image/bmp"
              multiple
              beforeUpload={(_file, fileList) => {
                setImportAttachments((prev) => [...prev, ...fileList.filter((file) => !prev.some((item) => item.name === file.name && item.size === file.size))])
                return false
              }}
              onRemove={(file) => {
                setImportAttachments((prev) => prev.filter((item) => item.name !== file.name || item.size !== file.size))
              }}
              fileList={importAttachments.map((file, index) => ({ uid: String(index), name: file.name, status: 'done' as const }))}
            >
              <Button>选择附件图片</Button>
            </Upload>
            <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 4 }}>
              上传笔记中引用的图片文件（如 ![[image.png]] 引用的图片）
            </div>
          </div>
        </Space>
      </Modal>
    </PageShell>
  )
}
