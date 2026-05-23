const assert = require('node:assert/strict')
const test = require('node:test')

const { TRAY_ICON_DATA_URL, createTrayIcon } = require('./trayIcon')

test('tray icon is created from bundled image data', () => {
  const nativeImage = {
    createFromDataURL(dataUrl) {
      assert.equal(dataUrl, TRAY_ICON_DATA_URL)
      return {
        isEmpty() {
          return false
        },
      }
    },
  }

  assert.equal(createTrayIcon(nativeImage).isEmpty(), false)
})

test('tray icon creation fails clearly when Electron returns an empty image', () => {
  const nativeImage = {
    createFromDataURL() {
      return {
        isEmpty() {
          return true
        },
      }
    },
  }

  assert.throws(() => createTrayIcon(nativeImage), /Failed to create tray icon/)
})
