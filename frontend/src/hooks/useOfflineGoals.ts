import { useLiveQuery } from 'dexie-react-hooks'
import { db as activeDb, type LocalGoal } from '../db/studyDb'
import { saveLocalOperation } from '../sync/enqueueOperation'
import { syncEngine } from '../sync/SyncEngine'

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
  const db = activeDb
  const allGoals = useLiveQuery(
    () => db.goals.where('_syncStatus').notEqual('pending_delete').toArray(),
    [db],
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
    const saved = await saveLocalOperation<LocalGoal>('goals', 'create', localId, record, db)
    if (!saved) throw new Error('Unable to save goal locally')
    void syncEngine.syncAll()
    return toOfflineItem(saved)
  }

  const updateGoal = async (
    localId: string,
    data: Record<string, unknown>,
  ): Promise<OfflineGoalItem | null> => {
    const updates: Record<string, unknown> = {}
    if (data.title !== undefined) updates.title = data.title
    if (data.description !== undefined) updates.description = data.description
    if (data.target_level !== undefined) updates.target_level = data.target_level
    if (data.deadline !== undefined) updates.deadline = data.deadline
    if (data.status !== undefined) updates.status = data.status

    const saved = await saveLocalOperation<LocalGoal>('goals', 'update', localId, updates, db)
    void syncEngine.syncAll()
    return saved ? toOfflineItem(saved) : null
  }

  const deleteGoal = async (localId: string): Promise<void> => {
    await saveLocalOperation<LocalGoal>('goals', 'delete', localId, {}, db)
    void syncEngine.syncAll()
  }

  return { goals, createGoal, updateGoal, deleteGoal }
}
