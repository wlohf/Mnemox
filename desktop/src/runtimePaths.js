const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')

function getRepoRoot(appPath) {
  return path.resolve(appPath, '..')
}

function getBackendExecutable({ isPackaged, resourcesPath, appPath }) {
  if (isPackaged) {
    return path.join(resourcesPath, 'backend', 'mnemox-backend', 'mnemox-backend.exe')
  }
  return path.join(getRepoRoot(appPath), 'backend', 'venv', 'Scripts', 'python.exe')
}

function getBackendArgs({ isPackaged, appPath }) {
  if (isPackaged) {
    return []
  }
  return ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1']
}

function getBackendCwd({ isPackaged, resourcesPath, appPath }) {
  if (isPackaged) {
    return path.join(resourcesPath, 'backend', 'mnemox-backend')
  }
  return path.join(getRepoRoot(appPath), 'backend')
}

function getFrontendDistDir({ isPackaged, resourcesPath, appPath }) {
  if (isPackaged) {
    return path.join(resourcesPath, 'frontend', 'dist')
  }
  return path.join(getRepoRoot(appPath), 'frontend', 'dist')
}

function sqliteUrlFromPath(dbPath) {
  return `sqlite+aiosqlite:///${path.resolve(dbPath).replace(/\\/g, '/')}`
}

function ensureStableSecret(userData) {
  fs.mkdirSync(userData, { recursive: true })
  const secretPath = path.join(userData, 'desktop-secret.txt')
  if (fs.existsSync(secretPath)) {
    const existing = fs.readFileSync(secretPath, 'utf8').trim()
    if (existing.length >= 32) {
      return existing
    }
  }
  const secret = crypto.randomBytes(48).toString('base64url')
  fs.writeFileSync(secretPath, secret, { encoding: 'utf8', mode: 0o600 })
  return secret
}

function buildBackendEnv({ baseEnv = process.env, port, userData, frontendDistDir, secretKey }) {
  const dataDir = path.join(userData, 'data')
  fs.mkdirSync(dataDir, { recursive: true })
  const updateManifestUrl = baseEnv.APP_UPDATE_MANIFEST_URL || 'https://raw.githubusercontent.com/wlohf/Mnemox/main/release-manifest/latest.json'
  return {
    ...baseEnv,
    HOST: '127.0.0.1',
    PORT: String(port),
    DEBUG: 'False',
    ENVIRONMENT: 'desktop',
    SERVE_FRONTEND: 'True',
    FRONTEND_DIST_DIR: frontendDistDir,
    MNEMOX_DATA_DIR: dataDir,
    DATABASE_URL: sqliteUrlFromPath(path.join(dataDir, 'study.db')),
    SECRET_KEY: secretKey,
    AI_KEY_ENCRYPTION_SECRET: secretKey,
    APP_UPDATE_MANIFEST_URL: updateManifestUrl,
    RAG_ENABLED: baseEnv.RAG_ENABLED || 'False',
    CORS_ORIGINS: JSON.stringify([`http://127.0.0.1:${port}`, `http://localhost:${port}`]),
    MATERIAL_UPLOAD_MAX_MB: baseEnv.MATERIAL_UPLOAD_MAX_MB || '200',
    MAX_REQUEST_BODY_MB: baseEnv.MAX_REQUEST_BODY_MB || '20',
    RATE_LIMIT_ENABLED: baseEnv.RATE_LIMIT_ENABLED || 'False',
  }
}

module.exports = {
  buildBackendEnv,
  ensureStableSecret,
  getBackendArgs,
  getBackendCwd,
  getBackendExecutable,
  getFrontendDistDir,
  sqliteUrlFromPath,
}
