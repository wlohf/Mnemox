// Real HTTP + IndexedDB acceptance. NEVER point this at a working/user database.
// Requires Vite, an isolated backend, and explicit synthetic-write opt-in.
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'
import assert from 'node:assert/strict'

const base = process.env.MNEMOX_E2E_BASE_URL || 'http://127.0.0.1:5187'
const artifacts = process.env.MNEMOX_E2E_ARTIFACT_DIR || '/tmp/mnemox-sync-e2e'
if (process.env.MNEMOX_SYNC_E2E_ALLOW_SYNTHETIC_WRITES !== '1'
  || !['127.0.0.1', 'localhost', '[::1]'].includes(new URL(base).hostname)) {
  throw new Error('Use an isolated loopback backend and set MNEMOX_SYNC_E2E_ALLOW_SYNTHETIC_WRITES=1')
}
await mkdir(artifacts, { recursive: true })
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, timezoneId: 'Asia/Shanghai' })
const page = await context.newPage()
const results = []
try {
  await page.goto(base, { waitUntil: 'networkidle' })
  await page.evaluate(async () => {
    const auth = await import('/src/services/authApi.ts')
    const { useAuthStore } = await import('/src/stores/authStore.ts')
    const username = `sync_e2e_${crypto.randomUUID().slice(0, 8)}`
    const password = `Test-only-${crypto.randomUUID()}`
    await auth.register(username, `${username}@example.com`, password)
    await useAuthStore.getState().login(username, password)
  })
  await page.getByRole('button', { name: '账户和设置' }).waitFor()
  await page.waitForLoadState('networkidle')
  assert((await context.cookies()).some(cookie => cookie.httpOnly), 'Expected an HttpOnly session cookie')
  results.push('real-http-only-session')
  await page.evaluate(async () => {
    const { syncEngine } = await import('/src/sync/SyncEngine.ts')
    const { saveLocalOperation } = await import('/src/sync/enqueueOperation.ts')
    syncEngine.stop(); await syncEngine.syncAll()
    const originalFetch = window.fetch.bind(window)
    let loseResponse = true
    window.fetch = async (url, options) => {
      const response = await originalFetch(url, options)
      if (String(url) === '/api/notes' && options?.method === 'POST' && loseResponse && response.ok) {
        loseResponse = false
        await response.text() // SQL committed; discard only the successful response.
        throw new TypeError('synthetic response loss after commit')
      }
      return response
    }
    const now = new Date().toISOString()
    await saveLocalOperation('notes', 'create', 'sync-e2e-note', {
      _localId: 'sync-e2e-note', _serverId: null, _syncStatus: 'pending_create',
      _updatedAt: now, _lastSyncedAt: null, _conflictAt: null, _conflictServerData: null,
      title: 'sync-e2e-create', content: 'synthetic content only', tags: '[]', links: '[]', note_type: 'general',
      material_id: null, chapter_id: null, created_at: now,
    })
    syncEngine.start()
    const deadline = Date.now() + 15000
    while (syncEngine.getSnapshot().status !== 'offline') {
      if (Date.now() > deadline) throw new Error(`No offline state after dropped response: ${JSON.stringify(syncEngine.getSnapshot())}`)
      await new Promise(resolve => setTimeout(resolve, 20))
    }
    syncEngine.stop(); window.fetch = originalFetch
    await saveLocalOperation('notes', 'update', 'sync-e2e-note', { title: 'sync-e2e-after-loss' })
  })
  // A real browser reload discards all in-memory state; persistent queue identity remains.
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByRole('button', { name: '账户和设置' }).waitFor()
  const recovered = await page.evaluate(async () => {
    const { syncEngine } = await import('/src/sync/SyncEngine.ts')
    const { db } = await import('/src/db/studyDb.ts')
    const { apiFetch } = await import('/src/services/apiClient.ts')
    await syncEngine.syncAll()
    return { local: await db.notes.get('sync-e2e-note'), queue: await db.opQueue.count(), remote: await apiFetch('/api/notes') }
  })
  assert.equal(recovered.queue, 0)
  assert.equal(recovered.remote.length, 1)
  assert.equal(recovered.local.title, 'sync-e2e-after-loss')
  assert.equal(recovered.local._serverId, recovered.remote[0].id)
  assert.equal(recovered.local._serverVersion, recovered.remote[0].sync_version)
  results.push('lost-create-response-replayed-on-reload-without-duplicates')

  async function createConflict(action) {
    await page.evaluate(async (action) => {
      const { syncEngine } = await import('/src/sync/SyncEngine.ts')
      const { db } = await import('/src/db/studyDb.ts')
      const { apiFetch } = await import('/src/services/apiClient.ts')
      const { saveLocalOperation } = await import('/src/sync/enqueueOperation.ts')
      syncEngine.stop(); await syncEngine.syncAll()
      const local = await db.notes.get('sync-e2e-note')
      await apiFetch(`/api/notes/${local._serverId}`, { method: 'PUT', body: JSON.stringify({ title: `cloud-${action}` }) })
      await saveLocalOperation('notes', action, local._localId, action === 'update' ? { title: 'keep-local-until-choice' } : {})
      syncEngine.start(); await syncEngine.syncAll()
      const conflict = await db.notes.get(local._localId)
      if (conflict._syncStatus !== 'conflicted') throw new Error(`Expected CAS conflict: ${JSON.stringify(conflict)}`)
    }, action)
    await page.getByText('待处理 1', { exact: true }).click()
    await page.getByRole('dialog').waitFor()
  }
  await createConflict('update')
  assert(await page.getByRole('dialog').getByText('keep-local-until-choice', { exact: false }).count())
  results.push('real-server-cas-preserves-local-content')
  await page.getByRole('button', { name: '采用云端版本', exact: true }).click()
  await page.getByText('没有待处理的同步冲突', { exact: true }).waitFor()
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  const chosen = await page.evaluate(async () => {
    const { db } = await import('/src/db/studyDb.ts')
    return { note: await db.notes.get('sync-e2e-note'), count: await db.opQueue.count() }
  })
  assert.equal(chosen.note.title, 'cloud-update'); assert.equal(chosen.count, 0)
  results.push('explicit-server-choice-applied-atomically')

  await createConflict('delete')
  await page.getByRole('button', { name: '继续删除云端记录', exact: true }).waitFor()
  for (const close of await page.locator('.ant-notification-notice-close').all()) await close.click()
  await page.screenshot({ path: `${artifacts}/delete-conflict-desktop.png`, animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: `${artifacts}/delete-conflict-mobile.png`, animations: 'disabled' })
  await page.getByRole('button', { name: '继续删除云端记录', exact: true }).click()
  await page.getByText('没有待处理的同步冲突', { exact: true }).waitFor()
  const deleted = await page.evaluate(async () => {
    const { syncEngine } = await import('/src/sync/SyncEngine.ts')
    await syncEngine.syncAll()
    const { db } = await import('/src/db/studyDb.ts')
    const { apiFetch } = await import('/src/services/apiClient.ts')
    return { local: await db.notes.count(), queue: await db.opQueue.count(), remote: (await apiFetch('/api/notes')).length }
  })
  assert.deepEqual(deleted, { local: 0, queue: 0, remote: 0 })
  results.push('delete-conflict-requires-explicit-confirmation')
  console.log(JSON.stringify({ ok: true, results, artifacts }, null, 2))
} finally {
  await browser.close()
}
