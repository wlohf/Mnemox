import { createCrudAdapter, pick } from './createCrudAdapter'
import { scopedApiFetch } from '../../services/apiClient'
import { fetchAllPages } from '../../services/pagedCollection'
import type { QueuedOperation } from '../../db/studyDb'
import { serverVersion, type ServerEntity } from '../syncProtocol'
import { utcTimestamp } from '../syncProtocol'

const crud = createCrudAdapter({
  module: 'ankiCards', collection: '/api/anki/cards',
  createBody: payload => pick(payload, ['front', 'back', 'tags', 'note']),
  updateBody: payload => pick(payload, ['front', 'back', 'tags', 'note']),
  mapServer: server => ({
    ...pick(server, ['front', 'back', 'source', 'tags', 'note', 'interval_days', 'ease_factor', 'repetitions', 'last_quality']),
    due_at: utcTimestamp(server.due_at), created_at: utcTimestamp(server.created_at),
  }),
  list: fetch => fetchAllPages<ServerEntity>('/api/anki/cards?scope=all', fetch),
})

export const ankiCardsSyncAdapter = {
  ...crud,
  async pushReview(op: QueuedOperation) {
    if (!op.serverId || !op.operationId || !op.claimedAt) throw new Error('复习前置创建尚未确认')
    const fetch = scopedApiFetch()
    const capabilities = await fetch<{ review_attempts?: boolean }>('/api/sync/capabilities')
    if (!capabilities.review_attempts) throw Object.assign(new Error('服务器不支持安全复习同步，请先升级服务器'), { status: 426 })
    const server = await fetch<ServerEntity>(`/api/anki/cards/${op.serverId}/review`, {
      method: 'POST', body: JSON.stringify({ ...JSON.parse(op.payload), attempt_id: op.operationId,
        expected_version: op.expectedVersion ?? 0 }),
    })
    if (!serverVersion(server)) throw Object.assign(new Error('服务器未返回同步版本'), { status: 426 })
    return { server }
  },
}
