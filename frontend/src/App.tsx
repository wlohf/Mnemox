import { lazy, useEffect, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { Toaster, TooltipProvider, toast } from './ui'
import { queryClient } from './app/queryClient'
import { AppShell } from './app/shell/AppShell'
import { useUpdateCheck } from './app/shell/globalBehaviours'
import { LegacyBoundary } from './app/LegacyBoundary'
import { setNotifySink } from './services/notify'
import './app/legacy.css'
import { syncEngine } from './sync/SyncEngine'
import { notesSyncAdapter } from './sync/adapters/notesSyncAdapter'
import { goalsSyncAdapter } from './sync/adapters/goalsSyncAdapter'
import { goalTasksSyncAdapter } from './sync/adapters/goalTasksSyncAdapter'
import { ankiCardsSyncAdapter } from './sync/adapters/ankiCardsSyncAdapter'
import { wrongQuestionsSyncAdapter } from './sync/adapters/wrongQuestionsSyncAdapter'
import { useAuthStore } from './stores/authStore'
import { usePomodoroStore } from './stores/pomodoroStore'
import { PomodoroTicker } from './components/PomodoroTicker'
import { AuthGate } from './app/AuthGate'
import { SettingsRedirect } from './app/SettingsRedirect'

// Rebuilt screens (Mnemox UI kit)
const TodayPage = lazy(() => import('./features/today/TodayPage').then(m => ({ default: m.TodayPage })))
const LoginPage = lazy(() => import('./features/auth/LoginPage').then(m => ({ default: m.LoginPage })))
const CoachPage = lazy(() => import('./features/coach/CoachPage').then(m => ({ default: m.CoachPage })))
const ReviewPage = lazy(() => import('./features/review/ReviewPage').then(m => ({ default: m.ReviewPage })))
const FocusPage = lazy(() => import('./features/focus/FocusPage').then(m => ({ default: m.FocusPage })))
const NotesPage = lazy(() => import('./features/notes/NotesPage').then(m => ({ default: m.NotesPage })))
const GoalsPage = lazy(() => import('./features/goals/GoalsPage').then(m => ({ default: m.GoalsPage })))
const WrongQuestionsPage = lazy(() => import('./features/wrong/WrongQuestionsPage').then(m => ({ default: m.WrongQuestionsPage })))
const MaterialsPage = lazy(() => import('./features/materials/MaterialsPage').then(m => ({ default: m.MaterialsPage })))
const CardsPage = lazy(() => import('./features/cards/CardsPage').then(m => ({ default: m.CardsPage })))
const MemoryPage = lazy(() => import('./features/memory/MemoryPage').then(m => ({ default: m.MemoryPage })))
const PlansPage = lazy(() => import('./features/plans/PlansPage').then(m => ({ default: m.PlansPage })))
const MasteryPage = lazy(() => import('./features/mastery/MasteryPage').then(m => ({ default: m.MasteryPage })))
const ReportPage = lazy(() => import('./features/report/ReportPage').then(m => ({ default: m.ReportPage })))

// Screens still on the legacy stack; rendered inside the new shell.
const ProgressEnginePage = lazy(() => import('./pages/ProgressEnginePage').then(m => ({ default: m.ProgressEnginePage })))
const AgentPage = lazy(() => import('./pages/AgentPage').then(m => ({ default: m.AgentPage })))
const KnowledgeLabPage = lazy(() => import('./pages/KnowledgeLabPage').then(m => ({ default: m.KnowledgeLabPage })))

// Route services' notifications into the new toast system.
setNotifySink((level, text) => {
  if (level === 'error') toast.error(text)
  else if (level === 'warning') toast.warning(text)
  else if (level === 'success') toast.success(text)
  else toast.info(text)
})

const legacy = (node: ReactNode) => <LegacyBoundary>{node}</LegacyBoundary>

function ScrollReset() {
  const { pathname } = useLocation()
  useEffect(() => {
    document.getElementById('mx-scroll')?.scrollTo({ top: 0 })
  }, [pathname])
  return null
}

function App() {
  const isAuthenticated = useAuthStore(st => st.isAuthenticated)
  const userId = useAuthStore(st => st.user?.id)
  const refreshPomodoroRecords = usePomodoroStore(st => st.refreshRecordsFromBackend)

  useEffect(() => {
    syncEngine.registerAdapter(notesSyncAdapter)
    syncEngine.registerAdapter(goalsSyncAdapter)
    syncEngine.registerAdapter(goalTasksSyncAdapter)
    syncEngine.registerAdapter(ankiCardsSyncAdapter)
    syncEngine.registerAdapter(wrongQuestionsSyncAdapter)
  }, [])

  useEffect(() => {
    if (isAuthenticated) {
      syncEngine.start(true)
      void refreshPomodoroRecords()
    } else {
      syncEngine.stop()
      queryClient.clear()
    }
    return () => syncEngine.stop()
  }, [isAuthenticated, userId, refreshPomodoroRecords])

  useUpdateCheck(isAuthenticated)

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <PomodoroTicker />
        <BrowserRouter>
          <ScrollReset />
          <Routes key={userId ?? 'guest'}>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<AuthGate><AppShell /></AuthGate>}>
              <Route path="/today" element={<TodayPage />} />
              <Route path="/dashboard" element={<Navigate to="/today" replace />} />
              <Route path="/" element={<CoachPage />} />
              <Route path="/conversations/:conversationId" element={<CoachPage />} />
              <Route path="/pomodoro" element={<FocusPage />} />
              <Route path="/wrong-questions" element={<WrongQuestionsPage />} />
              <Route path="/review" element={<ReviewPage />} />
              <Route path="/goals" element={<GoalsPage />} />
              <Route path="/notes" element={<NotesPage />} />
              <Route path="/materials" element={<MaterialsPage />} />
              <Route path="/memory" element={<MemoryPage />} />
              <Route path="/mastery" element={<MasteryPage />} />
              <Route path="/progress" element={legacy(<ProgressEnginePage />)} />
              <Route path="/profile" element={<Navigate to="/eda#profile" replace />} />
              <Route path="/prompts" element={<SettingsRedirect section="prompts" />} />
              <Route path="/eda" element={<ReportPage />} />
              <Route path="/intervention" element={<Navigate to="/eda?tab=intervention" replace />} />
              <Route path="/agent" element={legacy(<AgentPage />)} />
              <Route path="/anki" element={<CardsPage />} />
              <Route path="/plans" element={<PlansPage />} />
              <Route path="/knowledge-lab" element={legacy(<KnowledgeLabPage />)} />
            </Route>
            <Route path="*" element={<Navigate to="/today" replace />} />
          </Routes>
        </BrowserRouter>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  )
}

export default App
