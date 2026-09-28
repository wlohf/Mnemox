/**
 * Mnemox mark: two page arcs meeting at a spine — an open book that also
 * reads as an "M". Drawn on a 16-unit grid so it stays crisp at 14–28px.
 */
export function BrandMark({ size = 16, title }: { size?: number; title?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill="none"
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <path
        d="M2.5 12.6V5.3c0-.8.9-1.3 1.6-.9L8 6.7l3.9-2.3c.7-.4 1.6.1 1.6.9v7.3"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M8 6.7v6.1" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  )
}

/** Mark set on an ink tile + wordmark, for the sidebar and login. */
export function Wordmark({ compact, tile = 26 }: { compact?: boolean; tile?: number }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
      <span
        aria-hidden
        style={{
          display: 'grid',
          placeItems: 'center',
          flex: 'none',
          width: tile,
          height: tile,
          borderRadius: Math.round(tile * 0.27),
          background: 'var(--mx-text)',
          color: 'var(--mx-canvas)',
        }}
      >
        <BrandMark size={Math.round(tile * 0.62)} />
      </span>
      {!compact && (
        <span
          style={{
            fontSize: '0.9375rem',
            fontWeight: 660,
            letterSpacing: '-0.02em',
            color: 'var(--mx-text)',
          }}
        >
          Mnemox
        </span>
      )}
    </span>
  )
}
