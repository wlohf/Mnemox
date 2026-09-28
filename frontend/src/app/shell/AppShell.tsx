import { Suspense, lazy, useEffect, type ReactNode } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { ChevronRight, CloudOff, Maximize2, Menu, Minimize2, Moon, PanelLeft, PanelRight, Sun } from 'lucide-react'
import { IconButton, Skeleton } from '../../ui'
import { useThemeStore } from '../../stores/themeStore'
import { useSyncStatus } from '../../sync/useSyncStatus'
import { findActiveEntry, groupOf } from '../nav'
import { useBackendReady } from '../useBackendReady'
import { useChrome, useShell } from './shellStore'
import { Sidebar } from './Sidebar'
import { CommandPalette } from './CommandPalette'
import { BackendWaiting } from './BackendWaiting'
import { useCoachNudges, useDailyIntervention, useOnboardingAutoShow } from './globalBehaviours'
import s from './shell.module.css'

const SettingsDialog = lazy(() => import('../../features/settings/SettingsDialog').then(m => ({ default: m.SettingsDialog })))
const OnboardingDialog = lazy(() => import('../../features/onboarding/OnboardingDialog').then(m => ({ default: m.OnboardingDialog })))
const ConflictDialog = lazy(() => import('../../features/sync/ConflictDialog').then(m => ({ default: m.ConflictDialog })))

function isEditableTarget(t: EventTarget | null) {
  const el = t as HTMLElement | null
  return !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))
}

function useShellShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const st = useShell.getState()
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        st.setCommandOpen(!st.commandOpen)
      } else if (mod && e.key === '\\') {
        e.preventDefault()
        st.toggleSidebar()
      } else if (mod && e.key === '.') {
        e.preventDefault()
        st.toggleAside()
      } else if (mod && e.key === ',') {
        e.preventDefault()
        st.openSettings('appearance')
      } else if (e.key === 'Escape' && !e.defaultPrevented) {
        // Layers (dialogs, menus) handle Escape first and prevent default.
        if (st.mobileNavOpen) st.setMobileNav(false)
        else if (st.asideOpen && window.innerWidth <= 1180) st.setAsideOpen(false)
        else if (st.immersive && !isEditableTarget(e.target)) st.setImmersive(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}

function Breadcrumbs({ title }: { title?: ReactNode }) {
  const { pathname } = useLocation()
  const entry = findActiveEntry(pathname)
  const group = entry ? groupOf(entry) : undefined
  return (
    <nav className={s.crumbs} aria-label="位置">
      {group && (
        <>
          <span>{group.label}</span>
          <ChevronRight aria-hidden />
        </>
      )}
      <strong>{title ?? entry?.label ?? 'Mnemox'}</strong>
    </nav>
  )
}

function OfflinePill() {
  const { online } = useSyncStatus()
  if (online) return null
  return (
    <span className={s.offlinePill} role="status">
      <CloudOff aria-hidden />
      离线模式
    </span>
  )
}

function ChromeTopbar() {
  const chrome = useChrome()
  const { sidebarCollapsed, setSidebarCollapsed, setMobileNav, asideOpen, toggleAside, immersive, setImmersive } = useShell()
  const dark = useThemeStore(st => st.resolvedTheme === 'dark')
  const toggleTheme = useThemeStore(st => st.toggle)
  return (
    <div className={s.topbar}>
      <span className={s.mobileOnly}>
        <IconButton label="打开导航" onClick={() => setMobileNav(true)}>
          <Menu />
        </IconButton>
      </span>
      {sidebarCollapsed && !immersive && (
        <span className={s.desktopOnly}>
          <IconButton label="展开侧栏" kbd={['Ctrl', '\\']} onClick={() => setSidebarCollapsed(false)}>
            <PanelLeft />
          </IconButton>
        </span>
      )}
      <Breadcrumbs title={chrome.title} />
      <div className={s.topbarEnd}>
        <OfflinePill />
        {chrome.actions && <div className={s.topbarSlot}>{chrome.actions}</div>}
        <IconButton
          label={immersive ? '退出沉浸模式' : '进入沉浸模式'}
          aria-pressed={immersive}
          className={s.desktopOnly}
          onClick={() => setImmersive(!immersive)}
        >
          {immersive ? <Minimize2 /> : <Maximize2 />}
        </IconButton>
        <IconButton label={dark ? '切换到浅色' : '切换到深色'} onClick={toggleTheme}>
          {dark ? <Sun /> : <Moon />}
        </IconButton>
        {chrome.aside && (
          <>
            <span className={s.vDivider} />
            <IconButton label={chrome.asideLabel ?? '上下文面板'} kbd={['Ctrl', '.']} active={asideOpen} onClick={toggleAside}>
              <PanelRight />
            </IconButton>
          </>
        )}
      </div>
    </div>
  )
}

/** Routes that are one screen (e.g. every conversation) share a key so they don't remount. */
function routeKey(pathname: string) {
  if (pathname === '/' || pathname.startsWith('/conversations/')) return 'coach'
  return pathname
}

function RouteFallback() {
  return (
    <div style={{ maxWidth: 1088, margin: '0 auto', padding: '28px 40px' }} aria-busy="true" aria-label="正在加载">
      <Skeleton width={120} height={12} />
      <Skeleton width={280} height={28} style={{ marginTop: 12 }} />
      <Skeleton height={180} radius={12} style={{ marginTop: 28 }} />
    </div>
  )
}

export function AppShell() {
  const { ready } = useBackendReady()
  const location = useLocation()
  const chrome = useChrome()
  const { sidebarCollapsed, asideOpen, setAsideOpen, mobileNavOpen, setMobileNav, immersive, settingsOpen, onboardingOpen, conflictsOpen } = useShell()
  const bgImage = useThemeStore(st => st.bgImage)
  const bgOpacity = useThemeStore(st => st.bgOpacity)

  useShellShortcuts()
  useCoachNudges(ready)
  useDailyIntervention(ready)
  useOnboardingAutoShow(ready)

  // Close transient layers on navigation.
  useEffect(() => {
    setMobileNav(false)
  }, [location.pathname, setMobileNav])

  // A page without an aside can't leave the panel open.
  useEffect(() => {
    if (!chrome.aside && asideOpen) setAsideOpen(false)
  }, [chrome.aside, asideOpen, setAsideOpen])

  const hasAside = Boolean(chrome.aside)
  return (
    <div
      className={s.shell}
      data-sidebar={sidebarCollapsed ? 'collapsed' : undefined}
      data-evidence={hasAside && asideOpen ? 'open' : undefined}
      data-mobile-nav={mobileNavOpen ? 'open' : undefined}
      data-immersive={immersive || undefined}
    >
      {bgImage && (
        <div className={s.bgImage} aria-hidden style={{ backgroundImage: `url(${bgImage})`, opacity: bgOpacity }} />
      )}
      <Sidebar ready={ready} inert={immersive} />

      <main className={s.main} id="mx-main">
        <ChromeTopbar />
        <div className={s.scroll} data-bare={chrome.bare || undefined} id="mx-scroll">
          {ready ? (
            <Suspense fallback={<RouteFallback />}>
              <div key={routeKey(location.pathname)} className={s.routeView} data-bare={chrome.bare || undefined}>
                <Outlet />
              </div>
            </Suspense>
          ) : (
            <BackendWaiting />
          )}
        </div>
      </main>

      <aside className={s.aside} aria-label={chrome.asideLabel ?? '上下文'} aria-hidden={!(hasAside && asideOpen)}>
        <div className={s.asideInner}>{chrome.aside}</div>
      </aside>

      <div
        className={s.scrim}
        onClick={() => {
          setMobileNav(false)
          setAsideOpen(false)
        }}
        aria-hidden
      />

      <CommandPalette />
      <Suspense fallback={null}>
        {settingsOpen && <SettingsDialog />}
        {onboardingOpen && <OnboardingDialog />}
        {conflictsOpen && <ConflictDialog />}
      </Suspense>
    </div>
  )
}
