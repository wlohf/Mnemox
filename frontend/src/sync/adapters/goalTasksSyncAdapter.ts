import { db, type LocalGoalTask, type QueuedOperation } from '../../db/studyDb'
import type { ModuleSyncAdapter } from '../SyncEngine'
import { apiFetch } from '../../services/apiClient'

interface ServerTask {
  id: number
  goal_id: number
  parent_task_id?: number | null
  chapter_id: number | null
  chapter_title: string | null
  title: string
  description: string | null
  task_type: string | null
  planned_date: string | null
  status: string
  completed_at: string | null
  created_at: string | null
  updated_at: string | null
}

export const goalTasksSyncAdapter: ModuleSyncAdapter = {
  module: 'goalTasks',

  async pushCreate(op: QueuedOperation) {
    const local = await db.goalTasks.get(op.localId)
    if (!local) throw new Error('Local goalTask not found')

    // If parent goal hasn't been synced yet (no goal_id), skip for now
    if (!local.goal_id) {
      throw new Error('Parent goal not yet synced, will retry')
    }

    const payload = JSON.parse(op.payload) as Record<string, unknown>
    const body: Record<string, unknown> = {
      title: payload.title ?? local.title,
      description: payload.description ?? local.description ?? undefined,
      task_type: payload.task_type ?? local.task_type ?? 'learn',
      planned_date: payload.planned_date ?? local.planned_date ?? undefined,
      chapter_id: payload.chapter_id ?? local.chapter_id ?? undefined,
      parent_task_id: payload.parent_task_id ?? local.parent_task_id ?? undefined,
    }

    const server = await apiFetch<ServerTask>(`/api/goals/${local.goal_id}/tasks`, {
      method: 'POST',
      body: JSON.stringify(body),
    })

    await db.goalTasks.update(op.localId, {
      _serverId: server.id,
      _syncStatus: 'synced',
      _lastSyncedAt: new Date().toISOString(),
      _updatedAt: server.updated_at ?? new Date().toISOString(),
    })
  },

  async pushUpdate(op: QueuedOperation) {
    const local = await db.goalTasks.get(op.localId)
    if (!local || !local._serverId) throw new Error('Cannot push update: no serverId')

    const payload = JSON.parse(op.payload) as Record<string, unknown>
    const body: Record<string, unknown> = {}
    if (payload.title !== undefined) body.title = payload.title
    if (payload.description !== undefined) body.description = payload.description
    if (payload.task_type !== undefined) body.task_type = payload.task_type
    if (payload.planned_date !== undefined) body.planned_date = payload.planned_date
    if (payload.parent_task_id !== undefined) body.parent_task_id = payload.parent_task_id
    if (payload.status !== undefined) body.status = payload.status

    const server = await apiFetch<ServerTask>(`/api/goals/tasks/${local._serverId}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    })

    await db.goalTasks.update(op.localId, {
      _syncStatus: 'synced',
      _lastSyncedAt: new Date().toISOString(),
      _updatedAt: server.updated_at ?? new Date().toISOString(),
    })
  },

  async pushDelete(op: QueuedOperation) {
    const local = await db.goalTasks.get(op.localId)
    if (!local) return
    if (!local._serverId) {
      await db.goalTasks.delete(op.localId)
      return
    }

    try {
      await apiFetch(`/api/goals/tasks/${local._serverId}`, { method: 'DELETE' })
    } catch (error: unknown) {
      const status = (error as { status?: number })?.status
      if (status !== 404) {
        throw error
      }
    }
    await db.goalTasks.delete(op.localId)
  },

  async pullAll() {
    // We need to pull tasks for all goals
    const allGoals = await db.goals.where('_serverId').above(0).toArray()

    const allServerTasks: ServerTask[] = []
    for (const goal of allGoals) {
      if (!goal._serverId) continue
      try {
        const tasks = await apiFetch<ServerTask[]>(`/api/goals/${goal._serverId}/tasks`)
        allServerTasks.push(...tasks)
      } catch {
        // Skip goals that fail to fetch
      }
    }

    const serverMap = new Map(allServerTasks.map((t) => [t.id, t]))

    const allLocal = await db.goalTasks.toArray()
    const localByServerId = new Map<number, LocalGoalTask>()
    for (const l of allLocal) {
      if (l._serverId != null) localByServerId.set(l._serverId, l)
    }

    // Build goal serverId → localId map
    const goalLocalIdMap = new Map<number, string>()
    for (const g of allGoals) {
      if (g._serverId != null) goalLocalIdMap.set(g._serverId, g._localId)
    }

    for (const st of allServerTasks) {
      const local = localByServerId.get(st.id)
      const serverUpdatedAt = st.updated_at ?? st.created_at ?? new Date().toISOString()

      if (!local) {
        await db.goalTasks.put({
          _localId: crypto.randomUUID(),
          _serverId: st.id,
          _syncStatus: 'synced',
          _updatedAt: serverUpdatedAt,
          _lastSyncedAt: new Date().toISOString(),
          _conflictAt: null,
          _conflictServerData: null,
          goal_id: st.goal_id,
          _localGoalId: goalLocalIdMap.get(st.goal_id) ?? null,
          parent_task_id: st.parent_task_id ?? null,
          chapter_id: st.chapter_id,
          chapter_title: st.chapter_title,
          title: st.title,
          description: st.description,
          task_type: st.task_type,
          planned_date: st.planned_date,
          status: st.status,
          completed_at: st.completed_at,
          created_at: st.created_at,
        })
      } else if (local._syncStatus === 'synced') {
        await db.goalTasks.update(local._localId, {
          goal_id: st.goal_id,
          parent_task_id: st.parent_task_id ?? null,
          chapter_id: st.chapter_id,
          chapter_title: st.chapter_title,
          title: st.title,
          description: st.description,
          task_type: st.task_type,
          planned_date: st.planned_date,
          status: st.status,
          completed_at: st.completed_at,
          _updatedAt: serverUpdatedAt,
          _lastSyncedAt: new Date().toISOString(),
          created_at: st.created_at,
        })
      } else if (local._syncStatus === 'pending_update') {
        if (serverUpdatedAt > local._updatedAt) {
          await db.goalTasks.update(local._localId, {
            goal_id: st.goal_id,
            parent_task_id: st.parent_task_id ?? null,
            chapter_id: st.chapter_id,
            chapter_title: st.chapter_title,
            title: st.title,
            description: st.description,
            task_type: st.task_type,
            planned_date: st.planned_date,
            status: st.status,
            completed_at: st.completed_at,
            _syncStatus: 'synced',
            _updatedAt: serverUpdatedAt,
            _lastSyncedAt: new Date().toISOString(),
          })
          await db.opQueue.where({ module: 'goalTasks', localId: local._localId }).delete()
        }
      }
    }

    // Detect server-side deletions
    for (const local of allLocal) {
      if (local._serverId != null && local._syncStatus === 'synced' && !serverMap.has(local._serverId)) {
        await db.goalTasks.delete(local._localId)
      }
    }
  },
}
