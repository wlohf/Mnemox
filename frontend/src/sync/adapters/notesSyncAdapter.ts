import { createCrudAdapter, pick } from './createCrudAdapter'
import { utcTimestamp, type ServerEntity } from '../syncProtocol'

function body(payload: Record<string, unknown>) {
  const result = pick(payload, ['title', 'content', 'note_type', 'material_id', 'chapter_id'])
  for (const key of ['tags', 'links']) {
    if (payload[key] !== undefined) result[key] = typeof payload[key] === 'string' ? JSON.parse(payload[key] as string) : payload[key]
  }
  return result
}
export const notesSyncAdapter = createCrudAdapter({
  module: 'notes', collection: '/api/notes',
  createBody: payload => ({ title: '', content: '', note_type: 'general', ...body(payload) }),
  updateBody: body,
  mapServer: (server: ServerEntity) => ({
    ...pick(server, ['title', 'content', 'note_type', 'material_id', 'chapter_id']),
    tags: JSON.stringify(server.tags ?? []), links: JSON.stringify(server.links ?? []),
    created_at: utcTimestamp(server.created_at),
  }),
})
