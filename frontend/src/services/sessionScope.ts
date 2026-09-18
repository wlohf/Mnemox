/** A request belongs to the login generation that started it, not the current cookie. */
const CHANGE_KEY = 'mnemox.session-change'
export const SESSION_INVALIDATED_EVENT = 'mnemox:session-invalidated'
let userId: number | null = null
let controller = new AbortController()

export interface ApiSessionScope {
  readonly userId: number | null
  readonly signal: AbortSignal
  assertActive(): void
}

export function captureApiSession(): ApiSessionScope {
  const captured = controller
  return {
    userId,
    signal: captured.signal,
    assertActive() {
      if (captured !== controller || captured.signal.aborted) {
        throw new DOMException('登录会话已变化，请重试', 'AbortError')
      }
    },
  }
}

export function setApiSessionUser(nextUserId: number | null): void {
  controller.abort()
  controller = new AbortController()
  userId = nextUserId
}

/** Notify other tabs before changing a shared HttpOnly cookie. No credentials are stored. */
export function announceSessionChange(): void {
  try { localStorage.setItem(CHANGE_KEY, crypto.randomUUID()) } catch { /* storage may be unavailable */ }
}

export function invalidateApiSession(): void {
  setApiSessionUser(null)
  window.dispatchEvent(new Event(SESSION_INVALIDATED_EVENT))
}

window.addEventListener('storage', (event) => {
  if (event.key === CHANGE_KEY) invalidateApiSession()
})
