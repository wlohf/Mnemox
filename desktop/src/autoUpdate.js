const fs = require('node:fs')
const path = require('node:path')

function summarizeUpdateError(error) {
  const text = String(error || '').trim()
  const lower = text.toLowerCase()

  if (!text) {
    return {
      message: '更新失败，请稍后重试',
      error: null,
    }
  }

  if (lower.includes('unable to find latest version on github') || lower.includes('cannot parse releases feed')) {
    return {
      message: '未找到可用发布版本，请先发布 GitHub Release',
      error: 'GitHub Release 不存在，或 latest.yml / 安装包尚未发布',
    }
  }

  if (lower.includes('404')) {
    return {
      message: '更新源不存在或版本未发布',
      error: '更新地址返回 404，请检查 GitHub Release 或更新清单',
    }
  }

  if (lower.includes('timeout')) {
    return {
      message: '检查更新超时，请稍后重试',
      error: '网络超时',
    }
  }

  return {
    message: '检查更新失败，请稍后重试',
    error: text.split('\n')[0].slice(0, 200),
  }
}

function buildInitialUpdateState() {
  return {
    phase: 'idle',
    version: null,
    currentVersion: null,
    releaseNotes: null,
    releaseDate: null,
    progressPercent: 0,
    bytesPerSecond: 0,
    transferred: 0,
    total: 0,
    message: '',
    error: null,
  }
}

function defaultUpdateSettings() {
  return {
    autoCheck: true,
    intervalMinutes: 360,
    lastCheckedAt: null,
  }
}

function readUpdateSettings(settingsPath) {
  const defaults = defaultUpdateSettings()
  if (!fs.existsSync(settingsPath)) {
    return defaults
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(settingsPath, 'utf8'))
    return {
      autoCheck: parsed.autoCheck !== false,
      intervalMinutes: Number.isFinite(parsed.intervalMinutes) ? parsed.intervalMinutes : defaults.intervalMinutes,
      lastCheckedAt: typeof parsed.lastCheckedAt === 'number' ? parsed.lastCheckedAt : null,
    }
  } catch {
    return defaults
  }
}

function writeUpdateSettings(settingsPath, settings) {
  fs.mkdirSync(path.dirname(settingsPath), { recursive: true })
  fs.writeFileSync(settingsPath, JSON.stringify(settings), 'utf8')
}

function reduceUpdateState(state, event) {
  const current = { ...buildInitialUpdateState(), ...state }
  const payload = event?.payload || {}
  switch (event?.type) {
    case 'checking':
      return {
        ...current,
        phase: 'checking',
        message: '正在检查更新',
        error: null,
      }
    case 'update-available':
      return {
        ...current,
        phase: 'available',
        version: payload.version || current.version,
        releaseNotes: payload.releaseNotes || null,
        releaseDate: payload.releaseDate || null,
        message: payload.message || '发现新版本',
        error: null,
      }
    case 'update-not-available':
      return {
        ...current,
        phase: 'not-available',
        version: payload.version || current.version,
        message: payload.message || '当前已是最新版本',
        error: null,
      }
    case 'download-progress':
      return {
        ...current,
        phase: 'downloading',
        progressPercent: Math.max(0, Math.min(100, Math.round(payload.percent || 0))),
        bytesPerSecond: payload.bytesPerSecond || 0,
        transferred: payload.transferred || 0,
        total: payload.total || 0,
        message: payload.message || '正在下载更新',
        error: null,
      }
    case 'update-downloaded':
      return {
        ...current,
        phase: 'downloaded',
        version: payload.version || current.version,
        message: payload.message || '更新已下载，准备安装',
        error: null,
      }
    case 'error':
      return {
        ...current,
        phase: 'error',
        message: payload.message || '更新失败',
        error: payload.error || payload.message || '更新失败',
      }
    default:
      return current
  }
}

function shouldAutoCheckForUpdates(enabled, lastCheckedAt, intervalMinutes, now = Date.now()) {
  if (!enabled) return false
  if (!lastCheckedAt) return true
  const intervalMs = Math.max(5, intervalMinutes || 0) * 60 * 1000
  return now - lastCheckedAt >= intervalMs
}

function createAutoUpdateManager({ app, onStateChange = () => {} }) {
  const { autoUpdater } = require('electron-updater')
  let state = {
    ...buildInitialUpdateState(),
    currentVersion: app.getVersion(),
  }

  const emit = (type, payload = {}) => {
    state = reduceUpdateState(state, { type, payload })
    onStateChange(state)
    return state
  }

  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = false
  autoUpdater.disableWebInstaller = false

  autoUpdater.on('checking-for-update', () => emit('checking'))
  autoUpdater.on('update-available', (info) =>
    emit('update-available', {
      version: info?.version || null,
      releaseNotes: typeof info?.releaseNotes === 'string' ? info.releaseNotes : null,
      releaseDate: info?.releaseDate || null,
    }),
  )
  autoUpdater.on('update-not-available', (info) =>
    emit('update-not-available', {
      version: info?.version || null,
    }),
  )
  autoUpdater.on('download-progress', (progress) =>
    emit('download-progress', progress || {}),
  )
  autoUpdater.on('update-downloaded', (info) =>
    emit('update-downloaded', {
      version: info?.version || null,
    }),
  )
  autoUpdater.on('error', (error) =>
    emit('error', summarizeUpdateError(error)),
  )

  return {
    getState() {
      return state
    },
    async checkForUpdates() {
      emit('checking')
      await autoUpdater.checkForUpdates()
      return state
    },
    async downloadUpdate() {
      await autoUpdater.downloadUpdate()
      return state
    },
    async quitAndInstall() {
      autoUpdater.quitAndInstall(false, true)
    },
  }
}

module.exports = {
  buildInitialUpdateState,
  createAutoUpdateManager,
  defaultUpdateSettings,
  readUpdateSettings,
  reduceUpdateState,
  shouldAutoCheckForUpdates,
  writeUpdateSettings,
}
