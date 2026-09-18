import { useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { RightOutlined } from '@ant-design/icons'

interface FoldPanelProps {
  title: ReactNode
  children: ReactNode
  summary?: ReactNode
  extra?: ReactNode
  defaultOpen?: boolean
  open?: boolean
  onOpenChange?: (open: boolean) => void
  storageKey?: string
  className?: string
  style?: CSSProperties
}

/** Mounted content preserves its state; a CSS grid transition can reverse mid-flight. */
export function FoldPanel({
  title, children, summary, extra, defaultOpen = false, open, onOpenChange,
  storageKey, className = '', style,
}: FoldPanelProps) {
  const id = useId()
  const trigger = useRef<HTMLButtonElement>(null)
  const content = useRef<HTMLDivElement>(null)
  const [expanded, setExpanded] = useState(() => {
    if (!storageKey) return defaultOpen
    try {
      const saved = localStorage.getItem(storageKey)
      return saved === null ? defaultOpen : saved === 'true'
    } catch { return defaultOpen }
  })
  const isOpen = open ?? expanded

  useLayoutEffect(() => {
    const element = content.current
    if (!element) return
    if (!isOpen && element.contains(document.activeElement)) trigger.current?.focus()
    element.inert = !isOpen
  }, [isOpen])

  const toggle = () => {
    const next = !isOpen
    setExpanded(next)
    onOpenChange?.(next)
    if (storageKey) {
      try { localStorage.setItem(storageKey, String(next)) } catch { /* Preferences are optional. */ }
    }
  }

  return (
    <section className={`mnemox-fold-panel ${isOpen ? 'is-open' : ''} ${className}`} style={style}>
      <div className="mnemox-fold-heading">
        <h3>
          <button ref={trigger} type="button" id={`${id}-trigger`} aria-expanded={isOpen}
            aria-controls={`${id}-content`} onClick={toggle} className="mnemox-fold-trigger" data-click-spark>
            <RightOutlined className="mnemox-fold-chevron" aria-hidden />
            <span className="mnemox-fold-label">{title}</span>
            {summary !== undefined && <span className="mnemox-fold-summary">{summary}</span>}
          </button>
        </h3>
        {extra && <div className="mnemox-fold-extra">{extra}</div>}
      </div>
      <div className="mnemox-fold-grid" id={`${id}-content`} role="region"
        aria-labelledby={`${id}-trigger`} aria-hidden={!isOpen} ref={content}>
        <div className="mnemox-fold-clip"><div className="mnemox-fold-body">{children}</div></div>
      </div>
    </section>
  )
}
