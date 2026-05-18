import { apiFetch } from './apiClient'

export interface DashboardAction {
  type: string
  title: string
  item_id: number
}

export interface DashboardData {
  today: string
  today_task_count: number
  today_pending_count: number
  today_completed_count: number
  due_review_count: number
  today_pomodoro_count: number
  today_study_minutes: number
  today_mission?: {
    kind: 'review' | 'task' | 'focus' | 'reflection' | 'setup' | string
    title: string
    reason: string
    cta: string
    route: string
    estimated_minutes: number
    active_recall_prompt: string
  }
  recommended_actions: DashboardAction[]
  today_tasks: Array<{ id: number; title: string; task_type?: string; status: string }>
}

export interface MasteryMapData {
  materials: Array<{
    material_id: number
    material_title: string
    average_mastery: number
    chapter_count: number
    chapters: Array<{
      chapter_id: number
      chapter_title: string
      mastery_level: number
      band: 'weak' | 'medium' | 'strong' | string
    }>
  }>
  weak_points: Array<{
    material_title: string
    chapter_title: string
    mastery_level: number
  }>
}

export interface ProgressMaterialItem {
  material_id: number
  title: string
  is_textbook: boolean
  profile_source?: string | null
  textbook_confidence: number
  chapter_count: number
  chapter_progress: number
  chapter_completion: number
  practice_correct_rate: number
  question_type_coverage?: number
  wrong_fix_rate: number
  task_completion_rate?: number
  task_type_coverage?: number
  task_execution_quality?: number
  output_quality: number
  overall_progress: number
  structure?: any
}

export interface ProgressEngineData {
  total_progress: number
  material_count: number
  weights?: {
    chapter: number
    quiz: number
    wrong: number
    output: number
  }
  materials: ProgressMaterialItem[]
}

export interface OutputEvalResult {
  task_id: number
  task_title: string
  score: number
  strengths: string[]
  gaps: string[]
  next_actions: string[]
  verdict: string
}

export async function getDashboard(): Promise<DashboardData> {
  return await apiFetch<DashboardData>('/api/learning/dashboard')
}

export async function getMasteryMap(): Promise<MasteryMapData> {
  return await apiFetch<MasteryMapData>('/api/learning/mastery-map')
}

export async function getProgressEngine(
  includeNonTextbook = false,
  weights?: { chapter: number; quiz: number; wrong: number; output: number }
): Promise<ProgressEngineData> {
  const query = new URLSearchParams()
  query.set('include_non_textbook', includeNonTextbook ? 'true' : 'false')
  if (weights) {
    query.set('w_chapter', String(weights.chapter))
    query.set('w_quiz', String(weights.quiz))
    query.set('w_wrong', String(weights.wrong))
    query.set('w_output', String(weights.output))
  }
  return await apiFetch<ProgressEngineData>(`/api/learning/progress-engine?${query.toString()}`)
}

export async function analyzeMaterialForProgress(materialId: number): Promise<{
  material_id: number
  is_textbook: boolean
  confidence: number
  created_chapters: number
  chapter_count: number
}> {
  return await apiFetch(`/api/learning/materials/${materialId}/analyze`, { method: 'POST' })
}

export async function setMaterialClassification(materialId: number, isTextbook: boolean): Promise<boolean> {
  await apiFetch(`/api/learning/materials/${materialId}/classification`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_textbook: isTextbook }),
  })
  return true
}

export async function getMaterialLearningPlan(materialId: number): Promise<{
  material_id: number
  material_title: string
  chapter_path: Array<{
    chapter_id: number
    chapter_title: string
    mastery_level: number
    question_count: number
    question_types: string[]
    wrong_count: number
    priority: 'high' | 'medium' | 'low' | string
  }>
  training_pack: Array<{
    question_type: string
    total: number
    wrong: number
    difficulty: string
    suggest_count: number
  }>
}> {
  return await apiFetch(`/api/learning/progress-engine/materials/${materialId}/plan`)
}

export async function generateTrainingTasks(materialId: number, questionTypes?: string[]): Promise<{
  material_id: number
  goal_id: number
  created_task_count: number
}> {
  return await apiFetch(`/api/learning/progress-engine/materials/${materialId}/generate-training-tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ material_id: materialId, question_types: questionTypes || [] }),
  })
}

export async function generate7DayPlan(materialId: number, days = 7): Promise<{
  material_id: number
  goal_id: number
  created_task_count: number
  days: number
}> {
  return await apiFetch(`/api/learning/progress-engine/materials/${materialId}/generate-7day-plan?days=${days}`, {
    method: 'POST',
  })
}

export async function adaptiveReplan(materialId: number, params?: {
  days?: number
  focus_mode?: 'balanced' | 'weak_first' | 'output_first'
}): Promise<{
  material_id: number
  goal_id: number
  focus_mode: string
  rescheduled: number
  days: number
  preview: Array<{ task_id: number; title: string; task_type?: string; planned_date?: string | null; priority: number }>
}> {
  return await apiFetch(`/api/learning/progress-engine/materials/${materialId}/adaptive-replan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      days: params?.days ?? 7,
      focus_mode: params?.focus_mode ?? 'balanced',
    }),
  })
}

export async function evaluateTaskOutput(data: {
  task_id: number
  output_text: string
  rubric?: string
  mark_task_completed?: boolean
}): Promise<OutputEvalResult> {
  return await apiFetch<OutputEvalResult>('/api/learning/evaluate-output', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function startLearningPipeline(materialId: number): Promise<{
  material_id: number
  is_textbook: boolean
  confidence: number
  created_chapters: number
  chapter_count: number
  goal_id: number | null
  auto_created_tasks: number
  tasks: Array<{ id: number; title: string; task_type?: string; status: string; planned_date?: string | null }>
}> {
  return await apiFetch(`/api/learning/materials/${materialId}/start-learning`, { method: 'POST' })
}

export interface BatchLearningResult {
  material_id: number
  material_title?: string | null
  error?: string
  goal_id: number | null
  auto_created_tasks: number
  tasks: Array<{ id: number; title: string; task_type?: string; status: string; planned_date?: string | null }>
}

export async function startBatchLearningPipeline(materialIds: number[]): Promise<{
  results: BatchLearningResult[]
  total_tasks: number
}> {
  return await apiFetch('/api/learning/materials/batch-start-learning', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ material_ids: materialIds }),
  })
}

export async function generateDailyPlan(date: string): Promise<{
  date: string
  content: string
  item_count: number
  items: Array<{ type: string; emoji: string; label: string; priority: number; id: number }>
}> {
  return await apiFetch(`/api/plans/generate/${date}`, { method: 'POST' })
}
