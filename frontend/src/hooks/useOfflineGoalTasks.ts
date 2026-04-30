import { useLiveQuery } from 'dexie-react-hooks'
import { db, type LocalGoalTask } from '../db/studyDb'
import { enqueueOperation } from '../sync/enqueueOperation'
import { syncEngine } from '../sync/SyncEngine'
import { apiFetch, isNetworkOnline } from '../services/apiClient'

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
  const tasks = useLiveQuery(
    () =>
      db.goalTasks
        .where('_syncStatus')
        .notEqual('pending_delete')
        .toArray(),
    [],
    [] as LocalGoalTask[],
  )

  let filtered = tasks

  // Filter by goal
  if (params?.goalLocalId) {
    const gLocalId = params.goalLocalId
    filtered = filtered.filter(
      (t) => t._localGoalId === gLocalId,
    )
  } else if (params?.goalServerId) {
    const gServerId = params.goalServerId
    filtered = filtered.filter(
      (t) => t.goal_id === gServerId,
    )
  }

  // Filter by planned_date
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
    await db.goalTasks.put(record)
    await enqueueOperation('goalTasks', 'create', localId, record as unknown as Record<string, unknown>)
    void syncEngine.syncAll()
    return toOfflineItem(record)
  }

  const updateGoalTask = async (
    localId: string,
    data: Record<string, unknown>,
  ): Promise<OfflineGoalTaskItem | null> => {
    const existing = await db.goalTasks.get(localId)
    if (!existing) return null

    const now = new Date().toISOString()
    const updates: Partial<LocalGoalTask> = { _updatedAt: now }

    if (data.title !== undefined) updates.title = data.title as string
    if (data.description !== undefined) updates.description = data.description as string | null
    if (data.task_type !== undefined) updates.task_type = data.task_type as string | null
    if (data.planned_date !== undefined) updates.planned_date = data.planned_date as string | null
    if (data.parent_task_id !== undefined) updates.parent_task_id = data.parent_task_id as number | null
    if (data.status !== undefined) updates.status = data.status as string
    if (data.completed_at !== undefined) updates.completed_at = data.completed_at as string | null

    if (existing._syncStatus === 'synced') {
      updates._syncStatus = 'pending_update'
    }

    await db.goalTasks.update(localId, updates)
    await enqueueOperation('goalTasks', 'update', localId, updates as Record<string, unknown>)
    void syncEngine.syncAll()

    const updated = await db.goalTasks.get(localId)
    return updated ? toOfflineItem(updated) : null
  }

  const deleteGoalTask = async (localId: string): Promise<boolean> => {
    const existing = await db.goalTasks.get(localId)
    if (!existing) return false

    const now = new Date().toISOString()

    if (existing._syncStatus === 'pending_create' || !existing._serverId) {
      // Not yet synced to server, just delete locally
      await db.goalTasks.delete(localId)
      await db.opQueue.where({ module: 'goalTasks', localId }).delete()
      return true
    }

    if (isNetworkOnline()) {
      await apiFetch(`/api/goals/tasks/${existing._serverId}`, { method: 'DELETE' })
      await db.goalTasks.delete(localId)
      await db.opQueue.where({ module: 'goalTasks', localId }).delete()
    } else {
      // Mark as pending_delete for sync
      await db.goalTasks.update(localId, {
        _syncStatus: 'pending_delete',
        _updatedAt: now,
      })
      await enqueueOperation('goalTasks', 'delete', localId, {})
      void syncEngine.syncAll()
    }

    return true
  }

  return { goalTasks, createGoalTask, updateGoalTask, deleteGoalTask }
}
