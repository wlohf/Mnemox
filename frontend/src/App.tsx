import { lazy, Suspense, useEffect, useRef } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Spin, ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { ProtectedRoute } from './components/ProtectedRoute'
import { syncEngine } from './sync/SyncEngine'
import { notesSyncAdapter } from './sync/adapters/notesSyncAdapter'
import { goalsSyncAdapter } from './sync/adapters/goalsSyncAdapter'
import { goalTasksSyncAdapter } from './sync/adapters/goalTasksSyncAdapter'
import { ankiCardsSyncAdapter } from './sync/adapters/ankiCardsSyncAdapter'
import { wrongQuestionsSyncAdapter } from './sync/adapters/wrongQuestionsSyncAdapter'
import { useThemeStore } from './stores/themeStore'
import { useAuthStore } from './stores/authStore'
import { checkSystemUpdate } from './services/systemApi'

const ObsidianLayout = lazy(() => import('./components/Layout/ObsidianLayout').then(m => ({ default: m.ObsidianLayout })))
const PomodoroPage = lazy(() => import('./pages/PomodoroPage').then(m => ({ default: m.PomodoroPage })))
const WrongQuestionsPage = lazy(() => import('./pages/WrongQuestionsPage').then(m => ({ default: m.WrongQuestionsPage })))
const ReviewPage = lazy(() => import('./pages/ReviewPage').then(m => ({ default: m.ReviewPage })))
const GoalsTasksPage = lazy(() => import('./pages/GoalsTasksPage').then(m => ({ default: m.GoalsTasksPage })))
const NotesPage = lazy(() => import('./pages/NotesPage').then(m => ({ default: m.NotesPage })))
const MemoryPage = lazy(() => import('./pages/MemoryPage').then(m => ({ default: m.MemoryPage })))
const DashboardPage = lazy(() => import('./pages/DashboardPage').then(m => ({ default: m.DashboardPage })))
const MasteryMapPage = lazy(() => import('./pages/MasteryMapPage').then(m => ({ default: m.MasteryMapPage })))
const ProgressEnginePage = lazy(() => import('./pages/ProgressEnginePage').then(m => ({ default: m.ProgressEnginePage })))
const UserProfilePage = lazy(() => import('./pages/UserProfilePage').then(m => ({ default: m.UserProfilePage })))
const PromptsPage = lazy(() => import('./pages/PromptsPage').then(m => ({ default: m.PromptsPage })))
const LoginPage = lazy(() => import('./pages/LoginPage').then(m => ({ default: m.LoginPage })))
const EDAReportPage = lazy(() => import('./pages/EDAReportPage').then(m => ({ default: m.EDAReportPage })))
const InterventionPage = lazy(() => import('./pages/InterventionPage').then(m => ({ default: m.InterventionPage })))
const AnkiPage = lazy(() => import('./pages/AnkiPage').then(m => ({ default: m.AnkiPage })))
const PlansPage = lazy(() => import('./pages/PlansPage').then(m => ({ default: m.PlansPage })))
const AgentPage = lazy(() => import('./pages/AgentPage').then(m => ({ default: m.AgentPage })))

const PageSpinner = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
    <Spin size="large" />
  </div>
)

const UPDATE_AUTO_CHECK_KEY = 'sys_update_auto_check'
const UPDATE_INTERVAL_MIN_KEY = 'sys_update_interval_min'
const UPDATE_LAST_RESULT_KEY = 'sys_update_last'
const UPDATE_NOTIFIED_VERSION_KEY = 'sys_update_notified_version'

function isAutoCheckEnabled() {
  return localStorage.getItem(UPDATE_AUTO_CHECK_KEY) !== 'false'
}

function getAutoCheckIntervalMs() {
  const parsed = Number.parseInt(localStorage.getItem(UPDATE_INTERVAL_MIN_KEY) ?? '360', 10)
  const minutes = Number.isNaN(parsed) ? 360 : Math.min(Math.max(parsed, 5), 1440)
  return minutes * 60 * 1000
}

function notifyUpdateIfPossible(latestVersion: string) {
  const notifEnabled = localStorage.getItem('sys_notif') !== 'false'
  if (!notifEnabled || !('Notification' in window)) {
    return
  }
  if (Notification.permission === 'granted') {
    const notice = new Notification('Study Assistant 发现新版本', {
      body: `v${latestVersion} 已发布，可在系统设置中更新。`,
    })
    notice.onclick = () => {
      window.focus()
    }
  }
}

function App() {
  const resolvedTheme = useThemeStore((s) => s.resolvedTheme)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const autoCheckTimer = useRef<number | null>(null)

  useEffect(() => {
    // Register all sync adapters once. Start sync only after login to avoid
    // unauthenticated requests racing against auth bootstrap.
    syncEngine.registerAdapter(notesSyncAdapter)
    syncEngine.registerAdapter(goalsSyncAdapter)
    syncEngine.registerAdapter(goalTasksSyncAdapter)
    syncEngine.registerAdapter(ankiCardsSyncAdapter)
    syncEngine.registerAdapter(wrongQuestionsSyncAdapter)
    return () => syncEngine.stop()
  }, [])

  useEffect(() => {
    if (!isAuthenticated) {
      syncEngine.stop()
      return
    }
    syncEngine.start()
    return () => syncEngine.stop()
  }, [isAuthenticated])

  useEffect(() => {
    if (!isAuthenticated) {
      if (autoCheckTimer.current) {
        window.clearTimeout(autoCheckTimer.current)
        autoCheckTimer.current = null
      }
      return
    }

    let destroyed = false

    const runUpdateCheck = async () => {
      const result = await checkSystemUpdate()
      if (destroyed || !result) {
        return
      }

      const payload = JSON.stringify(result)
      localStorage.setItem(UPDATE_LAST_RESULT_KEY, payload)
      window.dispatchEvent(new StorageEvent('storage', { key: UPDATE_LAST_RESULT_KEY, newValue: payload }))

      if (!result.has_update || !result.latest_version) {
        return
      }

      const lastNotified = localStorage.getItem(UPDATE_NOTIFIED_VERSION_KEY)
      if (lastNotified === result.latest_version) {
        return
      }
      localStorage.setItem(UPDATE_NOTIFIED_VERSION_KEY, result.latest_version)
      notifyUpdateIfPossible(result.latest_version)
    }

    const scheduleNext = () => {
      if (destroyed) {
        return
      }
      if (!isAutoCheckEnabled()) {
        autoCheckTimer.current = null
        return
      }
      autoCheckTimer.current = window.setTimeout(async () => {
        await runUpdateCheck()
        scheduleNext()
      }, getAutoCheckIntervalMs())
    }

    if (isAutoCheckEnabled()) {
      void runUpdateCheck()
      scheduleNext()
    }

    const handleStorage = (event: StorageEvent) => {
      if (event.key !== UPDATE_AUTO_CHECK_KEY && event.key !== UPDATE_INTERVAL_MIN_KEY) {
        return
      }
      if (autoCheckTimer.current) {
        window.clearTimeout(autoCheckTimer.current)
        autoCheckTimer.current = null
      }
      if (isAutoCheckEnabled()) {
        void runUpdateCheck()
        scheduleNext()
      }
    }

    window.addEventListener('storage', handleStorage)
    return () => {
      destroyed = true
      if (autoCheckTimer.current) {
        window.clearTimeout(autoCheckTimer.current)
        autoCheckTimer.current = null
      }
      window.removeEventListener('storage', handleStorage)
    }
  }, [isAuthenticated])

  const isDark = resolvedTheme === 'dark'

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: isDark ? {
          colorPrimary: '#6366f1', // Indigo 500
          colorBgContainer: '#111827', // var(--bg-surface)
          colorBgLayout: '#0a0e1a', // var(--bg-base)
          colorBgElevated: '#1a2235', // var(--bg-elevated)
          colorBorder: 'rgba(255, 255, 255, 0.08)',
          colorBorderSecondary: 'rgba(255, 255, 255, 0.04)',
          colorText: '#f1f5f9', // var(--text-primary)
          colorTextSecondary: '#94a3b8', // var(--text-secondary)
          colorTextTertiary: '#64748b', // var(--text-tertiary)
          borderRadius: 12,
          colorLink: '#818cf8', // Indigo 400
          colorSuccess: '#2dd4bf', // Teal 400
          colorError: '#fb7185', // Rose 400
          colorWarning: '#fbbf24', // Amber 400
          colorInfo: '#818cf8', // Indigo 400
          fontFamily: "'Space Grotesk', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
        } : {
          colorPrimary: '#6366f1', // Indigo 500 (still use Indigo as primary)
          colorBgContainer: '#ffffff',
          colorBgLayout: '#f8fafc',
          colorBgElevated: '#ffffff',
          colorBorder: '#e2e8f0',
          colorBorderSecondary: '#f1f5f9',
          colorText: '#0f172a',
          colorTextSecondary: '#475569',
          colorTextTertiary: '#94a3b8',
          borderRadius: 12,
          colorLink: '#6366f1',
          colorSuccess: '#0d9488',
          colorError: '#e11d48',
          colorWarning: '#d97706',
          colorInfo: '#6366f1',
          fontFamily: "'Space Grotesk', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
        },
        components: {
          Card: {
            colorBgContainer: isDark ? '#111827' : '#ffffff',
          },
          Layout: {
            siderBg: isDark ? '#111827' : '#ffffff',
            headerBg: isDark ? '#111827' : '#ffffff',
          }
        }
      }}
    >
      <BrowserRouter>
        <Suspense fallback={<PageSpinner />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<ProtectedRoute><ObsidianLayout /></ProtectedRoute>} />
            <Route path="/pomodoro" element={<ProtectedRoute><PomodoroPage /></ProtectedRoute>} />
            <Route path="/wrong-questions" element={<ProtectedRoute><WrongQuestionsPage /></ProtectedRoute>} />
            <Route path="/review" element={<ProtectedRoute><ReviewPage /></ProtectedRoute>} />
            <Route path="/goals" element={<ProtectedRoute><GoalsTasksPage /></ProtectedRoute>} />
            <Route path="/notes" element={<ProtectedRoute><NotesPage /></ProtectedRoute>} />
            <Route path="/memory" element={<ProtectedRoute><MemoryPage /></ProtectedRoute>} />
            <Route path="/dashboard" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
            <Route path="/mastery" element={<ProtectedRoute><MasteryMapPage /></ProtectedRoute>} />
            <Route path="/progress" element={<ProtectedRoute><ProgressEnginePage /></ProtectedRoute>} />
            <Route path="/profile" element={<ProtectedRoute><UserProfilePage /></ProtectedRoute>} />
            <Route path="/prompts" element={<ProtectedRoute><PromptsPage /></ProtectedRoute>} />
            <Route path="/eda" element={<ProtectedRoute><EDAReportPage /></ProtectedRoute>} />
            <Route path="/intervention" element={<ProtectedRoute><InterventionPage /></ProtectedRoute>} />
            <Route path="/anki" element={<ProtectedRoute><AnkiPage /></ProtectedRoute>} />
            <Route path="/plans" element={<ProtectedRoute><PlansPage /></ProtectedRoute>} />
            <Route path="/agent" element={<ProtectedRoute><AgentPage /></ProtectedRoute>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App
