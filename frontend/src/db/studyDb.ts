import Dexie, { type Table } from 'dexie'

// ── Sync metadata mixin ──
export type SyncStatus = 'synced' | 'pending_create' | 'pending_update' | 'pending_delete' | 'sync_failed' | 'conflicted'

export interface SyncMeta {
  _localId: string        // client-generated UUID, primary key
  _serverId: number | null // server-assigned id (null before first push)
  _syncStatus: SyncStatus
  _updatedAt: string       // ISO datetime – latest local change
  _serverVersion?: number | null // server CAS revision, never a client timestamp
  _localRevision?: number       // monotonic local edits, including equal-clock edits
  _lastSyncedAt: string | null // ISO datetime of last successful push/pull
  _conflictAt: string | null   // ISO datetime when conflict was detected
  _conflictServerData: string | null // JSON snapshot of server version at conflict time
  _syncError?: string | null    // latest permanent sync failure, if any
  _syncFailedAt?: string | null // ISO datetime when permanent sync failure was recorded
}

// ── Local table types ──

export interface LocalNote extends SyncMeta {
  title: string
  content: string
  note_type: string | null
  material_id: number | null
  chapter_id: number | null
  tags: string   // JSON-encoded string[]
  links: string  // JSON-encoded NoteLink[]
  created_at: string | null
}

export interface LocalGoal extends SyncMeta {
  title: string
  description: string | null
  target_level: string | null
  deadline: string | null  // ISO date
  status: string           // active | completed | paused
  material_id: number | null
  material_title: string | null
  created_at: string | null
}

export interface LocalGoalTask extends SyncMeta {
  goal_id: number | null        // server goal_id (null if parent goal not yet synced)
  _localGoalId: string | null   // local goal _localId for parent reference
  parent_task_id: number | null
  chapter_id: number | null
  chapter_title: string | null
  title: string
  description: string | null
  task_type: string | null
  planned_date: string | null   // ISO date
  status: string                // pending | in_progress | completed
  completed_at: string | null
  created_at: string | null
}

export interface LocalAnkiCard extends SyncMeta {
  front: string
  back: string
  source: string
  tags: string | null
  note: string | null
  due_at: string | null
  interval_days: number
  ease_factor: number
  repetitions: number
  last_quality: number | null
  created_at: string | null
}

export interface LocalWrongQuestion extends SyncMeta {
  content: string
  question_type: string | null
  answer: string | null
  explanation: string | null
  difficulty: number | null
  chapter_id: number | null
  chapter_title: string
  wrong_count: number
  mastery_status: string
  review_count: number
  knowledge_point: string | null
  next_review_at: string | null
  last_wrong_at: string | null
  created_at: string | null
}

// ── Operation queue ──

export type OpType = 'create' | 'update' | 'delete'
export type ModuleName = 'notes' | 'goals' | 'goalTasks' | 'ankiCards' | 'wrongQuestions'

export interface QueuedOperation {
  id?: number             // auto-incremented
  operationId?: string    // durable idempotency identity; immutable once claimed
  claimedAt?: string | null // sticky across failures/restarts (not a short lease)
  serverId?: number | null
  expectedVersion?: number | null
  parentServerId?: number | null
  legacyUncertain?: boolean
  module: ModuleName
  opType: OpType
  localId: string         // the _localId of the affected record
  payload: string         // JSON serialised data for create/update
  createdAt: string       // ISO datetime
  attempts?: number
  lastError?: string | null
  failedAt?: string | null
}

// ── Database class ──

class StudyDatabase extends Dexie {
  notes!: Table<LocalNote, string>
  goals!: Table<LocalGoal, string>
  goalTasks!: Table<LocalGoalTask, string>
  ankiCards!: Table<LocalAnkiCard, string>
  wrongQuestions!: Table<LocalWrongQuestion, string>
  opQueue!: Table<QueuedOperation, number>

  constructor(name: string) {
    // Closed databases must never auto-reopen after logout/account switching.
    super(name, { autoOpen: false })

    this.version(1).stores({
      notes:     '_localId, _serverId, _syncStatus, _updatedAt',
      goals:     '_localId, _serverId, _syncStatus, _updatedAt, status',
      goalTasks: '_localId, _serverId, _syncStatus, _updatedAt, goal_id, _localGoalId, planned_date, status',
      opQueue:   '++id, module, localId, createdAt',
    })

    this.version(2).stores({
      notes:     '_localId, _serverId, _syncStatus, _updatedAt',
      goals:     '_localId, _serverId, _syncStatus, _updatedAt, status',
      goalTasks: '_localId, _serverId, _syncStatus, _updatedAt, goal_id, _localGoalId, parent_task_id, planned_date, status',
      opQueue:   '++id, module, localId, createdAt',
    })

    this.version(3).stores({
      notes:          '_localId, _serverId, _syncStatus, _updatedAt',
      goals:          '_localId, _serverId, _syncStatus, _updatedAt, status',
      goalTasks:      '_localId, _serverId, _syncStatus, _updatedAt, goal_id, _localGoalId, parent_task_id, planned_date, status',
      ankiCards:      '_localId, _serverId, _syncStatus, _updatedAt, due_at',
      wrongQuestions: '_localId, _serverId, _syncStatus, _updatedAt',
      opQueue:        '++id, module, localId, createdAt',
    })

    this.version(4).stores({
      notes:          '_localId, _serverId, _syncStatus, _updatedAt',
      goals:          '_localId, _serverId, _syncStatus, _updatedAt, status',
      goalTasks:      '_localId, _serverId, _syncStatus, _updatedAt, goal_id, _localGoalId, parent_task_id, planned_date, status',
      ankiCards:      '_localId, _serverId, _syncStatus, _updatedAt, due_at',
      wrongQuestions: '_localId, _serverId, _syncStatus, _updatedAt',
      opQueue:        '++id, module, localId, [module+localId], createdAt',
    })

    this.version(5).stores({
      opQueue: '++id, &operationId, module, localId, [module+localId], createdAt',
    }).upgrade(async (tx) => {
      // Older creates may already have committed without a response. Inventing a
      // new idempotency key cannot make that uncertain history safe to replay.
      await tx.table('opQueue').toCollection().modify((op: QueuedOperation) => {
        if (!op.operationId && op.opType === 'create') {
          op.legacyUncertain = true
          op.failedAt = new Date().toISOString()
          op.lastError = '升级前的创建结果不确定，请核对云端并备份本地内容后处理；不会自动重发'
        }
        op.operationId ??= crypto.randomUUID()
      })
    })
  }
}

// IndexedDB already partitions by server origin. Creation time also distinguishes
// reused numeric IDs after a server database is replaced. The legacy unowned
// StudyAssistantDB is deliberately left untouched, never adopted by the next login.
export let db = new StudyDatabase('StudyAssistantDB:locked')

export function studyDatabaseName(user: { id: number; created_at: string }): string {
  if (!Number.isSafeInteger(user.id) || user.id <= 0 || !user.created_at) {
    throw new Error('无法确认离线数据归属，请重新登录')
  }
  return `StudyAssistantDB:user:${user.id}:${encodeURIComponent(user.created_at)}`
}

export function closeStudyDatabase(): void {
  db.close()
  db = new StudyDatabase('StudyAssistantDB:locked')
}

export async function openStudyDatabase(user: { id: number; created_at: string }): Promise<void> {
  closeStudyDatabase()
  const next = new StudyDatabase(studyDatabaseName(user))
  db = next
  await next.open()
  if (db !== next) {
    next.close()
    throw new DOMException('登录会话已变化', 'AbortError')
  }
}
