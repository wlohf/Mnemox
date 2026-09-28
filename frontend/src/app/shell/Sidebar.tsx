import { useMemo } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Command, LogOut, PanelLeft, RefreshCw, Rocket, Search, Settings, TriangleAlert } from 'lucide-react'
import { IconButton, Kbd, Menu, ProgressRing, Tooltip, Wordmark } from '../../ui'
import { useAuthStore } from '../../stores/authStore'
import { usePomodoroStore } from '../../stores/pomodoroStore'
import { useSyncStatus } from '../../sync/useSyncStatus'
import { syncEngine } from '../../sync/SyncEngine'
import { getDueReviewCount } from '../../services/reviewApi'
import { listAgentMemoryCandidates } from '../../services/agentApi'
import { listConversations } from '../../services/conversationApi'
import { getConversationPath } from '../../services/conversationRoute'
import { NAV_GROUPS, PRIMARY_NAV, isEntryActive, type NavEntry } from '../nav'
import { qk } from '../queryClient'
import { useShell } from './shellStore'
import s from './shell.module.css'

function formatClock(seconds: number) {
  const m = Math.floor(seconds / 60)
  const sec = Math.floor(seconds % 60)
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

function useNavBadges(enabled: boolean) {
  const review = useQuery({ queryKey: qk.reviewDue, queryFn: getDueReviewCount, enabled, refetchInterval: 5 * 60_000 })
  const memory = useQuery({ queryKey: qk.memoryCandidates, queryFn: listAgentMemoryCandidates, enabled, staleTime: 60_000 })
  return {
    reviewDue: review.data ?? 0,
    wrongDue: 0,
    memoryPending: (memory.data ?? []).filter(c => (c.review_status ?? c.status) === 'staged').length,
  }
}

export function Sidebar({ ready, inert }: { ready: boolean; inert?: boolean }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const user = useAuthStore(st => st.user)
  const logout = useAuthStore(st => st.logout)
  const collapsed = useShell(st => st.sidebarCollapsed)
  const { toggleSidebar, setCommandOpen, setMobileNav, openSettings, setOnboardingOpen, setConflictsOpen } = useShell()
  const badges = useNavBadges(ready)
  const recents = useQuery({
    queryKey: qk.conversations(),
    queryFn: () => listConversations(),
    enabled: ready,
    staleTime: 20_000,
  })

  const go = (path: string) => {
    navigate(path)
    setMobileNav(false)
  }

  const item = (n: NavEntry) => {
    const active = isEntryActive(pathname, n)
    const count = n.badgeKey ? badges[n.badgeKey] : 0
    return (
      <Tooltip key={n.key} label={n.label} side="right" disabled={!collapsed}>
        <button
          type="button"
          className={s.navItem}
          aria-current={active ? 'page' : undefined}
          data-badge={count > 0 || undefined}
          onClick={() => go(n.path)}
        >
          {n.icon}
          <span className={s.navText}>{n.label}</span>
          {count > 0 && (
            <span className={s.navBadge} data-tone={n.badgeKey === 'reviewDue' ? 'evidence' : n.badgeKey === 'memoryPending' ? 'ink' : undefined}>
              {count > 99 ? '99+' : count}
            </span>
          )}
        </button>
      </Tooltip>
    )
  }

  const recentList = useMemo(() => {
    const list = recents.data ?? []
    return [...list]
      .sort((a, b) => Number(b.is_pinned) - Number(a.is_pinned) || (a.updated_at < b.updated_at ? 1 : -1))
      .slice(0, 4)
  }, [recents.data])

  return (
    <aside
      className={s.sidebar}
      aria-label="主导航"
      aria-hidden={inert || undefined}
      ref={node => {
        if (node) (node as HTMLElement & { inert: boolean }).inert = Boolean(inert)
      }}
    >
      <div className={s.brandRow}>
        <button type="button" className={s.brandLink} onClick={() => go('/today')} aria-label="Mnemox 首页">
          <Wordmark compact={collapsed} />
        </button>
        <span className={`${s.brandToggle} ${s.desktopOnly}`}>
          <IconButton label="收起侧栏" kbd={['Ctrl', '\\']} size="sm" onClick={toggleSidebar}>
            <PanelLeft />
          </IconButton>
        </span>
      </div>

      <button type="button" className={s.search} onClick={() => setCommandOpen(true)} aria-label="搜索或跳转">
        <Search />
        <span className={s.searchText}>搜索或跳转…</span>
        <span className={s.searchKeys}>
          <Kbd>
            <Command size={10} />
          </Kbd>
          <Kbd>K</Kbd>
        </span>
      </button>

      <nav className={s.navScroll} aria-label="页面">
        <div className={s.navGroup}>
          {PRIMARY_NAV.map(item)}
          {recentList.length > 0 && (
            <div className={s.recent}>
              {recentList.map(c => (
                <button
                  key={c.id}
                  type="button"
                  className={s.recentItem}
                  aria-current={pathname === getConversationPath(c.id) ? 'page' : undefined}
                  title={c.title}
                  onClick={() => go(getConversationPath(c.id))}
                >
                  {c.title || '未命名对话'}
                </button>
              ))}
            </div>
          )}
        </div>
        {NAV_GROUPS.map(g => (
          <div key={g.key} className={s.navGroup}>
            <div className={s.navLabel}>{g.label}</div>
            {g.items.map(item)}
          </div>
        ))}
      </nav>

      <FocusDock onOpen={() => go('/pomodoro')} />
      <ConflictButton />

      <div className={s.account}>
        <Menu
          side="top"
          align="start"
          minWidth={220}
          trigger={
            <button type="button" className={s.accountButton} aria-label="账户和设置">
              <span className={s.avatar}>{(user?.username ?? '?').slice(0, 1).toUpperCase()}</span>
              <span className={s.accountText}>
                <span className={s.accountName}>{user?.username ?? '未登录'}</span>
                <SyncLine />
              </span>
            </button>
          }
          items={[
            { key: 'settings', label: '设置', icon: <Settings />, hint: 'Ctrl ,', onSelect: () => openSettings('appearance') },
            { key: 'sync', label: '立即同步', icon: <RefreshCw />, onSelect: () => void syncEngine.syncAll({ retryFailed: true }) },
            { key: 'conflicts', label: '处理同步冲突', icon: <TriangleAlert />, onSelect: () => setConflictsOpen(true) },
            { key: 'guide', label: '新手引导 / Demo', icon: <Rocket />, onSelect: () => setOnboardingOpen(true) },
            { key: 'sep', type: 'separator' },
            {
              key: 'logout',
              label: '退出登录',
              icon: <LogOut />,
              tone: 'danger',
              onSelect: () => {
                logout()
                navigate('/login', { replace: true })
              },
            },
          ]}
        />
        <span className={`${s.accountTools}`}>
          <IconButton label="设置" kbd={['Ctrl', ',']} size="sm" onClick={() => openSettings('appearance')}>
            <Settings />
          </IconButton>
        </span>
      </div>
    </aside>
  )
}

function SyncLine() {
  const { status, online, failedCount, conflictCount } = useSyncStatus()
  let state: 'ok' | 'syncing' | 'offline' | 'error' | 'conflict' = 'ok'
  let text = '已同步'
  if (conflictCount > 0) {
    state = 'conflict'
    text = '有同步冲突'
  } else if (!online || status === 'offline') {
    state = 'offline'
    text = '离线 · 改动稍后同步'
  } else if (status === 'syncing') {
    state = 'syncing'
    text = '同步中…'
  } else if (status === 'error' || failedCount > 0) {
    state = 'error'
    text = failedCount > 0 ? `同步失败 ${failedCount}` : '同步出错'
  }
  return (
    <span className={s.syncLine} data-state={state}>
      <i className={s.syncDot} />
      {text}
    </span>
  )
}

/** A dedicated, focusable entry to the conflict resolver (never nested in the menu trigger). */
function ConflictButton() {
  const { conflictCount } = useSyncStatus()
  const setConflictsOpen = useShell(st => st.setConflictsOpen)
  if (conflictCount <= 0) return null
  return (
    <button type="button" className={s.conflictButton} onClick={() => setConflictsOpen(true)}>
      <TriangleAlert aria-hidden />
      <span className={s.conflictText}>待处理 {conflictCount}</span>
    </button>
  )
}

function FocusDock({ onOpen }: { onOpen: () => void }) {
  const isRunning = usePomodoroStore(st => st.isRunning)
  const isPaused = usePomodoroStore(st => st.isPaused)
  const remaining = usePomodoroStore(st => st.remainingTime)
  const duration = usePomodoroStore(st => st.duration)
  const task = usePomodoroStore(st => st.currentTask)
  const mode = usePomodoroStore(st => st.timerMode)
  if (!isRunning && !isPaused) return null
  const progress = duration > 0 ? 1 - remaining / (duration * 60) : 0
  const color = mode === 'break' ? 'var(--mx-success)' : 'var(--mx-evidence)'
  return (
    <button
      type="button"
      className={s.focusDock}
      data-paused={isPaused || undefined}
      onClick={onOpen}
      aria-label={`${mode === 'break' ? '休息中' : '专注中'} ${formatClock(remaining)}，打开专注页`}
    >
      <ProgressRing value={progress} size={30} stroke={3} color={color}>
        <span className={s.focusPulse} style={{ color }} />
      </ProgressRing>
      <span className={s.focusMeta}>
        <span className={s.focusTime}>{formatClock(remaining)}</span>
        <span className={s.focusLabel}>
          {isPaused ? '已暂停' : mode === 'break' ? '休息中' : '专注中'}
          {task && mode !== 'break' ? ` · ${task}` : ''}
        </span>
      </span>
    </button>
  )
}
