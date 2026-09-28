import { Suspense, lazy, type ReactNode } from 'react'
import * as RDialog from '@radix-ui/react-dialog'
import { Bell, Bot, Cpu, Palette, Quote, ScrollText, ServerCog, X } from 'lucide-react'
import { IconButton, Skeleton } from '../../ui'
import { useShell, type SettingsSection } from '../../app/shell/shellStore'
import overlay from '../../ui/overlays.module.css'
import s from './settings.module.css'

const AppearanceSection = lazy(() => import('./sections/AppearanceSection').then(m => ({ default: m.AppearanceSection })))
const AISection = lazy(() => import('./sections/AISection').then(m => ({ default: m.AISection })))
const CoachSection = lazy(() => import('./sections/CoachSection').then(m => ({ default: m.CoachSection })))
const PromptsSection = lazy(() => import('./sections/PromptsSection').then(m => ({ default: m.PromptsSection })))
const MotivationSection = lazy(() => import('./sections/MotivationSection').then(m => ({ default: m.MotivationSection })))
const SystemSection = lazy(() => import('./sections/SystemSection').then(m => ({ default: m.SystemSection })))

const SECTIONS: Array<{ key: SettingsSection; label: string; icon: ReactNode; title: string; desc: string }> = [
  { key: 'appearance', label: '外观', icon: <Palette />, title: '外观', desc: '主题与背景。浅色适合白天，深色适合夜里长时间学习。' },
  { key: 'ai', label: 'AI 模型', icon: <Cpu />, title: 'AI 模型与联网', desc: '配置模型供应商、各场景使用的模型，以及联网搜索。API Key 加密保存在本地。' },
  { key: 'coach', label: '教练与提醒', icon: <Bell />, title: '教练与提醒', desc: '教练什么时候主动找你、通过什么方式、多频繁。' },
  { key: 'prompts', label: '提示词', icon: <ScrollText />, title: '提示词', desc: '每种学习场景都有独立的提示词。自定义之后会优先使用你的版本。' },
  { key: 'motivation', label: '激励语录', icon: <Quote />, title: '激励语录', desc: '「今天」页面和专注页面展示的那一句话。' },
  { key: 'system', label: '系统与更新', icon: <ServerCog />, title: '系统与更新', desc: '版本、更新检查和通知。' },
]

export function SettingsDialog() {
  const open = useShell(st => st.settingsOpen)
  const section = useShell(st => st.settingsSection)
  const close = useShell(st => st.closeSettings)
  const arg = useShell(st => st.settingsArg)
  const go = (k: SettingsSection) => useShell.setState({ settingsSection: k })
  const current = SECTIONS.find(x => x.key === section) ?? SECTIONS[0]

  return (
    <RDialog.Root open={open} onOpenChange={v => !v && close()}>
      <RDialog.Portal>
        <RDialog.Overlay className={overlay.overlay} />
        <RDialog.Content className={s.dialog} aria-describedby={undefined}>
          <nav className={s.nav} role="tablist" aria-label="设置分区" aria-orientation="vertical">
            <RDialog.Title className={s.navTitle}>设置</RDialog.Title>
            {SECTIONS.map(x => (
              <button
                key={x.key}
                type="button"
                role="tab"
                aria-selected={x.key === current.key}
                className={s.navItem}
                onClick={() => go(x.key)}
              >
                {x.icon}
                {x.label}
              </button>
            ))}
            <p className={s.navFoot}>
              <Bot size={12} style={{ display: 'inline', verticalAlign: '-2px', marginRight: 4 }} aria-hidden />
              所有设置只作用于当前账号。
            </p>
          </nav>
          <section className={s.body} role="tabpanel" aria-label={current.title}>
            <div className={s.bodyHead}>
              <div className={s.bodyHeadText}>
                <h2 className={s.bodyTitle}>{current.title}</h2>
                <p className={s.bodyDesc}>{current.desc}</p>
              </div>
              <RDialog.Close asChild>
                <IconButton label="关闭设置" size="sm" noTooltip>
                  <X />
                </IconButton>
              </RDialog.Close>
            </div>
            <div className={s.bodyScroll}>
              <Suspense
                fallback={
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <Skeleton height={52} radius={12} />
                    <Skeleton height={52} radius={12} />
                    <Skeleton height={120} radius={12} />
                  </div>
                }
              >
                {current.key === 'appearance' && <AppearanceSection />}
                {current.key === 'ai' && <AISection />}
                {current.key === 'coach' && <CoachSection />}
                {current.key === 'prompts' && <PromptsSection initialKey={arg ?? undefined} />}
                {current.key === 'motivation' && <MotivationSection />}
                {current.key === 'system' && <SystemSection />}
              </Suspense>
            </div>
          </section>
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  )
}

/* ---------------- shared layout helpers for sections ---------------- */
export function Group({ title, desc, children }: { title?: ReactNode; desc?: ReactNode; children: ReactNode }) {
  return (
    <div className={s.group}>
      {title && <h3 className={s.groupTitle}>{title}</h3>}
      {desc && <p className={s.groupDesc}>{desc}</p>}
      {children}
    </div>
  )
}

export function Rows({ children }: { children: ReactNode }) {
  return <div className={s.rows}>{children}</div>
}

export function Row({ label, hint, children, htmlFor }: { label: ReactNode; hint?: ReactNode; children?: ReactNode; htmlFor?: string }) {
  return (
    <div className={s.row}>
      <div className={s.rowText}>
        <label className={s.rowLabel} htmlFor={htmlFor}>
          {label}
        </label>
        {hint && <span className={s.rowHint}>{hint}</span>}
      </div>
      {children && <div className={s.rowControl}>{children}</div>}
    </div>
  )
}

export const settingsStyles = s
