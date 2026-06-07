const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')

const {
  defaultUpdateSettings,
  getInstallerFileName,
  readUpdateSettings,
  reduceUpdateState,
  writeUpdateSettings,
  shouldAutoCheckForUpdates,
} = require('./autoUpdate')

test('reduceUpdateState reports available update metadata', () => {
  const next = reduceUpdateState(
    { phase: 'idle', progressPercent: 0, message: '' },
    {
      type: 'update-available',
      payload: {
        version: '1.0.1',
        releaseDate: '2026-05-18T12:00:00Z',
        releaseNotes: 'Bug fixes',
      },
    },
  )

  assert.equal(next.phase, 'available')
  assert.equal(next.version, '1.0.1')
  assert.equal(next.releaseNotes, 'Bug fixes')
})

test('reduceUpdateState tracks download progress and downloaded state', () => {
  const downloading = reduceUpdateState(
    { phase: 'available', progressPercent: 0, message: '' },
    {
      type: 'download-progress',
      payload: { percent: 42.4, transferred: 420, total: 1000 },
    },
  )
  assert.equal(downloading.phase, 'downloading')
  assert.equal(downloading.progressPercent, 42)

  const downloaded = reduceUpdateState(downloading, {
    type: 'update-downloaded',
    payload: { version: '1.0.1' },
  })
  assert.equal(downloaded.phase, 'downloaded')
  assert.equal(downloaded.version, '1.0.1')
})

test('shouldAutoCheckForUpdates honors enabled flag and minimum interval', () => {
  const now = Date.now()
  assert.equal(shouldAutoCheckForUpdates(true, null, 30, now), true)
  assert.equal(shouldAutoCheckForUpdates(false, null, 30, now), false)
  assert.equal(shouldAutoCheckForUpdates(true, now - 5 * 60 * 1000, 30, now), false)
  assert.equal(shouldAutoCheckForUpdates(true, now - 31 * 60 * 1000, 30, now), true)
})

test('readUpdateSettings falls back to defaults and writeUpdateSettings persists values', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mnemox-updater-'))
  const settingsPath = path.join(tmpDir, 'desktop-update-settings.json')

  assert.deepEqual(readUpdateSettings(settingsPath), defaultUpdateSettings())

  writeUpdateSettings(settingsPath, {
    autoCheck: false,
    intervalMinutes: 90,
    lastCheckedAt: 123,
  })

  assert.deepEqual(readUpdateSettings(settingsPath), {
    autoCheck: false,
    intervalMinutes: 90,
    lastCheckedAt: 123,
  })
})

test('getInstallerFileName uses release asset basename and sanitizes unsafe names', () => {
  assert.equal(
    getInstallerFileName('https://github.com/wlohf/Mnemox/releases/download/v1.0.8/Mnemox-Setup-1.0.8.exe', '1.0.8'),
    'Mnemox-Setup-1.0.8.exe',
  )
  assert.equal(
    getInstallerFileName('https://example.com/download?asset=installer', 'v1.0.9'),
    'Mnemox-Setup-1.0.9.exe',
  )
  assert.equal(
    getInstallerFileName('https://example.com/releases/Mnemox%3ASetup%3F1.0.9.exe', null),
    'Mnemox_Setup_1.0.9.exe',
  )
})
