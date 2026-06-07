const { app, BrowserWindow, Menu, Notification, Tray, dialog, shell, ipcMain, safeStorage, nativeImage } = require('electron')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const net = require('node:net')
const path = require('node:path')
const {
  createAutoUpdateManager,
  readUpdateSettings,
  shouldAutoCheckForUpdates,
  writeUpdateSettings,
} = require('./autoUpdate')

const {
  buildBackendEnv,
  ensureStableSecret,
  getBackendArgs,
  getBackendCwd,
  getBackendExecutable,
  getFrontendDistDir,
} = require('./runtimePaths')
const { createDesktopAuthStore } = require('./desktopAuth')
const { createDesktopPreferenceStore } = require('./desktopPreferences')
const { createReminderManager } = require('./desktopReminder')
const { createTrayIcon } = require('./trayIcon')

app.setName('Mnemox')

const singleInstanceLock = app.requestSingleInstanceLock()
if (!singleInstanceLock) {
  app.quit()
}

let backendProcess = null
let mainWindow = null
let backendPort = null
let autoUpdateManager = null
let updateSettingsPath = null
let desktopAuthStore = null
let desktopPreferenceStore = null
let reminderManager = null
let tray = null
let isQuitting = false
let startupReady = false
let pendingShowMainWindow = false

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      const port = address.port
      server.close(() => resolve(port))
    })
  })
}

async function waitForHealth(port, timeoutMs = 45000) {
  const deadline = Date.now() + timeoutMs
  let lastError = null
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/health`)
      if (response.ok) {
        return
      }
      lastError = new Error(`health returned ${response.status}`)
    } catch (error) {
      lastError = error
    }
    await wait(750)
  }
  throw lastError || new Error('backend health check timed out')
}

async function startBackend() {
  backendPort = await findFreePort()
  const resourcesPath = process.resourcesPath
  const appPath = app.getAppPath()
  const frontendDistDir = getFrontendDistDir({
    isPackaged: app.isPackaged,
    resourcesPath,
    appPath,
  })
  const executable = getBackendExecutable({
    isPackaged: app.isPackaged,
    resourcesPath,
    appPath,
  })

  if (!fs.existsSync(executable)) {
    throw new Error(`Backend executable not found: ${executable}`)
  }
  if (!fs.existsSync(path.join(frontendDistDir, 'index.html'))) {
    throw new Error(`Frontend build not found: ${frontendDistDir}`)
  }

  const userData = app.getPath('userData')
  const secretKey = ensureStableSecret(userData)
  const env = buildBackendEnv({
    baseEnv: process.env,
    port: backendPort,
    userData,
    frontendDistDir,
    secretKey,
  })
  const args = [
    ...getBackendArgs({ isPackaged: app.isPackaged, appPath }),
    ...(app.isPackaged ? [] : ['--port', String(backendPort)]),
  ]
  const cwd = getBackendCwd({
    isPackaged: app.isPackaged,
    resourcesPath,
    appPath,
  })

  backendProcess = spawn(executable, args, {
    cwd,
    env,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  const logPath = path.join(userData, 'backend.log')
  const logStream = fs.createWriteStream(logPath, { flags: 'a' })
  backendProcess.stdout.pipe(logStream)
  backendProcess.stderr.pipe(logStream)
  backendProcess.once('exit', (code, signal) => {
    logStream.write(`\n[desktop] backend exited code=${code} signal=${signal}\n`)
  })

  await waitForHealth(backendPort)
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 680,
    title: 'Mnemox',
    backgroundColor: '#f7f7f2',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  mainWindow.loadURL(`http://127.0.0.1:${backendPort}/dashboard`)
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })
  mainWindow.on('close', (event) => {
    if (isQuitting) return
    if (!tray) return
    event.preventDefault()
    mainWindow.hide()
  })
}

function showMainWindow() {
  if (!startupReady) {
    pendingShowMainWindow = true
    return
  }
  if (!mainWindow || mainWindow.isDestroyed()) {
    createWindow()
    return
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore()
  }
  mainWindow.show()
  mainWindow.focus()
}

function createTray() {
  if (tray) return
  tray = new Tray(createTrayIcon(nativeImage))
  tray.setToolTip('Mnemox')
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开 Mnemox', click: showMainWindow },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        isQuitting = true
        app.quit()
      },
    },
  ]))
  tray.on('double-click', showMainWindow)
}

function createTraySafely() {
  try {
    createTray()
  } catch (error) {
    if (tray) {
      try {
        tray.destroy()
      } catch {
        // ignore tray cleanup failures
      }
      tray = null
    }
    console.error('[desktop] failed to create tray', error)
  }
}

function registerAutoUpdater() {
  autoUpdateManager = createAutoUpdateManager({
    app,
    beforeInstall: async () => {
      stopBackend()
    },
    onStateChange: (state) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('desktop-updater:state', state)
      }
    },
  })

  ipcMain.handle('desktop-updater:get-state', () => autoUpdateManager.getState())
  ipcMain.handle('desktop-updater:check', () => autoUpdateManager.checkForUpdates())
  ipcMain.handle('desktop-updater:download', () => autoUpdateManager.downloadUpdate())
  ipcMain.handle('desktop-updater:download-installer-and-run', (_event, payload) => autoUpdateManager.downloadInstallerAndRun(payload))
  ipcMain.handle('desktop-updater:get-settings', () => readUpdateSettings(updateSettingsPath))
  ipcMain.handle('desktop-updater:set-settings', (_event, settings) => {
    const current = readUpdateSettings(updateSettingsPath)
    const next = {
      autoCheck: settings?.autoCheck !== false,
      intervalMinutes: Number.isFinite(settings?.intervalMinutes) ? settings.intervalMinutes : current.intervalMinutes,
      lastCheckedAt: current.lastCheckedAt,
    }
    writeUpdateSettings(updateSettingsPath, next)
    return next
  })
  ipcMain.handle('desktop-updater:quit-and-install', async () => {
    stopBackend()
    await autoUpdateManager.quitAndInstall()
    return null
  })
}

function registerDesktopAuth() {
  desktopAuthStore = createDesktopAuthStore({
    safeStorage,
    fs,
    credentialsPath: path.join(app.getPath('userData'), 'saved-login.bin'),
  })
  ipcMain.handle('desktop-auth:get-saved-login', () => desktopAuthStore.getSavedLogin())
  ipcMain.handle('desktop-auth:save-login', (_event, payload) => desktopAuthStore.saveSavedLogin(payload))
  ipcMain.handle('desktop-auth:clear-saved-login', () => desktopAuthStore.clearSavedLogin())
}

function registerDesktopPreferences() {
  desktopPreferenceStore = createDesktopPreferenceStore({
    fs,
    preferencesPath: path.join(app.getPath('userData'), 'desktop-preferences.json'),
  })
  ipcMain.handle('desktop-preferences:get', (_event, key) => desktopPreferenceStore.get(key))
  ipcMain.handle('desktop-preferences:set', (_event, key, value) => desktopPreferenceStore.set(key, value))
}

function registerDesktopReminder() {
  reminderManager = createReminderManager({
    notify: ({ title, body }) => {
      const notice = new Notification({
        title,
        body,
        silent: false,
      })
      notice.on('click', showMainWindow)
      notice.show()
      shell.beep()
    },
    emit: (channel, payload) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send(channel, payload)
      }
    },
  })
  ipcMain.handle('desktop-reminder:set', (_event, payload) => reminderManager.setReminder(payload))
  ipcMain.handle('desktop-reminder:clear', () => reminderManager.clearReminder())
}

async function maybeAutoCheckForUpdates() {
  const { autoCheck, intervalMinutes, lastCheckedAt } = readUpdateSettings(updateSettingsPath)

  if (!shouldAutoCheckForUpdates(autoCheck, lastCheckedAt, intervalMinutes)) {
    return
  }

  try {
    await autoUpdateManager.checkForUpdates()
    writeUpdateSettings(updateSettingsPath, {
      autoCheck,
      intervalMinutes,
      lastCheckedAt: Date.now(),
    })
  } catch {
    // ignore background update failures
  }
}

function stopBackend() {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill()
  }
  backendProcess = null
}

if (singleInstanceLock) {
  app.whenReady().then(async () => {
    try {
      updateSettingsPath = path.join(app.getPath('userData'), 'desktop-update-settings.json')
      await startBackend()
      registerAutoUpdater()
      registerDesktopAuth()
      registerDesktopPreferences()
      registerDesktopReminder()
      createWindow()
      startupReady = true
      createTraySafely()
      if (pendingShowMainWindow) {
        pendingShowMainWindow = false
        showMainWindow()
      }
      void maybeAutoCheckForUpdates()
    } catch (error) {
      await dialog.showMessageBox({
        type: 'error',
        title: 'Mnemox 启动失败',
        message: 'Mnemox 启动失败',
        detail: String(error && error.stack ? error.stack : error),
      })
      app.quit()
    }
  })

  app.on('second-instance', showMainWindow)

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin' && tray) {
      // Keep the tray process alive so desktop reminders still fire.
      return
    }
    app.quit()
  })

  app.on('before-quit', () => {
    isQuitting = true
    if (reminderManager) {
      reminderManager.clearReminder()
    }
    stopBackend()
  })
}
