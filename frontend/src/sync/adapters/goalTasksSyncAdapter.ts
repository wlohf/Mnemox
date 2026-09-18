import { createCrudAdapter, pick } from './createCrudAdapter'
import { utcTimestamp, type ServerEntity } from '../syncProtocol'

export const goalTasksSyncAdapter = createCrudAdapter({
  module: 'goalTasks', collection: '/api/goals/tasks',
  createUrl: op => `/api/goals/${op.parentServerId}/tasks`,
  createBody: payload => pick(payload, ['title', 'description', 'task_type', 'planned_date', 'chapter_id', 'parent_task_id']),
  updateBody: payload => pick(payload, ['title', 'description', 'task_type', 'planned_date', 'parent_task_id', 'status']),
  mapServer: server => ({
    ...pick(server, ['goal_id', 'parent_task_id', 'chapter_id', 'chapter_title', 'title', 'description', 'task_type', 'planned_date', 'status']),
    completed_at: utcTimestamp(server.completed_at), created_at: utcTimestamp(server.created_at),
  }),
  async list(fetch, db) {
    const goals = await db.goals.where('_serverId').above(0).toArray()
    const result: ServerEntity[] = []
    for (const goal of goals) {
      // Do not infer any deletions when even one source request fails.
      result.push(...await fetch<ServerEntity[]>(`/api/goals/${goal._serverId}/tasks`))
    }
    return result
  },
})
