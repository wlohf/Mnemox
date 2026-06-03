const path = require('node:path')

const MAX_PREFERENCE_BYTES = 64 * 1024
const VALID_PREFERENCE_KEY = /^[a-zA-Z0-9_.:-]{1,80}$/

function isValidPreferenceKey(key) {
  return typeof key === 'string' && VALID_PREFERENCE_KEY.test(key)
}

function readPreferenceStore(fs, preferencesPath) {
  try {
    const raw = fs.readFileSync(preferencesPath, 'utf8')
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed
    }
  } catch {
    // Missing or invalid preference files fall back to an empty store.
  }
  return {}
}

function writePreferenceStore(fs, preferencesPath, store) {
  const dir = path.dirname(preferencesPath)
  fs.mkdirSync(dir, { recursive: true })
  const payload = JSON.stringify(store, null, 2)
  const tmpPath = `${preferencesPath}.tmp`
  fs.writeFileSync(tmpPath, payload, 'utf8')
  fs.renameSync(tmpPath, preferencesPath)
}

function createDesktopPreferenceStore({ fs, preferencesPath }) {
  return {
    get(key) {
      if (!isValidPreferenceKey(key)) return null
      const store = readPreferenceStore(fs, preferencesPath)
      return Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null
    },

    set(key, value) {
      if (!isValidPreferenceKey(key)) {
        throw new Error('Invalid desktop preference key')
      }

      const encoded = JSON.stringify(value)
      if (encoded && Buffer.byteLength(encoded, 'utf8') > MAX_PREFERENCE_BYTES) {
        throw new Error('Desktop preference value is too large')
      }

      const store = readPreferenceStore(fs, preferencesPath)
      if (value === undefined) {
        delete store[key]
      } else {
        store[key] = value
      }
      writePreferenceStore(fs, preferencesPath, store)
      return Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null
    },
  }
}

module.exports = {
  createDesktopPreferenceStore,
  isValidPreferenceKey,
  readPreferenceStore,
}
