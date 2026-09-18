import { useLiveQuery } from 'dexie-react-hooks'
import { db as activeDb, type LocalNote } from '../db/studyDb'
import { saveLocalOperation } from '../sync/enqueueOperation'
import { syncEngine } from '../sync/SyncEngine'

export interface OfflineNoteItem {
  _localId: string
  _serverId: number | null
  _syncStatus: string
  title: string
  content: string
  note_type: string | null
  material_id: number | null
  chapter_id: number | null
  tags: string[]
  links: Array<{ id?: number; link_type: string; link_id: number }>
  created_at: string | null
  updated_at: string
}

function toOfflineItem(local: LocalNote): OfflineNoteItem {
  return {
    _localId: local._localId,
    _serverId: local._serverId,
    _syncStatus: local._syncStatus,
    title: local.title,
    content: local.content,
    note_type: local.note_type,
    material_id: local.material_id,
    chapter_id: local.chapter_id,
    tags: safeParse(local.tags, []),
    links: safeParse(local.links, []),
    created_at: local.created_at,
    updated_at: local._updatedAt,
  }
}

function safeParse<T>(json: string | null | undefined, fallback: T): T {
  if (!json) return fallback
  try {
    return JSON.parse(json)
  } catch {
    return fallback
  }
}

export function useOfflineNotes(params?: { q?: string; tag?: string }) {
  const db = activeDb
  const allNotes = useLiveQuery(
    () => db.notes.where('_syncStatus').notEqual('pending_delete').toArray(),
    [db],
    [] as LocalNote[],
  )

  let filtered = allNotes
  if (params?.q) {
    const lower = params.q.toLowerCase()
    filtered = filtered.filter(
      (n) => n.title.toLowerCase().includes(lower) || n.content.toLowerCase().includes(lower),
    )
  }
  if (params?.tag) {
    const tag = params.tag
    filtered = filtered.filter((n) => safeParse<string[]>(n.tags, []).includes(tag))
  }

  filtered.sort((a, b) => (b._updatedAt > a._updatedAt ? 1 : -1))
  const notes: OfflineNoteItem[] = filtered.map(toOfflineItem)

  const createNote = async (data: {
    title: string
    content: string
    note_type?: string
    material_id?: number | null
    chapter_id?: number | null
    tags?: string[]
    links?: Array<{ link_type: string; link_id: number }>
  }): Promise<OfflineNoteItem> => {
    const now = new Date().toISOString()
    const localId = crypto.randomUUID()
    const record: LocalNote = {
      _localId: localId,
      _serverId: null,
      _syncStatus: 'pending_create',
      _updatedAt: now,
      _lastSyncedAt: null,
      _conflictAt: null,
      _conflictServerData: null,
      title: data.title,
      content: data.content,
      note_type: data.note_type ?? 'general',
      material_id: data.material_id ?? null,
      chapter_id: data.chapter_id ?? null,
      tags: JSON.stringify(data.tags ?? []),
      links: JSON.stringify(data.links ?? []),
      created_at: now,
    }
    const saved = await saveLocalOperation<LocalNote>('notes', 'create', localId, record, db)
    if (!saved) throw new Error('Unable to save note locally')
    void syncEngine.syncAll()
    return toOfflineItem(saved)
  }

  const updateNote = async (
    localId: string,
    data: Record<string, unknown>,
  ): Promise<OfflineNoteItem | null> => {
    const updates: Record<string, unknown> = {}
    if (data.title !== undefined) updates.title = data.title
    if (data.content !== undefined) updates.content = data.content
    if (data.note_type !== undefined) updates.note_type = data.note_type
    if (data.material_id !== undefined) updates.material_id = data.material_id
    if (data.chapter_id !== undefined) updates.chapter_id = data.chapter_id
    if (data.tags !== undefined) updates.tags = JSON.stringify(data.tags)
    if (data.links !== undefined) updates.links = JSON.stringify(data.links)

    const saved = await saveLocalOperation<LocalNote>('notes', 'update', localId, updates, db)
    void syncEngine.syncAll()
    return saved ? toOfflineItem(saved) : null
  }

  const deleteNote = async (localId: string): Promise<boolean> => {
    const saved = await saveLocalOperation<LocalNote>('notes', 'delete', localId, {}, db)
    void syncEngine.syncAll()
    return saved !== undefined
  }

  return { notes, createNote, updateNote, deleteNote }
}
