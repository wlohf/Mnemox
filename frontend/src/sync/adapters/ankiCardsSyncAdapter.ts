import { createCrudAdapter, pick } from './createCrudAdapter'
import { utcTimestamp } from '../syncProtocol'

export const ankiCardsSyncAdapter = createCrudAdapter({
  module: 'ankiCards', collection: '/api/anki/cards',
  createBody: payload => pick(payload, ['front', 'back', 'tags', 'note']),
  updateBody: payload => pick(payload, ['front', 'back', 'tags', 'note']),
  mapServer: server => ({
    ...pick(server, ['front', 'back', 'source', 'tags', 'note', 'interval_days', 'ease_factor', 'repetitions', 'last_quality']),
    due_at: utcTimestamp(server.due_at), created_at: utcTimestamp(server.created_at),
  }),
  list: fetch => fetch('/api/anki/cards?scope=all&limit=200'),
  // This API is capped. Absence from a page is never evidence of deletion.
  completeSnapshot: false,
})
