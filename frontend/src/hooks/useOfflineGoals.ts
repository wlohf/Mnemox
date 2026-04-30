import { useLiveQuery } from 'dexie-react-hooks'
import { db, type LocalGoal } from '../db/studyDb'
import { enqueueOperation } from '../sync/enqueueOperation'
import { syncEngine } from '../sync/SyncEngine'
import { apiFetch, isNetworkOnline } from '../services/apiClient'

export interface OfflineGoalItem {
  _localId: string
  _serverId: number | null
  _syncStatus: string
  title: string
  description: string | null
  target_level: string | null
  deadline: string | null
  status: string
  material_id: number | null
  material_title: string | null
  created_at: string | null
  updated_at: string
}

function toOfflineItem(local: LocalGoal): OfflineGoalItem {
  return {
    _localId: local._localId,
    _serverId: local._serverId,
    _syncStatus: local._syncStatus,
    title: local.title,
    description: local.description,
    target_level: local.target_level,
    deadline: local.deadline,
    status: local.status,
    material_id: local.material_id,
    material_title: local.material_title,
    created_at: local.created_at,
    updated_at: local._updatedAt,
  }
}

export function useOfflineGoals(statusFilter?: string) {
  const allGoals = useLiveQuery(
    () =>
      db.goals
        .where('_syncStatus')
        .notEqual('pending_delete')
        .toArray(),
    [],
    [] as LocalGoal[],
  )

  let filtered = allGoals
  if (statusFilter && statusFilter !== 'all') {
    filtered = filtered.filter((g) => g.status === statusFilter)
  }

  filtered.sort((a, b) => (b._updatedAt > a._updatedAt ? 1 : -1))

  const goals: OfflineGoalItem[] = filtered.map(toOfflineItem)

  const createGoal = async (data: {
    title: string
    description?: string
    target_level?: string
    deadline?: string
    material_id?: number
  }): Promise<OfflineGoalItem> => {
    const now = new Date().toISOString()
    const localId = crypto.randomUUID()
    const record: LocalGoal = {
      _localId: localId,
      _serverId: null,
      _syncStatus: 'pending_create',
      _updatedAt: now,
      _lastSyncedAt: null,
      _conflictAt: null,
      _conflictServerData: null,
      title: data.title,
      description: data.description ?? null,
      target_level: data.target_level ?? null,
      deadline: data.deadline ?? null,
      status: 'active',
      material_id: data.material_id ?? null,
      material_title: null,
      created_at: now,
    }
    await db.goals.put(record)
    await enqueueOperation('goals', 'create', localId, record as unknown as Record<string, unknown>)
    void syncEngine.syncAll()
    return toOfflineItem(record)
  }

  const updateGoal = async (
    localId: string,
    data: Record<string, unknown>,
  ): Promise<OfflineGoalItem | null> => {
    const existing = await db.goals.get(localId)
    if (!existing) return null

    const now = new Date().toISOString()
    const updates: Partial<LocalGoal> = { _updatedAt: now }

    if (data.title !== undefined) updates.title = data.title as string
    if (data.description !== undefined) updates.description = data.description as string | null
    if (data.target_level !== undefined) updates.target_level = data.target_level as string | null
    if (data.deadline !== undefined) updates.deadline = data.deadline as string | null
    if (data.status !== undefined) updates.status = data.status as string

    if (existing._syncStatus === 'synced') {
      updates._syncStatus = 'pending_update'
    }

    await db.goals.update(localId, updates)
    await enqueueOperation('goals', 'update', localId, updates as Record<string, unknown>)
    void syncEngine.syncAll()

    const updated = await db.goals.get(localId)
    return updated ? toOfflineItem(updated) : null
  }

  const deleteGoal = async (localId: string): Promise<void> => {
    const existing = await db.goals.get(localId)
    if (!existing) return

    // 本地尚未同步到服务端，直接本地删除
    if (!existing._serverId) {
      await db.goals.delete(localId)
      await db.opQueue.where({ module: 'goals', localId }).delete()
      return
    }

    // 在线时直接调用服务端删除，只有成功才更新本地，避免“提示成功但服务端失败”
    if (isNetworkOnline()) {
      await apiFetch(`/api/goals/${existing._serverId}`, { method: 'DELETE' })
      await db.goals.delete(localId)
      await db.opQueue.where({ module: 'goals', localId }).delete()
      return
    }

    // 离线时进入队列，等待后续同步
    await db.goals.update(localId, { _syncStatus: 'pending_delete' })
    await enqueueOperation('goals', 'delete', localId, {})
    void syncEngine.syncAll()
  }

  return { goals, createGoal, updateGoal, deleteGoal }
}
