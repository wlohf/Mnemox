import { createCrudAdapter, pick } from './createCrudAdapter'
import { utcTimestamp } from '../syncProtocol'

export const goalsSyncAdapter = createCrudAdapter({
  module: 'goals', collection: '/api/goals',
  createBody: payload => pick(payload, ['title', 'description', 'target_level', 'deadline', 'material_id']),
  updateBody: payload => pick(payload, ['title', 'description', 'target_level', 'deadline', 'status']),
  mapServer: server => ({
    ...pick(server, ['title', 'description', 'target_level', 'deadline', 'status', 'material_id', 'material_title']),
    created_at: utcTimestamp(server.created_at),
  }),
})
