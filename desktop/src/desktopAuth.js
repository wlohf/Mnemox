const path = require('node:path')

function normalizeSavedLogin(value) {
  if (!value || typeof value !== 'object') return null
  const username = String(value.username || '').trim()
  const password = String(value.password || '')
  if (!username || !password) return null
  return {
    username,
    password,
    autoLogin: value.autoLogin === true,
  }
}

function createDesktopAuthStore({ safeStorage, fs, credentialsPath }) {
  function ensureEncryptionAvailable() {
    if (!safeStorage || typeof safeStorage.isEncryptionAvailable !== 'function' || !safeStorage.isEncryptionAvailable()) {
      throw new Error('secure credential storage is unavailable')
    }
  }

  function getSavedLogin() {
    ensureEncryptionAvailable()
    if (!fs.existsSync(credentialsPath)) return null
    try {
      const encrypted = fs.readFileSync(credentialsPath)
      const decrypted = safeStorage.decryptString(encrypted)
      return normalizeSavedLogin(JSON.parse(decrypted))
    } catch {
      return null
    }
  }

  function saveSavedLogin(payload) {
    const normalized = normalizeSavedLogin(payload)
    if (!normalized) {
      clearSavedLogin()
      return null
    }
    ensureEncryptionAvailable()
    fs.mkdirSync(path.dirname(credentialsPath), { recursive: true })
    const encrypted = safeStorage.encryptString(JSON.stringify(normalized))
    fs.writeFileSync(credentialsPath, encrypted)
    return null
  }

  function clearSavedLogin() {
    try {
      if (fs.existsSync(credentialsPath)) {
        fs.rmSync(credentialsPath, { force: true })
      }
    } catch {
      // Clearing credentials should not block logout.
    }
    return null
  }

  return {
    getSavedLogin,
    saveSavedLogin,
    clearSavedLogin,
  }
}

module.exports = {
  createDesktopAuthStore,
  normalizeSavedLogin,
}
