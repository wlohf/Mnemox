import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Spin } from 'antd'
import { ProtectedRoute } from './components/ProtectedRoute'
import { syncEngine } from './sync/SyncEngine'
import { notesSyncAdapter } from './sync/adapters/notesSyncAdapter'
import { goalsSyncAdapter } from './sync/adapters/goalsSyncAdapter'
import { goalTasksSyncAdapter } from './sync/adapters/goalTasksSyncAdapter'

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

const PageSpinner = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
    <Spin size="large" />
  </div>
)

function App() {
  useEffect(() => {
    // Register all sync adapters and start the engine
    syncEngine.registerAdapter(notesSyncAdapter)
    syncEngine.registerAdapter(goalsSyncAdapter)
    syncEngine.registerAdapter(goalTasksSyncAdapter)
    syncEngine.start()
    return () => syncEngine.stop()
  }, [])

  return (
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
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

export default App
