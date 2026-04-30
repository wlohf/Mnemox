import { db, type LocalGoal, type QueuedOperation } from '../../db/studyDb'
import type { ModuleSyncAdapter } from '../SyncEngine'
import { apiFetch } from '../../services/apiClient'

interface ServerGoal {
  id: number
  title: string
  description: string | null
  target_level: string | null
  deadline: string | null
  status: string
  material_id: number | null
  material_title: string | null
  created_at: string | null
  updated_at: string | null
}

export const goalsSyncAdapter: ModuleSyncAdapter = {
  module: 'goals',

  async pushCreate(op: QueuedOperation) {
    const payload = JSON.parse(op.payload) as Record<string, unknown>
    const body: Record<string, unknown> = {
      title: payload.title ?? '',
      description: payload.description ?? undefined,
      target_level: payload.target_level ?? undefined,
      deadline: payload.deadline ?? undefined,
      material_id: payload.material_id ?? undefined,
    }

    const server = await apiFetch<ServerGoal>('/api/goals', {
      method: 'POST',
      body: JSON.stringify(body),
    })

    // Update local record
    await db.goals.update(op.localId, {
      _serverId: server.id,
      _syncStatus: 'synced',
      _lastSyncedAt: new Date().toISOString(),
      _updatedAt: server.updated_at ?? new Date().toISOString(),
    })

    // Update any child goalTasks that reference this local goal
    const childTasks = await db.goalTasks
      .where('_localGoalId')
      .equals(op.localId)
      .toArray()

    for (const task of childTasks) {
      await db.goalTasks.update(task._localId, { goal_id: server.id })
    }
  },

  async pushUpdate(op: QueuedOperation) {
    const local = await db.goals.get(op.localId)
    if (!local || !local._serverId) throw new Error('Cannot push update: no serverId')

    const payload = JSON.parse(op.payload) as Record<string, unknown>
    const body: Record<string, unknown> = {}
    if (payload.title !== undefined) body.title = payload.title
    if (payload.description !== undefined) body.description = payload.description
    if (payload.target_level !== undefined) body.target_level = payload.target_level
    if (payload.deadline !== undefined) body.deadline = payload.deadline
    if (payload.status !== undefined) body.status = payload.status

    const server = await apiFetch<ServerGoal>(`/api/goals/${local._serverId}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    })

    await db.goals.update(op.localId, {
      _syncStatus: 'synced',
      _lastSyncedAt: new Date().toISOString(),
      _updatedAt: server.updated_at ?? new Date().toISOString(),
    })
  },

  async pushDelete(op: QueuedOperation) {
    const local = await db.goals.get(op.localId)
    if (!local) return
    if (!local._serverId) {
      await db.goals.delete(op.localId)
      return
    }

    try {
      await apiFetch(`/api/goals/${local._serverId}`, { method: 'DELETE' })
    } catch (error: unknown) {
      const status = (error as { status?: number })?.status
      if (status !== 404) {
        throw error
      }
    }
    await db.goals.delete(op.localId)
  },

  async pullAll() {
    const serverGoals = await apiFetch<ServerGoal[]>('/api/goals')
    const serverMap = new Map(serverGoals.map((g) => [g.id, g]))

    const allLocal = await db.goals.toArray()
    const localByServerId = new Map<number, LocalGoal>()
    for (const l of allLocal) {
      if (l._serverId != null) localByServerId.set(l._serverId, l)
    }

    for (const sg of serverGoals) {
      const local = localByServerId.get(sg.id)
      const serverUpdatedAt = sg.updated_at ?? sg.created_at ?? new Date().toISOString()

      if (!local) {
        await db.goals.put({
          _localId: crypto.randomUUID(),
          _serverId: sg.id,
          _syncStatus: 'synced',
          _updatedAt: serverUpdatedAt,
          _lastSyncedAt: new Date().toISOString(),
          _conflictAt: null,
          _conflictServerData: null,
          title: sg.title,
          description: sg.description,
          target_level: sg.target_level,
          deadline: sg.deadline,
          status: sg.status,
          material_id: sg.material_id,
          material_title: sg.material_title,
          created_at: sg.created_at,
        })
      } else if (local._syncStatus === 'synced') {
        await db.goals.update(local._localId, {
          title: sg.title,
          description: sg.description,
          target_level: sg.target_level,
          deadline: sg.deadline,
          status: sg.status,
          material_id: sg.material_id,
          material_title: sg.material_title,
          _updatedAt: serverUpdatedAt,
          _lastSyncedAt: new Date().toISOString(),
          created_at: sg.created_at,
        })
      } else if (local._syncStatus === 'pending_update') {
        if (serverUpdatedAt > local._updatedAt) {
          await db.goals.update(local._localId, {
            title: sg.title,
            description: sg.description,
            target_level: sg.target_level,
            deadline: sg.deadline,
            status: sg.status,
            material_id: sg.material_id,
            material_title: sg.material_title,
            _syncStatus: 'synced',
            _updatedAt: serverUpdatedAt,
            _lastSyncedAt: new Date().toISOString(),
          })
          await db.opQueue.where({ module: 'goals', localId: local._localId }).delete()
        }
      }
    }

    // Detect server-side deletions
    for (const local of allLocal) {
      if (local._serverId != null && local._syncStatus === 'synced' && !serverMap.has(local._serverId)) {
        await db.goals.delete(local._localId)
      }
    }
  },
}
