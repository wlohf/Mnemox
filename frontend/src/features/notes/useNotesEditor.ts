import { useCallback, useEffect, useMemo, useState } from 'react'
import { useOfflineNotes, type OfflineNoteItem } from '../../hooks/useOfflineNotes'

/*
 * Notes editor state: selection, local draft autosave (per note, in
 * localStorage) and the explicit save that writes through the offline sync
 * queue. Mirrors the legacy behaviour contract.
 */

export type FolderKey = 'all' | 'untagged' | 'pending' | `tag:${string}`
export type DraftStatus = 'clean' | 'dirty' | 'saved' | 'restored'

const DRAFT_PREFIX = 'mnemox_note_draft:'
const draftKey = (id: string) => `${DRAFT_PREFIX}${id}`

interface Draft {
  title: string
  content: string
  tags: string[]
  savedAt?: string
}

function readDraft(id: string): Draft | null {
  try {
    const raw = localStorage.getItem(draftKey(id))
    if (!raw) return null
    const d = JSON.parse(raw) as Partial<Draft> & { tagsText?: string }
    return {
      title: d.title ?? '',
      content: d.content ?? '',
      tags: Array.isArray(d.tags) ? d.tags : (d.tagsText ?? '').split(',').map(t => t.trim()).filter(Boolean),
      savedAt: d.savedAt,
    }
  } catch {
    localStorage.removeItem(draftKey(id))
    return null
  }
}

export function excerpt(content: string): string {
  const line = content
    .split('\n')
    .map(l => l.trim())
    .find(l => l && !l.startsWith('#'))
  return line?.replace(/^[-*]\s+/, '').replace(/\[( |x)\]\s*/i, '') || '空白笔记'
}

export function useNotesEditor() {
  const { notes, createNote, updateNote, deleteNote } = useOfflineNotes()
  const [query, setQuery] = useState('')
  const [folder, setFolder] = useState<FolderKey>('all')
  const [activeId, setActiveId] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [status, setStatus] = useState<DraftStatus>('clean')
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const tagStats = useMemo(() => {
    const counts = new Map<string, number>()
    for (const n of notes) for (const t of n.tags || []) counts.set(t, (counts.get(t) || 0) + 1)
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'))
      .map(([tag, count]) => ({ tag, count }))
  }, [notes])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return notes.filter(n => {
      const t = n.tags || []
      if (folder === 'untagged' && t.length > 0) return false
      if (folder === 'pending' && n._syncStatus === 'synced') return false
      if (folder.startsWith('tag:') && !t.includes(folder.slice(4))) return false
      if (!q) return true
      return n.title.toLowerCase().includes(q) || n.content.toLowerCase().includes(q)
    })
  }, [folder, notes, query])

  const active = useMemo(() => notes.find(n => n._localId === activeId) ?? null, [activeId, notes])

  const load = useCallback((note: OfflineNoteItem | null) => {
    if (!note) {
      setActiveId(null)
      setTitle('')
      setContent('')
      setTags([])
      setStatus('clean')
      setSavedAt(null)
      return
    }
    setActiveId(note._localId)
    const d = readDraft(note._localId)
    if (d) {
      setTitle(d.title)
      setContent(d.content)
      setTags(d.tags)
      setSavedAt(d.savedAt ?? null)
      setStatus('restored')
    } else {
      setTitle(note.title || '')
      setContent(note.content || '')
      setTags(note.tags || [])
      setSavedAt(null)
      setStatus('clean')
    }
  }, [])

  // Keep a valid selection as filters change.
  useEffect(() => {
    if (visible.length === 0) {
      if (activeId) load(null)
      return
    }
    if (!activeId || !visible.some(n => n._localId === activeId)) load(visible[0])
  }, [visible.length, folder, query])

  // Pull in remote changes while the editor is clean.
  useEffect(() => {
    if (!active || status !== 'clean') return
    if (active.title !== title) setTitle(active.title || '')
    if (active.content !== content) setContent(active.content || '')
    if (JSON.stringify(active.tags || []) !== JSON.stringify(tags)) setTags(active.tags || [])
  }, [active?.updated_at, active?._syncStatus])

  // Local draft autosave.
  useEffect(() => {
    if (!active) return
    const dirty =
      title !== (active.title || '') || content !== (active.content || '') || JSON.stringify(tags) !== JSON.stringify(active.tags || [])
    if (!dirty) {
      setStatus(prev => (prev === 'restored' ? prev : 'clean'))
      return
    }
    setStatus('dirty')
    const t = window.setTimeout(() => {
      const at = new Date().toISOString()
      localStorage.setItem(draftKey(active._localId), JSON.stringify({ title, content, tags, savedAt: at }))
      setSavedAt(at)
      setStatus('saved')
    }, 700)
    return () => window.clearTimeout(t)
  }, [active, title, content, tags])

  const save = useCallback(async () => {
    if (!active) return null
    setSaving(true)
    try {
      const saved = await updateNote(active._localId, { title: title.trim() || '未命名笔记', content, tags: tags.slice(0, 12) })
      if (saved) {
        localStorage.removeItem(draftKey(active._localId))
        setStatus('clean')
        setSavedAt(null)
      }
      return saved
    } finally {
      setSaving(false)
    }
  }, [active, content, tags, title, updateNote])

  const create = useCallback(async () => {
    const tag = folder.startsWith('tag:') ? folder.slice(4) : ''
    const created = await createNote({ title: '新笔记', content: '', note_type: 'general', tags: tag ? [tag] : [] })
    load(created)
    return created
  }, [createNote, folder, load])

  const discardDraft = useCallback(() => {
    if (!active) return
    localStorage.removeItem(draftKey(active._localId))
    load(active)
  }, [active, load])

  const remove = useCallback(async () => {
    if (!active) return false
    const ok = await deleteNote(active._localId)
    if (ok) {
      localStorage.removeItem(draftKey(active._localId))
      load(null)
    }
    return ok
  }, [active, deleteNote, load])

  return {
    notes,
    visible,
    tagStats,
    query,
    setQuery,
    folder,
    setFolder,
    active,
    open: load,
    title,
    setTitle,
    content,
    setContent,
    tags,
    setTags,
    status,
    savedAt,
    saving,
    save,
    create,
    remove,
    discardDraft,
    createNote,
  }
}
