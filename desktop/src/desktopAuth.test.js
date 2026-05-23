const assert = require('node:assert/strict')
const test = require('node:test')

const {
  createDesktopAuthStore,
  normalizeSavedLogin,
} = require('./desktopAuth')

test('normalizeSavedLogin rejects incomplete saved credentials', () => {
  assert.equal(normalizeSavedLogin(null), null)
  assert.equal(normalizeSavedLogin({ username: 'alice', password: '' }), null)
  assert.equal(normalizeSavedLogin({ username: '', password: 'secret' }), null)
})

test('desktop auth store persists login through encrypted storage', () => {
  const state = new Map()
  const safeStorage = {
    isEncryptionAvailable: () => true,
    encryptString: (value) => Buffer.from(`enc:${value}`, 'utf8'),
    decryptString: (buffer) => Buffer.from(buffer).toString('utf8').replace(/^enc:/, ''),
  }
  const fs = {
    existsSync: (file) => state.has(file),
    mkdirSync: () => {},
    readFileSync: (file) => state.get(file),
    writeFileSync: (file, value) => state.set(file, value),
    rmSync: (file) => state.delete(file),
  }
  const store = createDesktopAuthStore({
    safeStorage,
    fs,
    credentialsPath: 'credentials.bin',
  })

  store.saveSavedLogin({ username: 'alice', password: 'secret', autoLogin: true })

  assert.deepEqual(store.getSavedLogin(), {
    username: 'alice',
    password: 'secret',
    autoLogin: true,
  })

  store.clearSavedLogin()
  assert.equal(store.getSavedLogin(), null)
})

test('desktop auth store refuses to persist credentials without encryption', () => {
  const store = createDesktopAuthStore({
    safeStorage: { isEncryptionAvailable: () => false },
    fs: {
      existsSync: () => false,
      mkdirSync: () => {},
      readFileSync: () => '',
      writeFileSync: () => {},
      rmSync: () => {},
    },
    credentialsPath: 'credentials.bin',
  })

  assert.throws(
    () => store.saveSavedLogin({ username: 'alice', password: 'secret', autoLogin: true }),
    /secure credential storage is unavailable/,
  )
})
