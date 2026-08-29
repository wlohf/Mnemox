function parseUrl(value) {
  try {
    return new URL(String(value || ''))
  } catch {
    return null
  }
}

function isTrustedRendererUrl(value, backendPort) {
  const url = parseUrl(value)
  if (!url || url.protocol !== 'http:') return false
  if (!['127.0.0.1', 'localhost'].includes(url.hostname)) return false
  return url.port === String(backendPort)
}

function isSafeExternalUrl(value) {
  const url = parseUrl(value)
  return Boolean(url && url.protocol === 'https:')
}

module.exports = {
  isSafeExternalUrl,
  isTrustedRendererUrl,
}
