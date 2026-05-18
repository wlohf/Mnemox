const assert = require('node:assert/strict')
const path = require('node:path')
const test = require('node:test')

const {
  buildBackendEnv,
  getBackendExecutable,
  getFrontendDistDir,
  sqliteUrlFromPath,
} = require('./runtimePaths')

test('packaged paths point to bundled backend and frontend resources', () => {
  const resourcesPath = path.join('C:', 'Program Files', 'Mnemox', 'resources')

  assert.equal(
    getBackendExecutable({ isPackaged: true, resourcesPath, appPath: 'ignored' }),
    path.join(resourcesPath, 'backend', 'mnemox-backend', 'mnemox-backend.exe'),
  )
  assert.equal(
    getFrontendDistDir({ isPackaged: true, resourcesPath, appPath: 'ignored' }),
    path.join(resourcesPath, 'frontend', 'dist'),
  )
})

test('development paths point back to repository backend and frontend build', () => {
  const appPath = path.join('E:', 'xyleisure', 'Mnemox', 'Mnemox', 'desktop')
  const repoRoot = path.dirname(appPath)

  assert.equal(
    getBackendExecutable({ isPackaged: false, resourcesPath: 'ignored', appPath }),
    path.join(repoRoot, 'backend', 'venv', 'Scripts', 'python.exe'),
  )
  assert.equal(
    getFrontendDistDir({ isPackaged: false, resourcesPath: 'ignored', appPath }),
    path.join(repoRoot, 'frontend', 'dist'),
  )
})

test('backend environment uses stable user data and localhost-only port', () => {
  const resourcesPath = path.join('C:', 'Program Files', 'Mnemox', 'resources')
  const userData = path.join('C:', 'Users', 'me', 'AppData', 'Roaming', 'Mnemox')
  const env = buildBackendEnv({
    baseEnv: {},
    port: 18765,
    userData,
    frontendDistDir: path.join(resourcesPath, 'frontend', 'dist'),
    secretKey: 'stable-secret',
  })

  assert.equal(env.HOST, '127.0.0.1')
  assert.equal(env.PORT, '18765')
  assert.equal(env.SERVE_FRONTEND, 'True')
  assert.equal(env.RAG_ENABLED, 'False')
  assert.equal(env.MNEMOX_DATA_DIR, path.join(userData, 'data'))
  assert.equal(env.FRONTEND_DIST_DIR, path.join(resourcesPath, 'frontend', 'dist'))
  assert.match(env.DATABASE_URL, /^sqlite\+aiosqlite:\/\//)
  assert.match(env.DATABASE_URL, /study\.db$/)
  assert.equal(env.SECRET_KEY, 'stable-secret')
  assert.equal(env.AI_KEY_ENCRYPTION_SECRET, 'stable-secret')
})

test('sqliteUrlFromPath formats Windows paths for SQLAlchemy', () => {
  const dbPath = path.join('C:', 'Users', 'me', 'AppData', 'Roaming', 'Mnemox', 'data', 'study.db')

  assert.equal(sqliteUrlFromPath(dbPath), 'sqlite+aiosqlite:///C:/Users/me/AppData/Roaming/Mnemox/data/study.db')
})
