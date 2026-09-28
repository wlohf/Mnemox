import { QueryClient } from '@tanstack/react-query'
import { ApiRequestError } from '../services/apiClient'

/**
 * Server-state cache for rebuilt screens. Offline-first modules (notes, goals,
 * tasks, cards, wrong questions) keep reading from IndexedDB via Dexie hooks.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 10 * 60_000,
      refetchOnWindowFocus: true,
      retry: (count, error) => {
        if (error instanceof ApiRequestError && error.status && error.status < 500) return false
        return count < 2
      },
    },
    mutations: {
      retry: false,
    },
  },
})

/** Query keys shared across screens so invalidation stays consistent. */
export const qk = {
  dashboard: ['learning', 'dashboard'] as const,
  goalContext: (goalId?: number) => ['agent', 'goal-context', goalId ?? 'active'] as const,
  brief: (llm = false) => ['agent', 'brief', llm] as const,
  dailyTasks: (day: string) => ['goals', 'daily', day] as const,
  goals: ['goals'] as const,
  reviewDue: ['review', 'due-count'] as const,
  reviewTasks: (scope: string, type: string) => ['review', 'tasks', scope, type] as const,
  masteryMap: ['learning', 'mastery-map'] as const,
  memoryCandidates: ['agent', 'memory', 'candidates'] as const,
  memories: ['memory', 'list'] as const,
  memoryConflicts: ['memory', 'conflicts'] as const,
  coreProfile: ['agent', 'memory', 'core-profile'] as const,
  coachNudges: ['coach', 'nudges'] as const,
  coachPreferences: ['coach', 'preferences'] as const,
  conversations: (search = '', projectId?: number) => ['conversations', search, projectId ?? 'all'] as const,
  conversation: (id: number) => ['conversation', id] as const,
  projects: ['chat-projects'] as const,
  motivation: ['motivation', 'current'] as const,
  onboarding: ['system', 'onboarding'] as const,
  profile: ['profile'] as const,
  pomodoroDaily: (days: number) => ['pomodoro', 'daily', days] as const,
  providers: ['ai-settings', 'providers'] as const,
  materials: ['materials'] as const,
  wrongQuestions: ['wrong-questions'] as const,
  intervention: ['interventions', 'daily'] as const,
}
