import { Spinner } from '../../ui'

/** Shown while the local backend starts (desktop cold start). */
export function BackendWaiting() {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        display: 'grid',
        placeItems: 'center',
        height: '100%',
        padding: 24,
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, textAlign: 'center' }}>
        <span style={{ color: 'var(--mx-ink)' }}>
          <Spinner size={22} />
        </span>
        <div style={{ fontSize: 'var(--mx-type-ui)', fontWeight: 600, color: 'var(--mx-text)' }}>正在连接本地学习服务…</div>
        <div style={{ maxWidth: 320, fontSize: 'var(--mx-type-meta)', lineHeight: 1.6, color: 'var(--mx-text-3)' }}>
          第一次启动可能需要十几秒。服务就绪后会自动继续，无需刷新。
        </div>
      </div>
    </div>
  )
}
