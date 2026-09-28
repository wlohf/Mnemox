import type { CSSProperties, ElementType, HTMLAttributes, ReactNode } from 'react'
import { AlertCircle, ChevronRight, Info } from 'lucide-react'
import { cx } from './controls'
import s from './layout.module.css'

/* ---------- Page ---------- */
export function Page({
  children,
  width = 'default',
  className,
  style,
}: {
  children: ReactNode
  width?: 'narrow' | 'reading' | 'default' | 'wide' | 'full'
  className?: string
  style?: CSSProperties
}) {
  return (
    <div className={cx(s.page, className)} data-width={width === 'default' ? undefined : width} style={style}>
      {children}
    </div>
  )
}

export function PageHeader({
  title,
  kicker,
  lead,
  actions,
  className,
}: {
  title: ReactNode
  kicker?: ReactNode
  lead?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <header className={cx(s.pageHeader, className)}>
      <div className={s.pageHeaderText}>
        {kicker && <div className={s.pageKicker}>{kicker}</div>}
        <h1 className={s.pageTitle}>{title}</h1>
        {lead && <p className={s.pageLead}>{lead}</p>}
      </div>
      {actions && <div className={s.pageActions}>{actions}</div>}
    </header>
  )
}

/* ---------- Section ---------- */
export function Section({
  title,
  meta,
  aside,
  children,
  className,
  id,
  as: Tag = 'section',
}: {
  title?: ReactNode
  meta?: ReactNode
  aside?: ReactNode
  children: ReactNode
  className?: string
  id?: string
  as?: ElementType
}) {
  const headingId = id ? `${id}-title` : undefined
  return (
    <Tag className={cx(s.section, className)} id={id} aria-labelledby={title ? headingId : undefined}>
      {(title || aside) && (
        <div className={s.sectionHead}>
          {title && (
            <h2 id={headingId} className={s.sectionTitle}>
              {title}
            </h2>
          )}
          {meta && <span className={s.sectionMeta}>{meta}</span>}
          {aside && <div className={s.sectionAside}>{aside}</div>}
        </div>
      )}
      {children}
    </Tag>
  )
}

export function LinkButton({ children, onClick, withArrow = true }: { children: ReactNode; onClick?: () => void; withArrow?: boolean }) {
  return (
    <button type="button" className={s.linkBtn} onClick={onClick}>
      {children}
      {withArrow && <ChevronRight aria-hidden />}
    </button>
  )
}

/* ---------- Sheet ---------- */
export function Sheet({
  children,
  pad = 'md',
  tone,
  elevated,
  interactive,
  className,
  as: Tag = 'div',
  ...rest
}: HTMLAttributes<HTMLElement> & {
  children: ReactNode
  pad?: 'none' | 'sm' | 'md' | 'lg'
  tone?: 'sunken' | 'ink' | 'evidence'
  elevated?: boolean
  interactive?: boolean
  as?: ElementType
}) {
  return (
    <Tag
      className={cx(s.sheet, className)}
      data-pad={pad === 'none' ? undefined : pad}
      data-tone={tone}
      data-elevated={elevated || undefined}
      data-interactive={interactive || undefined}
      {...rest}
    >
      {children}
    </Tag>
  )
}

/* ---------- Empty ---------- */
export function Empty({
  icon,
  title,
  body,
  actions,
  align = 'center',
  className,
}: {
  icon?: ReactNode
  title: ReactNode
  body?: ReactNode
  actions?: ReactNode
  align?: 'center' | 'start'
  className?: string
}) {
  return (
    <div className={cx(s.empty, className)} data-align={align === 'start' ? 'start' : undefined}>
      {icon && (
        <span className={s.emptyGlyph} aria-hidden>
          {icon}
        </span>
      )}
      <p className={s.emptyTitle}>{title}</p>
      {body && <p className={s.emptyBody}>{body}</p>}
      {actions && <div className={s.emptyActions}>{actions}</div>}
    </div>
  )
}

/* ---------- Notice ---------- */
export function Notice({
  tone,
  icon,
  title,
  children,
  actions,
  className,
  role,
}: {
  tone?: 'ink' | 'evidence' | 'warning' | 'danger' | 'success'
  icon?: ReactNode
  title?: ReactNode
  children?: ReactNode
  actions?: ReactNode
  className?: string
  role?: 'status' | 'alert'
}) {
  const glyph = icon ?? (tone === 'danger' || tone === 'warning' ? <AlertCircle /> : <Info />)
  return (
    <div className={cx(s.notice, className)} data-tone={tone} role={role}>
      {glyph}
      <div className={s.noticeBody}>
        {title && <div className={s.noticeTitle}>{title}</div>}
        {children}
      </div>
      {actions && <div className={s.noticeActions}>{actions}</div>}
    </div>
  )
}

/* ---------- Stat grid (quiet inline metrics) ---------- */
export function StatGrid({ children, cols = 3, className }: { children: ReactNode; cols?: number; className?: string }) {
  return (
    <div className={cx(s.statGrid, className)} style={{ '--stat-cols': cols } as CSSProperties}>
      {children}
    </div>
  )
}

export function Stat({
  label,
  value,
  unit,
  foot,
}: {
  label: ReactNode
  value: ReactNode
  unit?: ReactNode
  foot?: ReactNode
}) {
  return (
    <div className={s.stat}>
      <span className={s.statLabel}>{label}</span>
      <span className={s.statValue}>
        <span className={s.statNum}>{value}</span>
        {unit && <span className={s.statUnit}>{unit}</span>}
      </span>
      {foot && <span className={s.statFoot}>{foot}</span>}
    </div>
  )
}

/* ---------- Key / value list ---------- */
export function KeyValue({ items, className }: { items: Array<[ReactNode, ReactNode]>; className?: string }) {
  return (
    <dl className={cx(s.kv, className)}>
      {items.map(([k, v], i) => (
        <div key={i} style={{ display: 'contents' }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  )
}

export const layoutStyles = s
