function normalizeReminderPayload(value) {
  if (!value || typeof value !== 'object') return null
  const taskName = String(value.taskName || '').trim()
  const dueAt = Number(value.dueAt)
  const mode = value.mode === 'break' ? 'break' : 'focus'
  if (!taskName || !Number.isFinite(dueAt) || dueAt <= 0) return null
  return { taskName, dueAt, mode }
}

function createReminderManager({
  now = () => Date.now(),
  setTimeoutFn = setTimeout,
  clearTimeoutFn = clearTimeout,
  notify,
  emit,
}) {
  let activeReminder = null
  let timer = null

  function clearReminder() {
    if (timer !== null) {
      clearTimeoutFn(timer)
      timer = null
    }
    activeReminder = null
    return null
  }

  function fireReminder(payload) {
    timer = null
    activeReminder = null
    const isBreak = payload.mode === 'break'
    const notificationPayload = {
      title: isBreak ? '休息时间到' : '番茄钟完成',
      body: payload.taskName,
    }
    notify(notificationPayload)
    emit('desktop-reminder:triggered', payload)
  }

  function setReminder(payload) {
    const normalized = normalizeReminderPayload(payload)
    clearReminder()
    if (!normalized) return null
    activeReminder = normalized
    const delay = Math.max(0, normalized.dueAt - now())
    timer = setTimeoutFn(() => fireReminder(normalized), delay)
    return null
  }

  function getActiveReminder() {
    return activeReminder
  }

  return {
    setReminder,
    clearReminder,
    getActiveReminder,
  }
}

module.exports = {
  createReminderManager,
  normalizeReminderPayload,
}
