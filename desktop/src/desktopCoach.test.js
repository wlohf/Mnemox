const assert = require('node:assert/strict')
const test = require('node:test')

const { normalizeCoachNotificationPayload } = require('./desktopCoach')

test('normalizeCoachNotificationPayload rejects invalid payloads', () => {
  assert.equal(normalizeCoachNotificationPayload(null), null)
  assert.equal(normalizeCoachNotificationPayload({ title: 'Coach', body: 'Body' }), null)
  assert.equal(normalizeCoachNotificationPayload({ id: 'n1', title: '', body: 'Body' }), null)
})

test('normalizeCoachNotificationPayload trims route and content', () => {
  assert.deepEqual(
    normalizeCoachNotificationPayload({
      id: '  n1  ',
      title: '  Coach  ',
      body: '  Start small  ',
      route: '  /pomodoro  ',
    }),
    {
      id: 'n1',
      title: 'Coach',
      body: 'Start small',
      route: '/pomodoro',
    },
  )
})
