import { useSyncExternalStore, type ReactNode } from 'react'
import * as RToast from '@radix-ui/react-toast'
import { Check, CircleAlert, Info, Quote, TriangleAlert, X } from 'lucide-react'
import { Button, IconButton } from './controls'
import s from './overlays.module.css'

/*
 * App-wide notifications. `toast.*` is callable from anywhere (services,
 * stores, event handlers); <Toaster/> renders the queue.
 */

export type ToastTone = 'info' | 'success' | 'warning' | 'danger' | 'evidence'

export interface ToastAction {
  label: string
  onClick: () => void
  variant?: 'primary' | 'secondary' | 'ghost'
}

export interface ToastItem {
  id: string
  tone: ToastTone
  title: ReactNode
  description?: ReactNode
  actions?: ToastAction[]
  /** ms; 0 keeps it until dismissed */
  duration: number
  open: boolean
}

type Listener = () => void

let items: ToastItem[] = []
const listeners = new Set<Listener>()
let seq = 0

function emit() {
  for (const l of listeners) l()
}

function subscribe(l: Listener) {
  listeners.add(l)
  return () => listeners.delete(l)
}

function snapshot() {
  return items
}

const MAX_VISIBLE = 4

function push(
  tone: ToastTone,
  title: ReactNode,
  opts: { description?: ReactNode; actions?: ToastAction[]; duration?: number; id?: string } = {},
): string {
  const id = opts.id ?? `t${++seq}`
  const duration = opts.duration ?? (tone === 'danger' ? 7000 : opts.actions?.length ? 9000 : 4200)
  const existing = items.find(t => t.id === id)
  const next: ToastItem = { id, tone, title, description: opts.description, actions: opts.actions, duration, open: true }
  items = existing ? items.map(t => (t.id === id ? next : t)) : [...items, next].slice(-MAX_VISIBLE - 2)
  emit()
  return id
}

function dismiss(id?: string) {
  items = items.map(t => (id === undefined || t.id === id ? { ...t, open: false } : t))
  emit()
  // Allow the exit animation before removing.
  window.setTimeout(() => {
    items = items.filter(t => t.open)
    emit()
  }, 260)
}

type ToastOpts = { description?: ReactNode; actions?: ToastAction[]; duration?: number; id?: string }

export const toast = {
  info: (title: ReactNode, opts?: ToastOpts) => push('info', title, opts),
  success: (title: ReactNode, opts?: ToastOpts) => push('success', title, opts),
  warning: (title: ReactNode, opts?: ToastOpts) => push('warning', title, opts),
  error: (title: ReactNode, opts?: ToastOpts) => push('danger', title, opts),
  evidence: (title: ReactNode, opts?: ToastOpts) => push('evidence', title, opts),
  dismiss,
}

const ICONS: Record<ToastTone, ReactNode> = {
  info: <Info />,
  success: <Check />,
  warning: <TriangleAlert />,
  danger: <CircleAlert />,
  evidence: <Quote />,
}

export function Toaster() {
  const list = useSyncExternalStore(subscribe, snapshot, snapshot)
  return (
    <RToast.Provider swipeDirection="right" label="通知">
      {list.slice(-MAX_VISIBLE).map(t => (
        <RToast.Root
          key={t.id}
          className={s.toast}
          data-tone={t.tone}
          open={t.open}
          duration={t.duration === 0 ? Infinity : t.duration}
          type={t.tone === 'danger' ? 'foreground' : 'background'}
          onOpenChange={o => {
            if (!o) dismiss(t.id)
          }}
        >
          <span className={s.toastIcon} aria-hidden>
            {ICONS[t.tone]}
          </span>
          <div className={s.toastBody}>
            <RToast.Title className={s.toastTitle}>{t.title}</RToast.Title>
            {t.description && <RToast.Description className={s.toastDesc}>{t.description}</RToast.Description>}
            {t.actions && t.actions.length > 0 && (
              <div className={s.toastActions}>
                {t.actions.map(a => (
                  <RToast.Action key={a.label} altText={a.label} asChild>
                    <Button
                      size="sm"
                      variant={a.variant ?? 'secondary'}
                      onClick={() => {
                        a.onClick()
                        dismiss(t.id)
                      }}
                    >
                      {a.label}
                    </Button>
                  </RToast.Action>
                ))}
              </div>
            )}
          </div>
          <RToast.Close asChild>
            <IconButton label="关闭通知" size="sm" noTooltip className={s.toastClose}>
              <X />
            </IconButton>
          </RToast.Close>
        </RToast.Root>
      ))}
      <RToast.Viewport className={s.toastViewport} />
    </RToast.Provider>
  )
}
