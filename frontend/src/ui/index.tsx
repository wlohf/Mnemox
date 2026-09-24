import { forwardRef, useEffect, useState, type ButtonHTMLAttributes, type CSSProperties, type ReactNode } from 'react'
import * as RTooltip from '@radix-ui/react-tooltip'
import { Quote } from 'lucide-react'
import s from './ui.module.css'

const cx = (...c: Array<string | false | null | undefined>) => c.filter(Boolean).join(' ')

/* ---------- Button ---------- */
type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'evidence' | 'danger'
type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: ReactNode
  iconRight?: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', icon, iconRight, className, children, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cx(s.btn, s[variant], size !== 'md' && s[size], className)}
      {...rest}
    >
      {icon}
      {children}
      {iconRight}
    </button>
  )
})

/* ---------- Tooltip ---------- */
export function Tooltip({ label, kbd, side = 'top', children }: {
  label: ReactNode
  kbd?: string[]
  side?: 'top' | 'right' | 'bottom' | 'left'
  children: ReactNode
}) {
  return (
    <RTooltip.Root>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content side={side} sideOffset={6} className={s.tooltip}>
          {label}
          {kbd && <span style={{ display: 'inline-flex', gap: 3 }}>{kbd.map(k => <Kbd key={k}>{k}</Kbd>)}</span>}
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  )
}

export const TooltipProvider = ({ children }: { children: ReactNode }) => (
  <RTooltip.Provider delayDuration={350} skipDelayDuration={200}>{children}</RTooltip.Provider>
)

/* ---------- IconButton ---------- */
export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string
  kbd?: string[]
  active?: boolean
  size?: 'sm' | 'md'
  tooltipSide?: 'top' | 'right' | 'bottom' | 'left'
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, kbd, active, size = 'md', tooltipSide, className, children, type = 'button', ...rest },
  ref,
) {
  return (
    <Tooltip label={label} kbd={kbd} side={tooltipSide}>
      <button
        ref={ref}
        type={type}
        aria-label={label}
        data-active={active || undefined}
        className={cx(s.iconBtn, size === 'sm' && s.iconBtnSm, className)}
        {...rest}
      >
        {children}
      </button>
    </Tooltip>
  )
})

/* ---------- Kbd ---------- */
export const Kbd = ({ children }: { children: ReactNode }) => <kbd className={s.kbd}>{children}</kbd>

/* ---------- Chip ---------- */
export const Chip = ({ children, icon, tone }: { children: ReactNode; icon?: ReactNode; tone?: 'ink' }) => (
  <span className={cx(s.chip, tone === 'ink' && s.chipInk)}>{icon}{children}</span>
)

/* ---------- Citation ---------- */
export function Cite({ n, active, onClick, onMouseEnter }: {
  n: number
  active?: boolean
  onClick?: () => void
  onMouseEnter?: () => void
}) {
  return (
    <button
      type="button"
      className={s.cite}
      data-active={active || undefined}
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      aria-label={`查看来源 ${n}`}
    >
      <Quote aria-hidden />{n}
    </button>
  )
}

/* ---------- ProgressRing ---------- */
export function ProgressRing({ value, size = 44, stroke = 4, color, children }: {
  value: number
  size?: number
  stroke?: number
  color?: string
  children?: ReactNode
}) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const [shown, setShown] = useState(0)
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(value))
    return () => cancelAnimationFrame(id)
  }, [value])
  return (
    <div style={{ position: 'relative', width: size, height: size, color: color ?? 'var(--mx-ink)' }}>
      <svg width={size} height={size} className={s.ring} aria-hidden>
        <circle className={s.ringTrack} cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} />
        <circle
          className={s.ringValue}
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - Math.min(Math.max(shown, 0), 1))}
        />
      </svg>
      {children && (
        <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center' }}>{children}</div>
      )}
    </div>
  )
}

/* ---------- MasteryBar ---------- */
export function MasteryBar({ level, max = 5 }: { level: number; max?: number }) {
  const style = { '--mx-level': `var(--mx-m${Math.max(1, Math.min(5, level))})` } as CSSProperties
  return (
    <span className={s.masteryBar} style={style} aria-label={`掌握度 ${level}/${max}`} role="img">
      {Array.from({ length: max }, (_, i) => <span key={i} data-on={i < level} />)}
    </span>
  )
}

/* ---------- CountUp ---------- */
export function CountUp({ value, duration = 900, format = (n: number) => String(Math.round(n)) }: {
  value: number
  duration?: number
  format?: (n: number) => string
}) {
  const [n, setN] = useState(0)
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setN(value); return }
    let raf = 0
    const start = performance.now()
    const tick = (t: number) => {
      const p = Math.min((t - start) / duration, 1)
      const eased = 1 - Math.pow(1 - p, 3)
      setN(value * eased)
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, duration])
  return <span className="mx-num">{format(n)}</span>
}

export { cx }
