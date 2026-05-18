import { message } from 'antd'

const TOKEN_KEY = 'study_assistant_token'

export class ApiRequestError extends Error {
  status?: number
  code?: string
  detail?: unknown
  body?: string

  constructor(message: string, init: { status?: number; code?: string; detail?: unknown; body?: string } = {}) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = init.status
    this.code = init.code
    this.detail = init.detail
    this.body = init.body
  }
}

function parseErrorBody(errorText: string): { message?: string; code?: string; detail?: unknown } {
  if (!errorText) return {}

  try {
    const parsed = JSON.parse(errorText)
    const detail = parsed?.detail
    if (typeof detail === 'string') {
      return { message: detail, detail }
    }
    if (detail && typeof detail === 'object') {
      return {
        message: typeof detail.message === 'string' ? detail.message : undefined,
        code: typeof detail.code === 'string' ? detail.code : undefined,
        detail,
      }
    }
    if (typeof parsed?.message === 'string') {
      return { message: parsed.message, detail: parsed }
    }
    if (typeof parsed?.error === 'string') {
      return { message: parsed.error, detail: parsed }
    }
    return { detail: parsed }
  } catch {
    return { message: errorText }
  }
}

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiRequestError) {
    return error.message || fallback
  }
  if (error instanceof Error) {
    const parsed = parseErrorBody(error.message)
    return parsed.message || error.message || fallback
  }
  if (typeof error === 'string') {
    const parsed = parseErrorBody(error)
    return parsed.message || error || fallback
  }
  return fallback
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function withAuthQuery(url: string): string {
  const token = getToken()
  if (!token || !url.startsWith('/api/')) return url
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}token=${encodeURIComponent(token)}`
}

// ── Network status tracking ──

let _networkOnline = navigator.onLine

window.addEventListener('online', () => { _networkOnline = true })
window.addEventListener('offline', () => { _networkOnline = false })

/** Returns current network status (combines navigator.onLine with fetch error detection). */
export function isNetworkOnline(): boolean {
  return _networkOnline
}

let _redirecting = false
let _lastNetworkToastAt = 0

export async function apiFetch<T = any>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken()
  const headers = new Headers(options.headers || {})

  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  // Set Content-Type for non-FormData requests
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let res: Response
  try {
    // Disable auto-redirect so we can handle 307 manually and preserve auth header
    res = await fetch(url, { ...options, headers, redirect: 'follow' })
  } catch (err) {
    // TypeError from fetch usually means network failure
    if (err instanceof TypeError) {
      _networkOnline = false
      const now = Date.now()
      if (now - _lastNetworkToastAt > 5000) {
        _lastNetworkToastAt = now
        message.error('网络连接异常，请检查网络后重试')
      }
    }
    throw err
  }

  // Successful fetch means network is reachable
  _networkOnline = true

  if (res.status === 401 && token) {
    // Only clear token and redirect once, not for every concurrent request
    if (!_redirecting) {
      _redirecting = true
      clearToken()
      message.warning('登录状态已过期，请重新登录')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
      // Reset after a short delay so future real 401s still work
      setTimeout(() => { _redirecting = false }, 2000)
    }
  }

  if (!res.ok) {
    const errorText = await res.text()
    const parsed = parseErrorBody(errorText)
    const error = new ApiRequestError(parsed.message || `HTTP ${res.status}`, {
      status: res.status,
      code: parsed.code,
      detail: parsed.detail,
      body: errorText,
    })
    if (res.status >= 500) {
      message.error(`${error.message || '服务器错误'} (${res.status})`)
    }
    throw error
  }

  return res.json() as Promise<T>
}
