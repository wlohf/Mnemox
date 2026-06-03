const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')

const {
  createDesktopPreferenceStore,
  isValidPreferenceKey,
  readPreferenceStore,
} = require('./desktopPreferences')

test('desktop preferences persist values across store instances', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mnemox-preferences-'))
  const preferencesPath = path.join(tmpDir, 'desktop-preferences.json')
  const store = createDesktopPreferenceStore({ fs, preferencesPath })

  const layout = {
    cardOrder: ['review', 'current'],
    visibleCards: ['review'],
    collapsed: false,
    width: 360,
  }

  assert.deepEqual(store.set('layout.rightSidebar', layout), layout)
  assert.deepEqual(store.get('layout.rightSidebar'), layout)

  const nextStore = createDesktopPreferenceStore({ fs, preferencesPath })
  assert.deepEqual(nextStore.get('layout.rightSidebar'), layout)
})

test('desktop preferences ignore invalid JSON and invalid keys', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mnemox-preferences-'))
  const preferencesPath = path.join(tmpDir, 'desktop-preferences.json')
  fs.writeFileSync(preferencesPath, '{not json', 'utf8')

  assert.deepEqual(readPreferenceStore(fs, preferencesPath), {})
  assert.equal(isValidPreferenceKey('layout.rightSidebar'), true)
  assert.equal(isValidPreferenceKey('../bad'), false)

  const store = createDesktopPreferenceStore({ fs, preferencesPath })
  assert.equal(store.get('../bad'), null)
  assert.throws(() => store.set('../bad', true), /Invalid desktop preference key/)
})
