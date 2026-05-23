const assert = require('node:assert/strict')
const test = require('node:test')

const { createReminderManager, normalizeReminderPayload } = require('./desktopReminder')

test('normalizeReminderPayload rejects invalid reminders', () => {
  assert.equal(normalizeReminderPayload(null), null)
  assert.equal(normalizeReminderPayload({ dueAt: Date.now() + 1000 }), null)
  assert.equal(normalizeReminderPayload({ taskName: 'Focus', dueAt: 0 }), null)
})

test('reminder manager schedules and clears active reminders', () => {
  const timers = []
  const cleared = []
  const sent = []
  const manager = createReminderManager({
    now: () => 1000,
    setTimeoutFn: (fn, delay) => {
      timers.push({ fn, delay })
      return timers.length
    },
    clearTimeoutFn: (id) => cleared.push(id),
    notify: (payload) => sent.push(payload),
    emit: () => {},
  })

  manager.setReminder({
    taskName: 'Read chapter',
    dueAt: 6000,
    mode: 'focus',
  })

  assert.equal(timers.length, 1)
  assert.equal(timers[0].delay, 5000)
  assert.deepEqual(manager.getActiveReminder(), {
    taskName: 'Read chapter',
    dueAt: 6000,
    mode: 'focus',
  })

  manager.clearReminder()
  assert.deepEqual(cleared, [1])
  assert.equal(manager.getActiveReminder(), null)
  assert.deepEqual(sent, [])
})

test('reminder manager fires due reminders immediately and emits payload', () => {
  const sent = []
  const emitted = []
  const manager = createReminderManager({
    now: () => 10_000,
    setTimeoutFn: (fn, delay) => {
      assert.equal(delay, 0)
      fn()
      return 1
    },
    clearTimeoutFn: () => {},
    notify: (payload) => sent.push(payload),
    emit: (channel, payload) => emitted.push({ channel, payload }),
  })

  manager.setReminder({
    taskName: 'Break',
    dueAt: 9_000,
    mode: 'break',
  })

  assert.equal(manager.getActiveReminder(), null)
  assert.equal(sent[0].title, '休息时间到')
  assert.equal(sent[0].body, 'Break')
  assert.deepEqual(emitted[0], {
    channel: 'desktop-reminder:triggered',
    payload: { taskName: 'Break', mode: 'break', dueAt: 9000 },
  })
})
