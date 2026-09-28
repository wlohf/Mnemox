import { useEffect, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'
import { Spinner, Wordmark } from '../ui'

/** Guards the authenticated app; restores the cookie session on first load. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, checkAuth } = useAuthStore()
  const location = useLocation()

  useEffect(() => {
    void checkAuth()
  }, [checkAuth])

  if (isLoading) {
    return (
      <div
        role="status"
        aria-label="正在恢复登录状态"
        style={{ display: 'grid', placeItems: 'center', height: '100dvh', background: 'var(--mx-canvas)' }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18, color: 'var(--mx-text-3)' }}>
          <Wordmark tile={34} />
          <Spinner size={18} />
        </div>
      </div>
    )
  }

  if (!isAuthenticated) {
    const from = `${location.pathname}${location.search}`
    return <Navigate to="/login" replace state={from !== '/' ? { from } : undefined} />
  }

  return <>{children}</>
}
