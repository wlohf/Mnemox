import {
  forwardRef,
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type CSSProperties,
  type HTMLAttributes,
  type ReactNode,
} from 'react'
import * as RTooltip from '@radix-ui/react-tooltip'
import s from './controls.module.css'

export const cx = (...c: Array<string | false | null | undefined>) => c.filter(Boolean).join(' ')

/* ---------- Spinner ---------- */
export function Spinner({ size = 16, className }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={cx(s.spinner, className)} aria-hidden>
      <circle cx="12" cy="12" r="9" strokeWidth="2.5" />
    </svg>
  )
}

/* ---------- Button ---------- */
export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'soft' | 'evidence' | 'danger' | 'dangerSolid'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: ReactNode
  iconRight?: ReactNode
  loading?: boolean
  block?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', icon, iconRight, loading, block, className, children, type = 'button', disabled, onClick, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cx(s.btn, s[variant], size !== 'md' && s[size], block && s.block, className)}
      disabled={disabled}
      aria-busy={loading || undefined}
      onClick={loading ? undefined : onClick}
      {...rest}
    >
      <span className={s.btnLabel}>
        {icon}
        {children}
        {iconRight}
      </span>
      {loading && (
        <span className={s.btnSpinner}>
          <Spinner size={size === 'sm' ? 13 : 15} />
        </span>
      )}
    </button>
  )
})

/* ---------- Tooltip ---------- */
export function Tooltip({
  label,
  kbd,
  side = 'top',
  children,
  disabled,
}: {
  label: ReactNode
  kbd?: string[]
  side?: 'top' | 'right' | 'bottom' | 'left'
  children: ReactNode
  disabled?: boolean
}) {
  if (disabled) return <>{children}</>
  return (
    <RTooltip.Root>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content side={side} sideOffset={6} collisionPadding={8} className={s.tooltip}>
          {label}
          {kbd && (
            <span style={{ display: 'inline-flex', gap: 3 }}>
              {kbd.map(k => (
                <Kbd key={k}>{k}</Kbd>
              ))}
            </span>
          )}
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  )
}

export const TooltipProvider = ({ children }: { children: ReactNode }) => (
  <RTooltip.Provider delayDuration={380} skipDelayDuration={220}>
    {children}
  </RTooltip.Provider>
)

/* ---------- IconButton ---------- */
export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string
  kbd?: string[]
  active?: boolean
  size?: 'sm' | 'md'
  tooltipSide?: 'top' | 'right' | 'bottom' | 'left'
  noTooltip?: boolean
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, kbd, active, size = 'md', tooltipSide, noTooltip, className, children, type = 'button', ...rest },
  ref,
) {
  const button = (
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
  )
  if (noTooltip) return button
  return (
    <Tooltip label={label} kbd={kbd} side={tooltipSide}>
      {button}
    </Tooltip>
  )
})

/* ---------- Kbd ---------- */
export const Kbd = ({ children }: { children: ReactNode }) => <kbd className={s.kbd}>{children}</kbd>

/* ---------- Badge ---------- */
export type Tone = 'neutral' | 'ink' | 'evidence' | 'success' | 'warning' | 'danger'

export function Badge({
  children,
  icon,
  tone = 'neutral',
  variant = 'soft',
  className,
  ...rest
}: HTMLAttributes<HTMLSpanElement> & { icon?: ReactNode; tone?: Tone; variant?: 'soft' | 'outline' }) {
  return (
    <span className={cx(s.badge, className)} data-tone={tone} data-variant={variant} {...rest}>
      {icon}
      {children}
    </span>
  )
}

/* ---------- Chip (toggleable filter pill) ---------- */
export function Chip({
  children,
  icon,
  selected,
  onClick,
  className,
}: {
  children: ReactNode
  icon?: ReactNode
  selected?: boolean
  onClick?: () => void
  className?: string
}) {
  if (!onClick) {
    return (
      <span className={cx(s.chip, className)} data-selected={selected || undefined}>
        {icon}
        {children}
      </span>
    )
  }
  return (
    <button type="button" className={cx(s.chip, className)} aria-pressed={!!selected} onClick={onClick}>
      {icon}
      {children}
    </button>
  )
}

/* ---------- Citation ---------- */
export function Cite({
  n,
  active,
  onClick,
  label,
}: {
  n: number | string
  active?: boolean
  onClick?: () => void
  label?: string
}) {
  return (
    <button
      type="button"
      className={s.cite}
      data-active={active || undefined}
      onClick={onClick}
      aria-label={label ?? `查看来源 ${n}`}
    >
      {n}
    </button>
  )
}

/* ---------- Highlight (animated highlighter stroke) ---------- */
export function Highlight({ children, lit = true }: { children: ReactNode; lit?: boolean }) {
  const [on, setOn] = useState(false)
  useEffect(() => {
    if (!lit) {
      setOn(false)
      return
    }
    const id = requestAnimationFrame(() => setOn(true))
    return () => cancelAnimationFrame(id)
  }, [lit])
  return (
    <mark className={s.mark} data-lit={on || undefined}>
      {children}
    </mark>
  )
}

/* ---------- ProgressRing ---------- */
export function ProgressRing({
  value,
  size = 44,
  stroke = 4,
  color,
  children,
  label,
}: {
  value: number
  size?: number
  stroke?: number
  color?: string
  children?: ReactNode
  label?: string
}) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const [shown, setShown] = useState(0)
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(value))
    return () => cancelAnimationFrame(id)
  }, [value])
  const clamped = Math.min(Math.max(shown, 0), 1)
  return (
    <div
      role={label ? 'img' : undefined}
      aria-label={label}
      style={{ position: 'relative', width: size, height: size, flex: 'none', color: color ?? 'var(--mx-ink)' }}
    >
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
          strokeDashoffset={c * (1 - clamped)}
        />
      </svg>
      {children && (
        <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center' }}>{children}</div>
      )}
    </div>
  )
}

/* ---------- ProgressBar ---------- */
export function ProgressBar({
  value,
  color,
  label,
  className,
}: {
  value: number
  color?: string
  label?: string
  className?: string
}) {
  const [shown, setShown] = useState(0)
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(value))
    return () => cancelAnimationFrame(id)
  }, [value])
  const pct = Math.min(Math.max(shown, 0), 1)
  return (
    <div
      className={cx(s.bar, className)}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value * 100)}
    >
      <div className={s.barFill} style={{ transform: `scaleX(${pct})`, ['--bar-color' as string]: color } as CSSProperties} />
    </div>
  )
}

/* ---------- Mastery pips (1–5) ---------- */
export function MasteryPips({ level, max = 5 }: { level: number; max?: number }) {
  const l = Math.max(0, Math.min(max, Math.round(level)))
  const style = { '--pip-color': `var(--mx-m${Math.max(1, l)})` } as CSSProperties
  return (
    <span className={s.pips} style={style} role="img" aria-label={`掌握度 ${l}/${max}`}>
      {Array.from({ length: max }, (_, i) => (
        <span key={i} data-on={i < l} />
      ))}
    </span>
  )
}

/* ---------- CountUp ---------- */
export function CountUp({
  value,
  duration = 800,
  format = (n: number) => String(Math.round(n)),
}: {
  value: number
  duration?: number
  format?: (n: number) => string
}) {
  const [n, setN] = useState(value)
  const from = useRef(0)
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setN(value)
      from.current = value
      return
    }
    let raf = 0
    const start = performance.now()
    const origin = from.current
    const tick = (t: number) => {
      const p = Math.min((t - start) / duration, 1)
      const eased = 1 - Math.pow(1 - p, 4)
      setN(origin + (value - origin) * eased)
      if (p < 1) raf = requestAnimationFrame(tick)
      else from.current = value
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, duration])
  return <span className="mx-num">{format(n)}</span>
}

/* ---------- Skeleton ---------- */
export function Skeleton({
  width = '100%',
  height = 14,
  radius,
  className,
  style,
}: {
  width?: number | string
  height?: number | string
  radius?: number
  className?: string
  style?: CSSProperties
}) {
  return (
    <span
      aria-hidden
      className={cx(s.skeleton, className)}
      style={{ width, height, borderRadius: radius, ...style }}
    />
  )
}

/* ---------- Separator ---------- */
export function Separator({ orientation = 'horizontal', className }: { orientation?: 'horizontal' | 'vertical'; className?: string }) {
  return <span role="separator" aria-orientation={orientation} data-orientation={orientation} className={cx(s.separator, className)} />
}
