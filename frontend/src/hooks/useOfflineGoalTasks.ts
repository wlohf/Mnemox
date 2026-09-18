import { useLiveQuery } from 'dexie-react-hooks'
import { db as activeDb, type LocalGoalTask } from '../db/studyDb'
import { saveLocalOperation } from '../sync/enqueueOperation'
import { syncEngine } from '../sync/SyncEngine'

export interface OfflineGoalTaskItem {
  _localId: string
  _serverId: number | null
  _syncStatus: string
  goal_id: number | null
  _localGoalId: string | null
  parent_task_id: number | null
  chapter_id: number | null
  chapter_title: string | null
  title: string
  description: string | null
  task_type: string | null
  planned_date: string | null
  status: string
  completed_at: string | null
  created_at: string | null
  updated_at: string
}

function toOfflineItem(local: LocalGoalTask): OfflineGoalTaskItem {
  return {
    _localId: local._localId,
    _serverId: local._serverId,
    _syncStatus: local._syncStatus,
    goal_id: local.goal_id,
    _localGoalId: local._localGoalId,
    parent_task_id: local.parent_task_id ?? null,
    chapter_id: local.chapter_id,
    chapter_title: local.chapter_title,
    title: local.title,
    description: local.description,
    task_type: local.task_type,
    planned_date: local.planned_date,
    status: local.status,
    completed_at: local.completed_at,
    created_at: local.created_at,
    updated_at: local._updatedAt,
  }
}

export function useOfflineGoalTasks(params?: {
  goalLocalId?: string
  goalServerId?: number
  plannedDate?: string
}) {
  const db = activeDb
  const tasks = useLiveQuery(
    () => db.goalTasks.where('_syncStatus').notEqual('pending_delete').toArray(),
    [db],
    [] as LocalGoalTask[],
  )

  let filtered = tasks
  if (params?.goalLocalId) {
    const gLocalId = params.goalLocalId
    filtered = filtered.filter((t) => t._localGoalId === gLocalId)
  } else if (params?.goalServerId) {
    const gServerId = params.goalServerId
    filtered = filtered.filter((t) => t.goal_id === gServerId)
  }
  if (params?.plannedDate) {
    const pd = params.plannedDate
    filtered = filtered.filter((t) => t.planned_date === pd)
  }

  filtered.sort((a, b) => (b._updatedAt > a._updatedAt ? 1 : -1))
  const goalTasks: OfflineGoalTaskItem[] = filtered.map(toOfflineItem)

  const createGoalTask = async (
    goalLocalId: string,
    goalServerId: number | null,
    data: {
      title: string
      description?: string
      task_type?: string
      planned_date?: string
      chapter_id?: number
      parent_task_id?: number | null
    },
  ): Promise<OfflineGoalTaskItem> => {
    const now = new Date().toISOString()
    const localId = crypto.randomUUID()
    const record: LocalGoalTask = {
      _localId: localId,
      _serverId: null,
      _syncStatus: 'pending_create',
      _updatedAt: now,
      _lastSyncedAt: null,
      _conflictAt: null,
      _conflictServerData: null,
      goal_id: goalServerId,
      _localGoalId: goalLocalId,
      parent_task_id: data.parent_task_id ?? null,
      chapter_id: data.chapter_id ?? null,
      chapter_title: null,
      title: data.title,
      description: data.description ?? null,
      task_type: data.task_type ?? 'learn',
      planned_date: data.planned_date ?? null,
      status: 'pending',
      completed_at: null,
      created_at: now,
    }
    const saved = await saveLocalOperation<LocalGoalTask>('goalTasks', 'create', localId, record, db)
    if (!saved) throw new Error('Unable to save goal task locally')
    void syncEngine.syncAll()
    return toOfflineItem(saved)
  }

  const updateGoalTask = async (
    localId: string,
    data: Record<string, unknown>,
  ): Promise<OfflineGoalTaskItem | null> => {
    const updates: Record<string, unknown> = {}
    if (data.title !== undefined) updates.title = data.title
    if (data.description !== undefined) updates.description = data.description
    if (data.task_type !== undefined) updates.task_type = data.task_type
    if (data.planned_date !== undefined) updates.planned_date = data.planned_date
    if (data.parent_task_id !== undefined) updates.parent_task_id = data.parent_task_id
    if (data.status !== undefined) updates.status = data.status
    if (data.completed_at !== undefined) updates.completed_at = data.completed_at

    const saved = await saveLocalOperation<LocalGoalTask>('goalTasks', 'update', localId, updates, db)
    void syncEngine.syncAll()
    return saved ? toOfflineItem(saved) : null
  }

  const deleteGoalTask = async (localId: string): Promise<boolean> => {
    const saved = await saveLocalOperation<LocalGoalTask>('goalTasks', 'delete', localId, {}, db)
    void syncEngine.syncAll()
    return saved !== undefined
  }

  return { goalTasks, createGoalTask, updateGoalTask, deleteGoalTask }
}
