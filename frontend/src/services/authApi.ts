import { apiFetch, setToken, getToken } from './apiClient'

export interface UserInfo {
  id: number
  username: string
  email: string
  is_active: boolean
  created_at: string
}

/**
 * Extract a human-readable error message from a FastAPI error response.
 * FastAPI returns `{detail: "string"}` for HTTPException but
 * `{detail: [{msg: "...", loc: [...]}]}` for Pydantic validation errors.
 */
function extractErrorMessage(err: any, fallback: string): string {
  if (!err) return fallback
  const detail = err.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    // Pydantic validation error - join all messages
    return detail
      .map((d: any) => {
        const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : ''
        const msg = d.msg || ''
        return field ? `${field}: ${msg}` : msg
      })
      .join('；')
  }
  return fallback
}

export async function login(username: string, password: string): Promise<string> {
  const body = new URLSearchParams()
  body.set('username', username)
  body.set('password', password)

  const res = await fetch('/api/auth/login', {
    method: 'POST',
    body,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => null)
    throw new Error(extractErrorMessage(err, '登录失败'))
  }

  const data = await res.json()
  setToken(data.access_token)
  return data.access_token
}

export async function register(
  username: string,
  email: string,
  password: string,
): Promise<UserInfo> {
  const res = await fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password }),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => null)
    throw new Error(extractErrorMessage(err, '注册失败'))
  }

  return res.json()
}

export async function getMe(): Promise<UserInfo | null> {
  const token = getToken()
  if (!token) return null

  const res = await apiFetch('/api/auth/me')
  if (!res.ok) return null
  return res.json()
}
