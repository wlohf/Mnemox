const fs = require('node:fs')
const net = require('node:net')
const path = require('node:path')

function probePort(port = 0) {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once('error', reject)
    server.listen(port, '127.0.0.1', () => {
      const selected = server.address().port
      server.close(() => resolve(selected))
    })
  })
}

function legacyOrigins(userData) {
  const dir = path.join(userData, 'IndexedDB')
  if (!fs.existsSync(dir)) return []
  return fs.readdirSync(dir).flatMap(name => {
    const match = /^http_127\.0\.0\.1_(\d+)\.indexeddb\.leveldb$/.exec(name)
    if (!match) return []
    return [{ port: Number(match[1]), modified: fs.statSync(path.join(dir, name)).mtimeMs }]
  }).sort((a, b) => b.modified - a.modified)
}

async function stableBackendPort(userData) {
  fs.mkdirSync(userData, { recursive: true })
  const file = path.join(userData, 'desktop-origin.json')
  const saved = fs.existsSync(file)
  // Reuse the most recently used legacy IndexedDB origin on the first upgrade.
  const port = saved ? JSON.parse(fs.readFileSync(file, 'utf8')).port : legacyOrigins(userData)[0]?.port
  if ((saved || port !== undefined) && (!Number.isInteger(port) || port < 1024 || port > 65535)) {
    throw new Error('desktop-origin.json 中的本地端口无效，请恢复该文件的备份；不能切换到空白数据源。')
  }
  let selected
  try {
    selected = await probePort(port ?? 0)
  } catch (error) {
    throw new Error(`Mnemox 固定本地端口 ${port} 被占用，无法打开原离线数据。请关闭占用该端口的进程后重试。`, { cause: error })
  }
  if (!saved) fs.writeFileSync(file, JSON.stringify({ port: selected }), { flag: 'wx', mode: 0o600 })
  return selected
}

module.exports = { stableBackendPort, legacyOrigins }
