const fs = require('node:fs')
const https = require('node:https')
const path = require('node:path')
const { spawn } = require('node:child_process')

function normalizeInstallerFileName(fileName) {
  const cleaned = String(fileName || '')
    .trim()
    .replace(/[<>:"/\\|?*\x00-\x1F]/g, '_')

  if (!cleaned || !cleaned.toLowerCase().endsWith('.exe')) {
    return null
  }
  return cleaned
}

function getInstallerFileName(downloadUrl, version) {
  try {
    const url = new URL(downloadUrl)
    const basename = path.posix.basename(url.pathname)
    const decoded = decodeURIComponent(basename)
    const fileName = normalizeInstallerFileName(decoded)
    if (fileName) return fileName
  } catch {
    // Fall back to version-based file name below.
  }

  const normalizedVersion = String(version || '').trim().replace(/^v/i, '')
  return normalizedVersion
    ? `Mnemox-Setup-${normalizedVersion}.exe`
    : 'Mnemox-Setup-update.exe'
}

function assertDownloadUrl(downloadUrl) {
  let url
  try {
    url = new URL(downloadUrl)
  } catch {
    throw new Error('更新安装包地址无效')
  }
  if (url.protocol !== 'https:') {
    throw new Error('更新安装包地址必须使用 HTTPS')
  }
  return url
}

function downloadFile(downloadUrl, destinationPath, onProgress = () => {}, redirectCount = 0) {
  if (redirectCount > 5) {
    return Promise.reject(new Error('更新安装包下载重定向次数过多'))
  }

  const url = assertDownloadUrl(downloadUrl)
  const tempPath = `${destinationPath}.download`

  return new Promise((resolve, reject) => {
    const request = https.get(url, {
      headers: {
        'User-Agent': 'Mnemox-Desktop-Updater',
        Accept: 'application/octet-stream,*/*',
      },
    }, (response) => {
      const statusCode = response.statusCode || 0
      if ([301, 302, 303, 307, 308].includes(statusCode) && response.headers.location) {
        response.resume()
        const redirectedUrl = new URL(response.headers.location, url).toString()
        resolve(downloadFile(redirectedUrl, destinationPath, onProgress, redirectCount + 1))
        return
      }

      if (statusCode < 200 || statusCode >= 300) {
        response.resume()
        reject(new Error(`更新安装包下载失败：HTTP ${statusCode}`))
        return
      }

      fs.mkdirSync(path.dirname(destinationPath), { recursive: true })
      fs.rmSync(tempPath, { force: true })

      const total = Number.parseInt(String(response.headers['content-length'] || '0'), 10) || 0
      const startedAt = Date.now()
      let transferred = 0
      let lastProgressAt = 0
      const file = fs.createWriteStream(tempPath)

      const emitProgress = (force = false) => {
        const now = Date.now()
        if (!force && now - lastProgressAt < 500) return
        lastProgressAt = now
        const elapsedSeconds = Math.max((now - startedAt) / 1000, 0.001)
        onProgress({
          percent: total > 0 ? (transferred / total) * 100 : 0,
          bytesPerSecond: Math.round(transferred / elapsedSeconds),
          transferred,
          total,
        })
      }

      response.on('data', (chunk) => {
        transferred += chunk.length
        emitProgress()
      })

      response.on('error', (error) => {
        file.destroy()
        fs.rmSync(tempPath, { force: true })
        reject(error)
      })

      file.on('error', (error) => {
        fs.rmSync(tempPath, { force: true })
        reject(error)
      })

      file.on('finish', () => {
        file.close((error) => {
          if (error) {
            fs.rmSync(tempPath, { force: true })
            reject(error)
            return
          }
          try {
            fs.rmSync(destinationPath, { force: true })
            fs.renameSync(tempPath, destinationPath)
            emitProgress(true)
            resolve(destinationPath)
          } catch (renameError) {
            fs.rmSync(tempPath, { force: true })
            reject(renameError)
          }
        })
      })

      response.pipe(file)
    })

    request.setTimeout(60000, () => {
      request.destroy(new Error('更新安装包下载超时'))
    })
    request.on('error', (error) => {
      fs.rmSync(tempPath, { force: true })
      reject(error)
    })
  })
}

function launchInstaller(installerPath) {
  const child = spawn(installerPath, [], {
    detached: true,
    stdio: 'ignore',
    windowsHide: false,
  })
  child.unref()
}

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

function createAutoUpdateManager({ app, onStateChange = () => {}, beforeInstall = () => {} }) {
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
      if (state.phase === 'downloaded') {
        await beforeInstall()
        autoUpdater.quitAndInstall(false, true)
      }
      return state
    },
    async downloadInstallerAndRun(payload = {}) {
      const downloadUrl = String(payload.url || '').trim()
      if (!downloadUrl) {
        const error = new Error('缺少更新安装包下载地址')
        emit('error', {
          message: '缺少更新安装包下载地址',
          error: error.message,
        })
        throw error
      }

      const version = payload.version || state.version
      const installerName = getInstallerFileName(downloadUrl, version)
      const installerPath = path.join(app.getPath('userData'), 'updates', installerName)

      try {
        emit('download-progress', {
          percent: 0,
          transferred: 0,
          total: 0,
          message: '正在下载更新安装包',
        })
        await downloadFile(downloadUrl, installerPath, (progress) => {
          emit('download-progress', {
            ...progress,
            message: '正在下载更新安装包',
          })
        })
        emit('update-downloaded', {
          version,
          message: '更新已下载，正在启动安装程序',
        })
        await beforeInstall()
        launchInstaller(installerPath)
        setTimeout(() => app.quit(), 500)
        return state
      } catch (error) {
        emit('error', {
          message: '下载安装包失败，请稍后重试',
          error: String(error && error.message ? error.message : error),
        })
        throw error
      }
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
  getInstallerFileName,
  readUpdateSettings,
  reduceUpdateState,
  shouldAutoCheckForUpdates,
  writeUpdateSettings,
}
