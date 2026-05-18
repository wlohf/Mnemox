import { useId } from 'react'

interface MnemoxLogoProps {
  size?: number
  showWordmark?: boolean
  className?: string
}

export function MnemoxLogo({ size = 40, showWordmark = false, className = '' }: MnemoxLogoProps) {
  const gradientId = useId().replace(/:/g, '')
  const clipId = `${gradientId}-clip`

  return (
    <div className={`mnemox-logo${showWordmark ? ' mnemox-logo-with-wordmark' : ''}${className ? ` ${className}` : ''}`}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 64 64"
        role="img"
        aria-label="Mnemox"
        className="mnemox-logo-mark"
      >
        <defs>
          <linearGradient id={gradientId} x1="12" y1="8" x2="54" y2="58" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#8fd9c6" />
            <stop offset="0.52" stopColor="#5d9c8e" />
            <stop offset="1" stopColor="#2f3933" />
          </linearGradient>
          <clipPath id={clipId}>
            <rect x="6" y="6" width="52" height="52" rx="15" />
          </clipPath>
        </defs>
        <rect x="6" y="6" width="52" height="52" rx="15" fill={`url(#${gradientId})`} />
        <g clipPath={`url(#${clipId})`}>
          <path
            d="M18 43V22.5c0-2.3 2.8-3.3 4.3-1.6L32 32l9.7-11.1c1.5-1.7 4.3-.7 4.3 1.6V43"
            fill="none"
            stroke="rgba(255,255,255,0.94)"
            strokeWidth="5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M19 46c8-1.8 18.7-1.8 26 0"
            fill="none"
            stroke="rgba(255,255,255,0.48)"
            strokeWidth="3"
            strokeLinecap="round"
          />
          <circle cx="20" cy="20" r="3.2" fill="rgba(255,255,255,0.96)" />
          <circle cx="32" cy="32" r="3.2" fill="rgba(255,255,255,0.96)" />
          <circle cx="44" cy="20" r="3.2" fill="rgba(255,255,255,0.96)" />
          <path
            d="M20 20l12 12 12-12"
            fill="none"
            stroke="rgba(255,255,255,0.38)"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </g>
      </svg>
      {showWordmark && (
        <span className="mnemox-logo-wordmark">
          <strong>Mnemox</strong>
          <small>AI Learning Coach</small>
        </span>
      )}
    </div>
  )
}
