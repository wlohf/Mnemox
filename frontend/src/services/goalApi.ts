import { apiFetch } from './apiClient'

export interface GoalItem {
  id: number
  title: string
  description?: string | null
  target_level?: string | null
  deadline?: string | null
  status: 'active' | 'completed' | 'paused' | string
  material_id?: number | null
  material_title?: string | null
  created_at?: string | null
}

export interface GoalTaskItem {
  id: number
  goal_id: number
  parent_task_id?: number | null
  chapter_id?: number | null
  chapter_title?: string | null
  title: string
  description?: string | null
  task_type?: string | null
  planned_date?: string | null
  status: 'pending' | 'in_progress' | 'completed' | string
  completed_at?: string | null
}

export async function listGoals(status?: string): Promise<GoalItem[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  try {
    return await apiFetch<GoalItem[]>(`/api/goals${qs}`)
  } catch {
    return []
  }
}

export async function createGoal(data: {
  title: string
  description?: string
  target_level?: string
  deadline?: string
  material_id?: number
}): Promise<GoalItem | null> {
  try {
    return await apiFetch<GoalItem>('/api/goals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function updateGoal(id: number, data: Record<string, any>): Promise<GoalItem | null> {
  try {
    return await apiFetch<GoalItem>(`/api/goals/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function listGoalTasks(goalId: number): Promise<GoalTaskItem[]> {
  try {
    return await apiFetch<GoalTaskItem[]>(`/api/goals/${goalId}/tasks`)
  } catch {
    return []
  }
}

export async function createGoalTask(goalId: number, data: {
  title: string
  description?: string
  task_type?: string
  planned_date?: string
  parent_task_id?: number | null
}): Promise<GoalTaskItem | null> {
  try {
    return await apiFetch<GoalTaskItem>(`/api/goals/${goalId}/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function updateGoalTask(taskId: number, data: Record<string, any>): Promise<GoalTaskItem | null> {
  try {
    return await apiFetch<GoalTaskItem>(`/api/goals/tasks/${taskId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function deleteGoalTask(taskId: number): Promise<boolean> {
  try {
    await apiFetch(`/api/goals/tasks/${taskId}`, { method: 'DELETE' })
    return true
  } catch {
    return false
  }
}

export async function listDailyTasks(day: string): Promise<GoalTaskItem[]> {
  try {
    return await apiFetch<GoalTaskItem[]>(`/api/goals/tasks/daily?day=${encodeURIComponent(day)}`)
  } catch {
    return []
  }
}
