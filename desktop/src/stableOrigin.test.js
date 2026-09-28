const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const net = require('node:net')
const { stableBackendPort } = require('./stableOrigin')

test('desktop origin survives process restarts and refuses occupied ports', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mnemox-origin-'))
  const server = net.createServer()
  try {
    const first = await stableBackendPort(dir)
    assert.equal(await stableBackendPort(dir), first)
    await new Promise(resolve => server.listen(first, '127.0.0.1', resolve))
    await assert.rejects(stableBackendPort(dir), /被占用/)
    assert.equal(JSON.parse(fs.readFileSync(path.join(dir, 'desktop-origin.json'))).port, first)
  } finally {
    if (server.listening) await new Promise(resolve => server.close(resolve))
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('first upgrade preserves the most recent legacy IndexedDB origin', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mnemox-origin-'))
  try {
    const selected = await stableBackendPort(dir)
    fs.unlinkSync(path.join(dir, 'desktop-origin.json'))
    fs.mkdirSync(path.join(dir, 'IndexedDB', `http_127.0.0.1_${selected}.indexeddb.leveldb`), { recursive: true })
    assert.equal(await stableBackendPort(dir), selected)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('missing port in an existing origin file never silently selects a new origin', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mnemox-origin-'))
  try {
    fs.writeFileSync(path.join(dir, 'desktop-origin.json'), '{}')
    await assert.rejects(stableBackendPort(dir), /端口无效/)
    assert.equal(fs.readFileSync(path.join(dir, 'desktop-origin.json'), 'utf8'), '{}')
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})
