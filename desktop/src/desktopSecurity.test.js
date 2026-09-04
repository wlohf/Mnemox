const assert = require('node:assert/strict')
const test = require('node:test')

const { isSafeExternalUrl, isTrustedRendererUrl } = require('./desktopSecurity')

test('only the current local backend origin is trusted for desktop IPC', () => {
  assert.equal(isTrustedRendererUrl('http://127.0.0.1:18765/dashboard', 18765), true)
  assert.equal(isTrustedRendererUrl('http://localhost:18765/login', 18765), true)
  assert.equal(isTrustedRendererUrl('https://mnemox.wlohf.com/dashboard', 18765), false)
  assert.equal(isTrustedRendererUrl('http://127.0.0.1:18766/dashboard', 18765), false)
})

test('external links are restricted to HTTPS', () => {
  assert.equal(isSafeExternalUrl('https://github.com/wlohf/Mnemox'), true)
  assert.equal(isSafeExternalUrl('http://example.com'), false)
  assert.equal(isSafeExternalUrl('file:///tmp/unsafe'), false)
})
