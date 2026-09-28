import { useState, type CSSProperties, type ReactNode } from 'react'
import * as RDialog from '@radix-ui/react-dialog'
import * as RAlert from '@radix-ui/react-alert-dialog'
import * as RPopover from '@radix-ui/react-popover'
import * as RMenu from '@radix-ui/react-dropdown-menu'
import * as RTabs from '@radix-ui/react-tabs'
import { CircleHelp, TriangleAlert, X } from 'lucide-react'
import { Button, IconButton, cx } from './controls'
import s from './overlays.module.css'

/* ==========================================================================
   Dialog
   ========================================================================== */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  footerStart,
  plainFooter,
  width = 32,
  hideClose,
  className,
  onOpenAutoFocus,
  preventOutsideClose,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
  footer?: ReactNode
  footerStart?: ReactNode
  plainFooter?: boolean
  /** width in rem */
  width?: number
  hideClose?: boolean
  className?: string
  onOpenAutoFocus?: (e: Event) => void
  preventOutsideClose?: boolean
}) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className={s.overlay} />
        <RDialog.Content
          className={cx(s.dialog, className)}
          style={{ '--dialog-w': `${width}rem` } as CSSProperties}
          onOpenAutoFocus={onOpenAutoFocus}
          onPointerDownOutside={preventOutsideClose ? e => e.preventDefault() : undefined}
          aria-describedby={description ? undefined : undefined}
        >
          <div className={s.dialogHead}>
            <div className={s.dialogHeadText}>
              <RDialog.Title className={s.dialogTitle}>{title}</RDialog.Title>
              {description ? (
                <RDialog.Description className={s.dialogDesc}>{description}</RDialog.Description>
              ) : (
                <RDialog.Description className="mx-visually-hidden">{typeof title === 'string' ? title : '对话框'}</RDialog.Description>
              )}
            </div>
            {!hideClose && (
              <RDialog.Close asChild>
                <IconButton label="关闭" size="sm" noTooltip>
                  <X />
                </IconButton>
              </RDialog.Close>
            )}
          </div>
          {children !== undefined && <div className={s.dialogBody}>{children}</div>}
          {footer && (
            <div className={s.dialogFoot} data-plain={plainFooter || undefined}>
              {footerStart && <span className={s.dialogFootStart}>{footerStart}</span>}
              {footer}
            </div>
          )}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  )
}

/* ==========================================================================
   Drawer (side sheet)
   ========================================================================== */
export function Drawer({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  width = 30,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
  footer?: ReactNode
  width?: number
}) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className={s.overlay} />
        <RDialog.Content className={s.drawer} style={{ '--drawer-w': `${width}rem` } as CSSProperties}>
          <div className={s.dialogHead}>
            <div className={s.dialogHeadText}>
              <RDialog.Title className={s.dialogTitle}>{title}</RDialog.Title>
              {description ? (
                <RDialog.Description className={s.dialogDesc}>{description}</RDialog.Description>
              ) : (
                <RDialog.Description className="mx-visually-hidden">{typeof title === 'string' ? title : '侧边面板'}</RDialog.Description>
              )}
            </div>
            <RDialog.Close asChild>
              <IconButton label="关闭" size="sm" noTooltip>
                <X />
              </IconButton>
            </RDialog.Close>
          </div>
          <div className={s.dialogBody}>{children}</div>
          {footer && <div className={s.dialogFoot}>{footer}</div>}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  )
}

/* ==========================================================================
   Confirm — controlled alert dialog
   ========================================================================== */
export function Confirm({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = '确认',
  cancelLabel = '取消',
  tone = 'default',
  onConfirm,
  children,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  title: ReactNode
  description?: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  tone?: 'default' | 'danger'
  onConfirm: () => void | Promise<void>
  children?: ReactNode
}) {
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true)
    try {
      await onConfirm()
      onOpenChange(false)
    } catch {
      /* caller reports the error; keep the dialog open for another attempt */
    } finally {
      setBusy(false)
    }
  }
  return (
    <RAlert.Root open={open} onOpenChange={v => !busy && onOpenChange(v)}>
      <RAlert.Portal>
        <RAlert.Overlay className={s.overlay} />
        <RAlert.Content className={s.dialog} style={{ '--dialog-w': '27rem' } as CSSProperties}>
          <div className={s.dialogHead} style={{ paddingBottom: 0 }}>
            <span className={s.confirmIcon} data-tone={tone === 'danger' ? 'danger' : undefined} aria-hidden>
              {tone === 'danger' ? <TriangleAlert /> : <CircleHelp />}
            </span>
            <div className={s.dialogHeadText}>
              <RAlert.Title className={s.dialogTitle}>{title}</RAlert.Title>
              {description ? (
                <RAlert.Description className={s.dialogDesc}>{description}</RAlert.Description>
              ) : (
                <RAlert.Description className="mx-visually-hidden">请确认此操作</RAlert.Description>
              )}
            </div>
          </div>
          {children && <div className={s.dialogBody}>{children}</div>}
          <div className={s.dialogFoot} data-plain>
            <RAlert.Cancel asChild>
              <Button variant="ghost" disabled={busy}>
                {cancelLabel}
              </Button>
            </RAlert.Cancel>
            <Button
              variant={tone === 'danger' ? 'dangerSolid' : 'primary'}
              loading={busy}
              onClick={e => {
                e.preventDefault()
                void run()
              }}
            >
              {confirmLabel}
            </Button>
          </div>
        </RAlert.Content>
      </RAlert.Portal>
    </RAlert.Root>
  )
}

/* ==========================================================================
   Popover
   ========================================================================== */
export function Popover({
  trigger,
  children,
  open,
  onOpenChange,
  side = 'bottom',
  align = 'start',
  width,
  sideOffset = 6,
}: {
  trigger: ReactNode
  children: ReactNode
  open?: boolean
  onOpenChange?: (v: boolean) => void
  side?: 'top' | 'right' | 'bottom' | 'left'
  align?: 'start' | 'center' | 'end'
  width?: number | string
  sideOffset?: number
}) {
  return (
    <RPopover.Root open={open} onOpenChange={onOpenChange}>
      <RPopover.Trigger asChild>{trigger}</RPopover.Trigger>
      <RPopover.Portal>
        <RPopover.Content
          side={side}
          align={align}
          sideOffset={sideOffset}
          collisionPadding={8}
          className={s.popover}
          style={width !== undefined ? ({ '--popover-w': typeof width === 'number' ? `${width}px` : width } as CSSProperties) : undefined}
        >
          {children}
        </RPopover.Content>
      </RPopover.Portal>
    </RPopover.Root>
  )
}

export const PopoverClose = RPopover.Close

/* ==========================================================================
   Dropdown menu
   ========================================================================== */
export interface MenuEntry {
  key: string
  label?: ReactNode
  icon?: ReactNode
  hint?: ReactNode
  tone?: 'danger'
  disabled?: boolean
  onSelect?: () => void
  type?: 'separator' | 'label'
}

export function Menu({
  trigger,
  items,
  align = 'end',
  side = 'bottom',
  minWidth,
}: {
  trigger: ReactNode
  items: MenuEntry[]
  align?: 'start' | 'center' | 'end'
  side?: 'top' | 'right' | 'bottom' | 'left'
  minWidth?: number
}) {
  return (
    <RMenu.Root modal={false}>
      <RMenu.Trigger asChild>{trigger}</RMenu.Trigger>
      <RMenu.Portal>
        <RMenu.Content
          align={align}
          side={side}
          sideOffset={6}
          collisionPadding={8}
          className={s.menu}
          style={minWidth ? { minWidth } : undefined}
        >
          {items.map(item => {
            if (item.type === 'separator') return <RMenu.Separator key={item.key} className={s.menuSeparator} />
            if (item.type === 'label')
              return (
                <RMenu.Label key={item.key} className={s.menuLabel}>
                  {item.label}
                </RMenu.Label>
              )
            return (
              <RMenu.Item
                key={item.key}
                className={s.menuItem}
                data-tone={item.tone}
                disabled={item.disabled}
                onSelect={item.onSelect}
              >
                {item.icon}
                <span>{item.label}</span>
                {item.hint && <span className={s.menuItemHint}>{item.hint}</span>}
              </RMenu.Item>
            )
          })}
        </RMenu.Content>
      </RMenu.Portal>
    </RMenu.Root>
  )
}

/* ==========================================================================
   Tabs
   ========================================================================== */
export function Tabs<T extends string>({
  value,
  onValueChange,
  items,
  variant = 'underline',
  children,
  className,
  listClassName,
  ariaLabel,
}: {
  value: T
  onValueChange: (v: T) => void
  items: Array<{ value: T; label: ReactNode; icon?: ReactNode; count?: number }>
  variant?: 'underline' | 'pill'
  children?: ReactNode
  className?: string
  listClassName?: string
  ariaLabel?: string
}) {
  return (
    <RTabs.Root value={value} onValueChange={v => onValueChange(v as T)} className={className}>
      <RTabs.List className={cx(s.tabsList, listClassName)} data-variant={variant} aria-label={ariaLabel}>
        {items.map(it => (
          <RTabs.Trigger key={it.value} value={it.value} className={s.tab}>
            {it.icon}
            {it.label}
            {it.count !== undefined && <span className={s.tabCount}>{it.count}</span>}
          </RTabs.Trigger>
        ))}
      </RTabs.List>
      {children}
    </RTabs.Root>
  )
}

export function TabPanel({ value, children, className }: { value: string; children: ReactNode; className?: string }) {
  return (
    <RTabs.Content value={value} className={cx(s.tabPanel, className)}>
      {children}
    </RTabs.Content>
  )
}
