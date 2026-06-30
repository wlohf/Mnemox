function trimText(value, maxLength) {
  return String(value || '').trim().slice(0, maxLength)
}

function normalizeCoachNotificationPayload(value) {
  if (!value || typeof value !== 'object') return null
  const id = trimText(value.id, 80)
  const title = trimText(value.title, 80)
  const body = trimText(value.body, 240)
  const route = value.route ? trimText(value.route, 200) : null
  if (!id || !title || !body) return null
  return { id, title, body, route }
}

module.exports = {
  normalizeCoachNotificationPayload,
}
