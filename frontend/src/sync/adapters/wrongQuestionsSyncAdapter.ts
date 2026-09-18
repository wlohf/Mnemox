import { createCrudAdapter, pick } from './createCrudAdapter'
import { utcTimestamp } from '../syncProtocol'

const editable = ['content', 'question_type', 'answer', 'explanation', 'difficulty', 'chapter_id', 'knowledge_point', 'mastery_status']
export const wrongQuestionsSyncAdapter = createCrudAdapter({
  module: 'wrongQuestions', collection: '/api/wrong-questions',
  createBody: payload => pick(payload, ['content', 'question_type', 'answer', 'explanation', 'difficulty', 'chapter_id', 'knowledge_point', 'user_answer']),
  updateBody: payload => pick(payload, ['mastery_status', 'next_review_at', 'increment_review_count', 'recall_difficulty']),
  // The default API response is a page, not a complete collection.
  completeSnapshot: false,
  mapServer: server => ({
    ...pick(server, [...editable, 'chapter_title', 'wrong_count', 'review_count']),
    next_review_at: utcTimestamp(server.next_review_at), last_wrong_at: utcTimestamp(server.last_wrong_at),
    created_at: utcTimestamp(server.created_at),
  }),
})
