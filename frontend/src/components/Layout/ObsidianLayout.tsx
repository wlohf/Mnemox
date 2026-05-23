import { useState, useEffect, useRef, useCallback, useMemo, lazy, Suspense } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  Layout,
  Card,
  List,
  Button,
  Input,
  InputNumber,
  DatePicker,
  Modal,
  Progress,
  message,
  notification,
  Upload,
  Calendar,
  Badge,
  Drawer,
  Statistic,
  Row,
  Col,
  Switch,
  Tag,
  Segmented,
  Checkbox,
  Tabs,
  Select,
  Spin,
  Tooltip,
  Space,
} from 'antd'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  CheckCircleOutlined,
  UploadOutlined,
  FileOutlined,
  DeleteOutlined,
  CalendarOutlined,
  DownOutlined,
  UpOutlined,
  BarChartOutlined,
  SettingOutlined,
  MessageOutlined,
  PictureOutlined,
  CloseCircleFilled,
  LogoutOutlined,
  UserOutlined,
  CheckSquareOutlined,
  MenuOutlined,
  DoubleLeftOutlined,
  DoubleRightOutlined,
  SendOutlined,
} from '@ant-design/icons'
import remarkGfm from 'remark-gfm'
import { usePomodoroStore, type DateRange } from '../../stores/pomodoroStore'
import { useThemeStore } from '../../stores/themeStore'
import * as pomodoroApi from '../../services/pomodoroApi'
import { sendMessageStream, type ChatMessage, type DetectedMaterial, type MemoryIndicator } from '../../services/chatApi'
import { ChatMessageBubble } from '../ChatMessageBubble'
import { ConversationSidebar } from '../ConversationSidebar'
import { useChatStore } from '../../stores/chatStore'
import { getProject, archiveUnassignedMaterials, addProjectMaterial, removeProjectMaterial, forkConversation, appendConversationMessages } from '../../services/conversationApi'
import { listWrongQuestions } from '../../services/wrongQuestionApi'
import { useAuthStore } from '../../stores/authStore'
import { listReviewTasks, getDueReviewCount, type ReviewTaskItem } from '../../services/reviewApi'
import { createNote, suggestNoteMetadata, type NoteLink } from '../../services/noteApi'
import { getDashboard, startLearningPipeline, startBatchLearningPipeline, generateDailyPlan, type DashboardData } from '../../services/learningApi'
import { getDailyIntervention } from '../../services/interventionApi'
import { draftAgentWrite, executeAgentWrite, type AgentWriteDraftResponse } from '../../services/agentApi'
import { createMemory } from '../../services/memoryApi'
import {
  getCurrentQuote,
  listQuotes,
  addCustomQuote,
  deleteQuote,
  getMotivationSettings,
  updateMotivationSettings,
  type MotivationQuote,
  type MotivationSettings,
} from '../../services/motivationApi'
import { apiFetch } from '../../services/apiClient'
import { syncEngine } from '../../sync/SyncEngine'
import { SyncStatusIndicator } from '../SyncStatusIndicator'
import { BackendLoadingOverlay } from './BackendLoadingOverlay'
import { GlobalNavRail } from './GlobalNavRail'
import type { MarkdownLiveEditorHandle } from '../MarkdownLiveEditor'
import { getOnboardingStatus, seedDemoWorkspace, type OnboardingStatus } from '../../services/systemApi'
import { AI_PROVIDERS_UPDATED_EVENT, getAllProviders, type AIProvider, type AIProvidersUpdatedDetail } from '../../services/aiSettingsApi'

const { Sider, Content } = Layout
const { TextArea } = Input

const ReactMarkdown = lazy(() => import('react-markdown'))
const SettingsModal = lazy(() => import('../SettingsModal').then(m => ({ default: m.SettingsModal })))
const StatsModal = lazy(() => import('./StatsModal').then(m => ({ default: m.StatsModal })))
const MotivationModal = lazy(() => import('./MotivationModal').then(m => ({ default: m.MotivationModal })))
const ProjectSettingsModal = lazy(() => import('../ProjectSettingsModal').then(m => ({ default: m.ProjectSettingsModal })))
const MarkdownLiveEditor = lazy(() => import('../MarkdownLiveEditor').then(m => ({ default: m.MarkdownLiveEditor })))
const OnboardingModal = lazy(() => import('../OnboardingModal').then(m => ({ default: m.OnboardingModal })))


interface PomodoroConfig {
  duration: number
  breakDuration: number
  taskName: string
  taskId: number | null
}

interface Material {
  id: number
  name: string
  uploadTime: string
  file_type?: string
  content?: string
  file_path?: string
  project_ids?: number[]
}

interface ProjectSearchResult {
  material_id: number
  title: string
  score: number
  text: string
}

interface AgentWriteTaskDraftItem {
  title?: string
  description?: string
  task_type?: string
  planned_date?: string
  duplicate?: boolean
}

type AgentWriteDraftData = Record<string, any>

interface DailyPlan {
  date: string
  content: string
}

interface WrongQuestionPreview {
  id: number
  content: string
  mastery_status: 'not_mastered' | 'partial' | 'mastered'
}

interface QuoteNoteDraft {
  sourceContent: string
  title: string
  content: string
  tags: string[]
  links: NoteLink[]
  metadataLoading: boolean
  saving: boolean
  titleEdited: boolean
  tagsEdited: boolean
}

export function ObsidianLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()
  const { bgImage, bgOpacity } = useThemeStore()
  // 使用zustand store管理番茄钟
  const {
    isRunning,
    isPaused,
    remainingTime,
    currentTask,
    duration,
    timerMode,
    breakDuration,
    startTimer,
    setBreakDuration,
    pauseTimer,
    resumeTimer,
    completeTimer,
    resetTimer,
    tick,
    getStats,
    getTaskDistribution,
    getCumulativeStats,
    backendOnline,
    syncPendingRecords,
    migrateLocalRecords,
  } = usePomodoroStore()

  const [pomodoroConfig, setPomodoroConfig] = useState<PomodoroConfig>({
    duration: 25,
    breakDuration,
    taskName: '',
    taskId: null,
  })
  const [showPomodoroModal, setShowPomodoroModal] = useState(false)
  const [showStopReasonModal, setShowStopReasonModal] = useState(false)
  const [selectedStopReason, setSelectedStopReason] = useState<'early_done' | 'interrupted' | 'distracted' | null>(null)
  const [showStatsModal, setShowStatsModal] = useState(false)
  const [focusMode] = useState<boolean>(() => {
    const saved = localStorage.getItem('layout_focus_mode')
    return saved === null ? true : saved === 'true'
  })
  const [statsRange, setStatsRange] = useState<DateRange>('week')
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const timerNotifiedRef = useRef(false)

  // 获取统计数据
  const stats = getStats()

  // 资料列表（从后端加载）
  const [materials, setMaterials] = useState<Material[]>([])
  const [materialsLoading, setMaterialsLoading] = useState(false)
  const [syncToRAG, setSyncToRAG] = useState(true)
  const [materialSearch, setMaterialSearch] = useState('')
  const [materialTypeFilter, setMaterialTypeFilter] = useState('all')
  const [showUploadArea, setShowUploadArea] = useState(false)
  const [ragStatus, setRagStatus] = useState<{
    enabled: boolean
    rag_online: boolean
    total_chunks: number
    embedding_enabled?: boolean
    fallback_active?: boolean
    last_retrieval_status?: { message?: string; mode?: string; ok?: boolean }
    message?: string
  } | null>(null)

  // 资料预览状态
  const [previewVisible, setPreviewVisible] = useState(false)
  const [currentMaterial, setCurrentMaterial] = useState<Material | null>(null)
  const [previewContent, setPreviewContent] = useState<string>('')
  const [previewLoading, setPreviewLoading] = useState(false)

  // 日历相关（计划持久化到后端）
  const [calendarExpanded, setCalendarExpanded] = useState(false)
  const [selectedDate, setSelectedDate] = useState<Dayjs | null>(null)
  const [showPlanModal, setShowPlanModal] = useState(false)
  const [dailyPlans, setDailyPlans] = useState<Record<string, string>>({})
  const [currentPlan, setCurrentPlan] = useState('')
  const [, setWeeklyPlans] = useState<DailyPlan[]>([])
  const planEditorRef = useRef<MarkdownLiveEditorHandle | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [motivationQuote, setMotivationQuote] = useState<MotivationQuote | null>(null)
  const [refreshOffset, setRefreshOffset] = useState(0)
  const [showMotivationModal, setShowMotivationModal] = useState(false)
  const [allQuotes, setAllQuotes] = useState<MotivationQuote[]>([])
  const [newQuoteContent, setNewQuoteContent] = useState('')
  const [newQuoteAuthor, setNewQuoteAuthor] = useState('')
  const [motivationSettings, setMotivationSettings] = useState<MotivationSettings>({
    display_mode: 'auto',
    selected_quote_id: null,
    sort_mode: 'created_desc',
    rotation_seconds: 3 * 60 * 60,
  })
  const [savingMotivationSettings, setSavingMotivationSettings] = useState(false)
  const [projectSearchQuery, setProjectSearchQuery] = useState('')
  const [projectSearchResults, setProjectSearchResults] = useState<ProjectSearchResult[]>([])
  const [projectSearchLoading, setProjectSearchLoading] = useState(false)

  // 提醒设置（响应式，监听 localStorage 变化）
  const [interventionEnabled, setInterventionEnabled] = useState(
    () => localStorage.getItem('intervention_enabled') !== 'false'
  )
  const [interventionIntervalMin, setInterventionIntervalMin] = useState(
    () => parseInt(localStorage.getItem('intervention_interval_min') || '30', 10)
  )

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'intervention_enabled') setInterventionEnabled(e.newValue !== 'false')
      if (e.key === 'intervention_interval_min') setInterventionIntervalMin(parseInt(e.newValue || '30', 10))
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])
  const DEFAULT_CARD_ORDER = ['current', 'review', 'progress', 'pomodoro', 'calendar', 'motivation']
  const ALL_CARDS = [
    { id: 'motivation', label: '每日格言' },
    { id: 'calendar', label: '今天与计划' },
    { id: 'current', label: '近期任务' },
    { id: 'review', label: '复习与错题' },
    { id: 'progress', label: '学习数据' },
    { id: 'pomodoro', label: '番茄工作法' }
  ]
  const CARD_ID_SET = new Set(ALL_CARDS.map(card => card.id))
  const normalizeCardOrder = (ids: string[]) => {
    const knownIds = ids.filter((id, index) => CARD_ID_SET.has(id) && ids.indexOf(id) === index)
    const missingIds = DEFAULT_CARD_ORDER.filter(id => !knownIds.includes(id))
    return [...knownIds, ...missingIds]
  }
  const normalizeVisibleCards = (ids: string[]) => ids.filter((id, index) => CARD_ID_SET.has(id) && ids.indexOf(id) === index)
  const [cardOrder, setCardOrder] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem('right_card_order')
      if (saved) {
        const parsed = JSON.parse(saved) as string[]
        if (parsed.join(',') !== 'motivation,calendar,current,review,progress,pomodoro') return normalizeCardOrder(parsed)
      }
    } catch { /* ignore */ }
    return DEFAULT_CARD_ORDER
  })
  const [visibleCards, setVisibleCards] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem('right_visible_cards')
      if (saved) return normalizeVisibleCards(JSON.parse(saved) as string[])
    } catch { /* ignore */ }
    return DEFAULT_CARD_ORDER
  })
  const [sortMode, setSortMode] = useState(false)
  const [customizeOpen, setCustomizeOpen] = useState(false)
  const dragCardRef = useRef<string | null>(null)
  const updateCardVisibility = (cardId: string, checked: boolean) => {
    setVisibleCards(prev => {
      const next = checked
        ? normalizeVisibleCards([...prev, cardId])
        : prev.filter(id => id !== cardId)
      localStorage.setItem('right_visible_cards', JSON.stringify(next))
      return next
    })
  }

  // Chat store
  const {
    projects,
    messages: chatMessages,
    streamingContent,
    isStreaming: chatLoading,
    activeConversationId,
    activeProjectId,
    addMessage,
    setMessages,
    setStreamingContent,
    setIsStreaming: setChatLoading,
    loadProjects,
    loadConversations,
    reloadConversationsForCurrentView,
    createNewConversation,
    reconcilePersistedSelections,
    restoreActiveConversation,
    setActiveConversation,
  } = useChatStore()

  const [chatInput, setChatInput] = useState('')
  const [selectedMaterialIds, setSelectedMaterialIds] = useState<Set<number>>(new Set())
  const [detectedMaterials, setDetectedMaterials] = useState<DetectedMaterial[]>([])
  const [autoScrollEnabled, setAutoScrollEnabled] = useState(true)
  const [agentWriteDraft, setAgentWriteDraft] = useState<AgentWriteDraftResponse | null>(null)
  const [agentWriteSourceText, setAgentWriteSourceText] = useState('')
  const [agentWriteLoading, setAgentWriteLoading] = useState(false)
  const [agentWriteExecuting, setAgentWriteExecuting] = useState(false)
  const [chatProviders, setChatProviders] = useState<AIProvider[]>([])
  const [selectedChatModel, setSelectedChatModel] = useState<string>(() => localStorage.getItem('chat_model_override') || '__route__')
  const [quoteNoteDraft, setQuoteNoteDraft] = useState<QuoteNoteDraft | null>(null)
  const chatScrollRef = useRef<HTMLDivElement>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const initialConversationRestoreRef = useRef(false)

  // Image upload state
  const [pendingImages, setPendingImages] = useState<string[]>([])
  const imageInputRef = useRef<HTMLInputElement>(null)

  // Project settings modal
  const [projectSettingsOpen, setProjectSettingsOpen] = useState(false)
  const [editingProjectId, setEditingProjectId] = useState<number | undefined>()
  const [leftSidebarTab, setLeftSidebarTab] = useState<string>('conversations')
  const [leftCollapsed, setLeftCollapsed] = useState(() => localStorage.getItem('layout_left_collapsed') === 'true')
  const [leftExpandTarget, setLeftExpandTarget] = useState<'default' | 'search' | 'categories' | 'history' | null>(null)
  const [projectMaterialsOpen, setProjectMaterialsOpen] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(() => localStorage.getItem('layout_right_collapsed') === 'true')

  // Draggable panel splitter state
  const [leftWidth, setLeftWidth] = useState<number>(() => {
    const saved = localStorage.getItem('layout_left_width')
    return saved ? Number(saved) : 280
  })
  const [rightWidth, setRightWidth] = useState<number>(() => {
    const saved = localStorage.getItem('layout_right_width')
    return saved ? Number(saved) : 320
  })
  const [dragging, setDragging] = useState<'left' | 'right' | null>(null)
  const effectiveLeftWidth = leftCollapsed ? 72 : leftWidth
  const effectiveRightWidth = rightCollapsed ? 0 : rightWidth
  const [activeProjectMaterialIds, setActiveProjectMaterialIds] = useState<number[]>([])
  const [, setWrongQuestions] = useState<WrongQuestionPreview[]>([])
  const [reviewDueCount, setReviewDueCount] = useState(0)
  const [reviewPreviewTasks, setReviewPreviewTasks] = useState<ReviewTaskItem[]>([])
  const [dashboardData, setDashboardData] = useState<DashboardData | null>(null)
  // Backend readiness polling (Feature 1)
  const [backendReady, setBackendReady] = useState(false)

  // First-run onboarding and demo workspace
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [onboardingStatus, setOnboardingStatus] = useState<OnboardingStatus | null>(null)
  const [demoSeedLoading, setDemoSeedLoading] = useState(false)
  const [beginnerMode, setBeginnerMode] = useState(() => localStorage.getItem('learner_view_mode') !== 'advanced')

  // Coach mode (Feature 5)
  const [chatMode] = useState<'normal' | 'coach'>('normal')

  // Memory indicators (Feature 2)
  const [, setMemoryIndicators] = useState<MemoryIndicator[]>([])

  // Start learning loading state (Feature 1)
  const [startLearningLoadingId, setStartLearningLoadingId] = useState<number | null>(null)
  const [hoveredMaterialId, setHoveredMaterialId] = useState<number | null>(null)
  // Batch learning state
  const [batchLearningLoading, setBatchLearningLoading] = useState(false)
  const [archiveMaterialsLoading, setArchiveMaterialsLoading] = useState(false)
  const [projectMaterialsOnly, setProjectMaterialsOnly] = useState(() => {
    try {
      const raw = localStorage.getItem('materials_project_only')
      return raw === null ? true : raw === 'true'
    } catch {
      return true
    }
  })

  // 加载资料列表
  const loadMaterials = useCallback(async () => {
    setMaterialsLoading(true)
    try {
      const arr = await apiFetch<any[]>('/api/materials/?skip=0&limit=100')
      const mapped: Material[] = (arr || []).map((m: any) => ({
        id: m.id,
        name: m.title,
        uploadTime: (m.created_at || '').slice(0, 10) || dayjs().format('YYYY-MM-DD'),
        file_type: m.file_type,
        file_path: m.file_path,
        project_ids: m.project_ids || [],
      }))
      setMaterials(mapped.reverse())
    } catch {
      // backend may not be ready yet
    } finally {
      setMaterialsLoading(false)
    }
  }, [])

  const loadCurrentQuote = useCallback(async (offset?: number) => {
    const res = await getCurrentQuote(offset ?? refreshOffset)
    setMotivationQuote(res)
  }, [refreshOffset])

  const loadAllQuotes = useCallback(async (sortMode?: string) => {
    const list = await listQuotes(undefined, sortMode ?? motivationSettings.sort_mode)
    setAllQuotes(list)
  }, [motivationSettings.sort_mode])

  const loadMotivationSettings = useCallback(async () => {
    const data = await getMotivationSettings()
    setMotivationSettings(data)
    return data
  }, [])

  const handleProjectSearch = useCallback(async (value?: string) => {
    if (!activeProjectId) {
      message.warning('请先选择一个项目')
      return
    }
    const q = (value ?? projectSearchQuery).trim()
    if (!q) {
      setProjectSearchResults([])
      return
    }
    setProjectSearchLoading(true)
    try {
      const data = await apiFetch<any[]>(`/api/materials/search?query=${encodeURIComponent(q)}&project_id=${activeProjectId}`)
      setProjectSearchResults(data || [])
    } catch (e: any) {
      message.error(e?.message || '搜索失败')
    } finally {
      setProjectSearchLoading(false)
    }
  }, [activeProjectId, projectSearchQuery])

  const handleRefreshQuote = () => {
    setRefreshOffset((prev) => {
      const next = prev + 1
      void loadCurrentQuote(next)
      return next
    })
  }

  const handleAddCustomQuote = async () => {
    const content = newQuoteContent.trim()
    if (!content) {
      message.warning('请输入语录内容')
      return
    }
    const created = await addCustomQuote(content, newQuoteAuthor.trim() || undefined)
    if (!created) {
      message.error('添加失败')
      return
    }
    setNewQuoteContent('')
    setNewQuoteAuthor('')
    await loadAllQuotes()
    message.success('已添加语录')
  }

  const handleDeleteQuote = async (quoteId: number) => {
    const res = await deleteQuote(quoteId)
    if (!res.ok) {
      message.error(res.detail || '删除失败')
      return
    }
    if (motivationSettings.selected_quote_id === quoteId) {
      setMotivationSettings((prev) => ({ ...prev, display_mode: 'auto', selected_quote_id: null }))
    }
    await loadMotivationSettings()
    await loadAllQuotes()
    await loadCurrentQuote()
    message.success('已删除')
  }

  const handleSaveMotivationSettings = async () => {
    if (motivationSettings.display_mode === 'manual' && motivationSettings.selected_quote_id === null) {
      message.warning('固定展示模式请先选择一条语录')
      return
    }

    setSavingMotivationSettings(true)
    try {
      const payload: {
        display_mode: 'auto' | 'manual'
        sort_mode: string
        rotation_seconds: number
        selected_quote_id?: number
      } = {
        display_mode: motivationSettings.display_mode,
        sort_mode: motivationSettings.sort_mode,
        rotation_seconds: motivationSettings.rotation_seconds,
      }

      if (motivationSettings.selected_quote_id !== null) {
        payload.selected_quote_id = motivationSettings.selected_quote_id
      }

      const updated = await updateMotivationSettings(payload)
      setMotivationSettings(updated)
      await loadAllQuotes(updated.sort_mode)
      await loadCurrentQuote()
      message.success('激励语录设置已保存')
    } catch (e: any) {
      message.error(e?.message || '保存失败')
    } finally {
      setSavingMotivationSettings(false)
    }
  }

  const handlePinCurrentQuote = async (quoteId: number) => {
    setSavingMotivationSettings(true)
    try {
      const updated = await updateMotivationSettings({
        display_mode: 'manual',
        selected_quote_id: quoteId,
      })
      setMotivationSettings(updated)
      await loadCurrentQuote()
      message.success('已设为当前展示语录')
    } catch (e: any) {
      message.error(e?.message || '设置失败')
    } finally {
      setSavingMotivationSettings(false)
    }
  }

  const visibleMaterials = useMemo(() => {
    if (!activeProjectId || !projectMaterialsOnly) return materials
    if (activeProjectMaterialIds.length === 0) return []
    const idSet = new Set(activeProjectMaterialIds)
    return materials.filter((m) => idSet.has(m.id))
  }, [materials, activeProjectId, activeProjectMaterialIds, projectMaterialsOnly])

  const materialTypeOptions = useMemo(() => {
    const types = Array.from(new Set(visibleMaterials.map((m) => m.file_type).filter(Boolean))) as string[]
    return [
      { label: '全部类型', value: 'all' },
      ...types.map((t) => ({ label: t.toUpperCase(), value: t })),
    ]
  }, [visibleMaterials])

  const filteredMaterials = useMemo(() => {
    let list = visibleMaterials
    const searchText = materialSearch.trim().toLowerCase()
    if (materialTypeFilter !== 'all') {
      list = list.filter((m) => m.file_type === materialTypeFilter)
    }
    if (searchText) {
      list = list.filter((m) => (m.name || '').toLowerCase().includes(searchText))
    }
    return list
  }, [visibleMaterials, materialSearch, materialTypeFilter])

  const projectMaterials = useMemo(() => {
    if (!activeProjectId) return []
    const idSet = new Set(activeProjectMaterialIds)
    return materials.filter((m) => idSet.has(m.id))
  }, [materials, activeProjectId, activeProjectMaterialIds])

  const resolveMaterialById = useCallback((id: number) => {
    return projectMaterials.find((m) => m.id === id) || materials.find((m) => m.id === id)
  }, [projectMaterials, materials])

  const projectNameMap = useMemo(() => {
    const map = new Map<number, string>()
    for (const p of projects) {
      map.set(p.id, p.name)
    }
    return map
  }, [projects])

  const chatModelOptions = useMemo(() => {
    const groups = chatProviders
      .filter((provider) => provider.enabled)
      .map((provider) => {
        const models = Array.from(new Set([provider.model, ...(provider.available_models || [])].filter(Boolean)))
        return {
          label: provider.display_name,
          options: models.map((model) => ({
            label: model,
            value: `${provider.provider_name}::${model}`,
          })),
        }
      })
      .filter((group) => group.options.length > 0)

    return [
      { label: '跟随路由', value: '__route__' },
      ...groups,
    ]
  }, [chatProviders])

  const chatModelValues = useMemo(() => {
    const values = new Set<string>(['__route__'])
    for (const provider of chatProviders) {
      if (!provider.enabled) continue
      const models = Array.from(new Set([provider.model, ...(provider.available_models || [])].filter(Boolean)))
      for (const model of models) {
        values.add(`${provider.provider_name}::${model}`)
      }
    }
    return values
  }, [chatProviders])

  const selectedChatModelConfig = useMemo(() => {
    if (!selectedChatModel || selectedChatModel === '__route__') return {}
    const [providerName, ...modelParts] = selectedChatModel.split('::')
    const model = modelParts.join('::')
    if (!providerName || !model) return {}
    return { providerName, model }
  }, [selectedChatModel])

  useEffect(() => {
    if (leftCollapsed && leftSidebarTab !== 'conversations') {
      setLeftSidebarTab('conversations')
    }
  }, [leftCollapsed, leftSidebarTab])

  useEffect(() => {
    try {
      localStorage.setItem('layout_left_collapsed', String(leftCollapsed))
    } catch {
      // ignore
    }
  }, [leftCollapsed])

  useEffect(() => {
    try {
      localStorage.setItem('layout_right_collapsed', String(rightCollapsed))
    } catch {
      // ignore
    }
  }, [rightCollapsed])

  useEffect(() => {
    try {
      localStorage.setItem('materials_project_only', String(projectMaterialsOnly))
    } catch {
      // ignore
    }
  }, [projectMaterialsOnly])

  // Backend health polling - wait until backend is ready before loading data
  useEffect(() => {
    if (backendReady) return
    let cancelled = false
    const poll = async () => {
      while (!cancelled) {
        try {
          const res = await fetch('/health')
          if (res.ok) {
            if (!cancelled) setBackendReady(true)
            return
          }
        } catch {
          // backend not ready yet
        }
        await new Promise((r) => setTimeout(r, 2000))
      }
    }
    poll()
    return () => { cancelled = true }
  }, [backendReady])

  // Once backend is ready, load only first-screen essentials immediately.
  // Secondary dashboard/agent signals are deferred so the chat shell becomes usable first.
  useEffect(() => {
    if (!backendReady) return
    const loadAll = async () => {
      const shouldRestoreConversation = !initialConversationRestoreRef.current && !!activeConversationId
      initialConversationRestoreRef.current = true
      void Promise.allSettled([
        loadMaterials(),
        shouldRestoreConversation ? restoreActiveConversation() : reconcilePersistedSelections(),
      ])

      window.setTimeout(() => {
        void apiFetch<{
          enabled: boolean
          rag_online: boolean
          total_chunks: number
          embedding_enabled?: boolean
          fallback_active?: boolean
          last_retrieval_status?: { message?: string; mode?: string; ok?: boolean }
          message: string
        }>('/api/rag/health').then(setRagStatus).catch(() => undefined)
        void loadWeeklyPlans()
        void loadWrongQuestions()
        void loadReviewOverview()
        void loadDashboardOverview()
      }, 400)

      window.setTimeout(() => {
        void loadDailyIntervention()
        void syncPendingRecords()
      }, 1600)
    }
    void loadAll()
  }, [backendReady, loadMaterials, reconcilePersistedSelections, restoreActiveConversation, syncPendingRecords])

  useEffect(() => {
    if (!backendReady) return
    let cancelled = false
    const loadChatProviders = async (detail?: AIProvidersUpdatedDetail) => {
      const data = await getAllProviders()
      if (cancelled || !data) return
      const nextData = data.map((provider) => {
        if (provider.provider_name !== detail?.providerName) return provider
        const models = Array.from(new Set([
          provider.model,
          ...(provider.available_models || []),
          ...(detail.availableModels || []),
          detail.model,
        ].filter(Boolean) as string[]))
        return {
          ...provider,
          model: detail.model || provider.model,
          available_models: models,
        }
      })
      setChatProviders(nextData)
      if (detail?.resetChatModel) {
        setSelectedChatModel('__route__')
        return
      }
      if (detail?.selectModel && detail.providerName) {
        const provider = nextData.find((item) => item.provider_name === detail.providerName)
        if (!provider?.enabled) return
        const models = Array.from(new Set([
          provider.model,
          ...(provider.available_models || []),
          ...(detail.availableModels || []),
          detail.model,
        ].filter(Boolean) as string[]))
        const model = detail.model && models.includes(detail.model)
          ? detail.model
          : provider.model || models[0]
        if (model) {
          setSelectedChatModel(`${provider.provider_name}::${model}`)
        }
      }
    }
    const handleProvidersUpdated = (event: Event) => {
      const detail = event instanceof CustomEvent
        ? event.detail as AIProvidersUpdatedDetail
        : undefined
      void loadChatProviders(detail)
    }
    void loadChatProviders()
    window.addEventListener(AI_PROVIDERS_UPDATED_EVENT, handleProvidersUpdated)
    return () => {
      cancelled = true
      window.removeEventListener(AI_PROVIDERS_UPDATED_EVENT, handleProvidersUpdated)
    }
  }, [backendReady])

  useEffect(() => {
    localStorage.setItem('chat_model_override', selectedChatModel)
  }, [selectedChatModel])

  useEffect(() => {
    if (chatProviders.length === 0) return
    if (!chatModelValues.has(selectedChatModel)) {
      setSelectedChatModel('__route__')
    }
  }, [chatModelValues, chatProviders.length, selectedChatModel])

  useEffect(() => {
    if (!backendReady || !user?.id) return
    let cancelled = false
    const loadStatus = async () => {
      const status = await getOnboardingStatus()
      if (cancelled || !status) return
      setOnboardingStatus(status)
      const dismissedKey = `mnemox_onboarding_dismissed_${user.id}`
      const dismissed = localStorage.getItem(dismissedKey) === 'true'
      if (!dismissed && status.stage !== 'loop_ready') {
        setShowOnboarding(true)
      }
    }
    void loadStatus()
    return () => { cancelled = true }
  }, [backendReady, user?.id])

  useEffect(() => {
    localStorage.setItem('learner_view_mode', beginnerMode ? 'beginner' : 'advanced')
  }, [beginnerMode])

  const closeOnboarding = () => {
    if (user?.id) {
      localStorage.setItem(`mnemox_onboarding_dismissed_${user.id}`, 'true')
    }
    setShowOnboarding(false)
  }

  const handleSeedDemo = async () => {
    setDemoSeedLoading(true)
    try {
      const result = await seedDemoWorkspace()
      if (!result?.ok) {
        message.error('Demo 数据导入失败，请稍后重试')
        return
      }
      message.success(result.already_seeded ? 'Demo 数据已存在' : result.message)
      const status = await getOnboardingStatus()
      if (status) setOnboardingStatus(status)
      await loadMaterials()
      await loadProjects()
      await loadConversations()
      await loadWeeklyPlans()
      await loadWrongQuestions()
      await loadReviewOverview()
      await loadDashboardOverview()
      await loadDailyIntervention()
      setLeftCollapsed(false)
      setLeftSidebarTab('materials')
      closeOnboarding()
      navigate('/dashboard')
    } finally {
      setDemoSeedLoading(false)
    }
  }

  const openOnboardingMaterials = () => {
    setLeftCollapsed(false)
    setLeftSidebarTab('materials')
    setShowOnboarding(false)
  }

  useEffect(() => {
    if (!backendReady) return
    void loadCurrentQuote()
    void loadMotivationSettings()
    const interval = setInterval(() => {
      void loadCurrentQuote()
    }, 5 * 60 * 1000)
    return () => clearInterval(interval)
  }, [backendReady, loadCurrentQuote, loadMotivationSettings])

  useEffect(() => {
    if (!projectMaterialsOpen) {
      setProjectSearchQuery('')
      setProjectSearchResults([])
    }
  }, [projectMaterialsOpen])

  useEffect(() => {
    setProjectSearchQuery('')
    setProjectSearchResults([])
  }, [activeProjectId])

  useEffect(() => {
    if (!activeProjectId || !projects.some((project) => project.id === activeProjectId)) {
      setActiveProjectMaterialIds([])
      return
    }
    ; (async () => {
      const detail = await getProject(activeProjectId)
      setActiveProjectMaterialIds(detail?.material_ids || [])
    })()
  }, [activeProjectId, projectSettingsOpen, projects])

  useEffect(() => {
    setSelectedMaterialIds((prev) => {
      if (!activeProjectId) return prev
      const visibleIds = new Set(visibleMaterials.map((m) => m.id))
      const next = new Set<number>()
      for (const id of prev) {
        if (visibleIds.has(id)) next.add(id)
      }
      return next
    })
  }, [activeProjectId, visibleMaterials])

  // 自动滚动到底部
  useEffect(() => {
    if (!autoScrollEnabled) return
    const el = chatScrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [chatMessages, streamingContent, autoScrollEnabled])

  // 发送消息
  const getLastUserMessage = () => {
    for (let i = chatMessages.length - 1; i >= 0; i -= 1) {
      if (chatMessages[i].role === 'user') return chatMessages[i].content
    }
    return ''
  }

  const shouldCheckAgentWrite = (text: string) => {
    const triggers = [
      '记个笔记', '记一条笔记', '记一个笔记', '记个灵感', '记一个灵感', '记录一下', '写入笔记', '存到笔记', '保存到笔记', '记到笔记', '记进笔记', '突然有个想法', '临时有个想法', '有个想法', '有一个想法', '我想到',
      '今天的任务', '今天任务', '今日任务', '今天的计划', '今天计划', '今日计划', '今天待办', '今日待办', '加入今天计划', '加到今天计划', '写到今天计划', '安排到今天',
      '创建任务', '添加任务', '加入任务', '安排任务', '制定任务', '拆成任务', '拆成子任务', '拆解任务', '生成任务', '做成任务', '目标是', '我的目标', '接下来我要', '接下来我的目标',
    ]
    return triggers.some(trigger => text.includes(trigger))
  }

  const updateAgentWriteDraft = (patch: AgentWriteDraftData) => {
    setAgentWriteDraft(prev => prev ? { ...prev, draft: { ...prev.draft, ...patch } } : prev)
  }

  const updateAgentWriteListItem = (field: 'items' | 'tasks', index: number, patch: AgentWriteTaskDraftItem) => {
    setAgentWriteDraft(prev => {
      if (!prev) return prev
      const list = Array.isArray(prev.draft[field]) ? [...prev.draft[field]] : []
      list[index] = { ...(list[index] || {}), ...patch, duplicate: false }
      return { ...prev, draft: { ...prev.draft, [field]: list } }
    })
  }

  const removeAgentWriteListItem = (field: 'items' | 'tasks', index: number) => {
    setAgentWriteDraft(prev => {
      if (!prev) return prev
      const list = Array.isArray(prev.draft[field]) ? [...prev.draft[field]] : []
      list.splice(index, 1)
      return { ...prev, draft: { ...prev.draft, [field]: list } }
    })
  }

  const confirmAgentWrite = async () => {
    if (!agentWriteDraft || agentWriteDraft.intent === 'none') return
    if (!['create_note', 'create_goal_tasks', 'add_daily_plan_items'].includes(agentWriteDraft.intent)) return
    if (agentWriteDraft.intent === 'create_note' && !String(agentWriteDraft.draft.content || '').trim()) {
      message.warning('笔记内容不能为空')
      return
    }
    if (agentWriteDraft.intent === 'add_daily_plan_items' && !((agentWriteDraft.draft.items || []) as AgentWriteTaskDraftItem[]).some(item => String(item.title || '').trim())) {
      message.warning('至少保留一个计划项')
      return
    }
    if (agentWriteDraft.intent === 'create_goal_tasks' && !((agentWriteDraft.draft.tasks || []) as AgentWriteTaskDraftItem[]).some(item => String(item.title || '').trim())) {
      message.warning('至少保留一个任务')
      return
    }
    setAgentWriteExecuting(true)
    let result
    try {
      result = await executeAgentWrite(agentWriteDraft.intent, agentWriteDraft.draft)
    } catch (error: any) {
      setAgentWriteExecuting(false)
      message.error(error?.message || 'Agent 写入失败，请检查草案内容后重试')
      return
    }
    setAgentWriteExecuting(false)
    message.success(result.message || 'Agent 已写入系统')
    const userEntry: ChatMessage = { role: 'user', content: agentWriteSourceText }
    const assistantEntry: ChatMessage = {
      role: 'assistant',
      content: result.message || (agentWriteDraft.intent === 'create_note' ? '已创建笔记。' : '已创建任务。'),
    }
    let conversationId = activeConversationId
    if (!conversationId) {
      const conv = await createNewConversation(activeProjectId)
      conversationId = conv.id
    }
    addMessage(userEntry)
    addMessage(assistantEntry)

    if (conversationId) {
      await appendConversationMessages(conversationId, [userEntry, assistantEntry])
      await setActiveConversation(conversationId)
      await loadConversations(activeProjectId ?? undefined)
    }
    setAgentWriteDraft(null)
    setAgentWriteSourceText('')
    await syncEngine.syncAll()
    void loadDashboardOverview()
  }

  const handleSendMessage = async (
    forcedText?: string,
    options?: {
      conversationId?: number
      history?: ChatMessage[]
      replaceMessages?: ChatMessage[]
    },
  ) => {
    const text = (forcedText ?? chatInput).trim()
    if (!text || chatLoading || agentWriteLoading) return

    if (!forcedText && !options && pendingImages.length === 0 && shouldCheckAgentWrite(text)) {
      setAgentWriteLoading(true)
      try {
        const draft = await draftAgentWrite(text)
        setAgentWriteLoading(false)
        if (draft.requires_confirmation && draft.intent !== 'none') {
          setAgentWriteDraft(draft)
          setAgentWriteSourceText(text)
          setChatInput('')
          return
        }
      } catch (error: any) {
        setAgentWriteLoading(false)
        message.error(error?.message || 'Agent 草稿生成失败')
      }
    }

    // Auto-create conversation if none active
    let convId = options?.conversationId ?? activeConversationId
    if (!convId) {
      const conv = await createNewConversation(activeProjectId)
      if (!conv) {
        message.error('创建对话失败')
        return
      }
      convId = conv.id
    }

    const userMsg: ChatMessage = { role: 'user', content: text }
    const historyForRequest = options?.history ?? chatMessages
    if (options?.replaceMessages) {
      setMessages([...options.replaceMessages, userMsg])
    } else {
      addMessage(userMsg)
    }
    if (!forcedText) setChatInput('')
    setPendingImages([])
    setAutoScrollEnabled(true)
    setChatLoading(true)
    setStreamingContent('')
    setDetectedMaterials([])
    let accumulated = ''
    const controller = new AbortController()
    abortControllerRef.current = controller

    await sendMessageStream(
      text,
      historyForRequest,
      (chunk) => {
        accumulated += chunk
        setStreamingContent(accumulated)
      },
      () => {
        if (accumulated) {
          addMessage({ role: 'assistant', content: accumulated })
        }
        setStreamingContent('')
        setChatLoading(false)
        abortControllerRef.current = null
        // Refresh conversation list to update title/timestamp
        reloadConversationsForCurrentView()
        // Refresh review count after chat (may have auto-created wrong questions)
        loadReviewOverview()
      },
      (error) => {
        message.error(error)
        setChatLoading(false)
        setStreamingContent('')
        abortControllerRef.current = null
      },
      Array.from(selectedMaterialIds),
      (detected) => {
        setDetectedMaterials(detected)
        if (detected.length > 0) {
          message.info(`AI 自动识别到资料：${detected.map((d) => d.title).join('、')}`)
        }
      },
      controller.signal,
      convId,
      !forcedText && pendingImages.length > 0 ? pendingImages : undefined,
      (() => {
        try {
          const raw = localStorage.getItem('study_active_session_id')
          return raw ? Number(raw) : undefined
        } catch {
          return undefined
        }
      })(),
      chatMode,
      (memories) => {
        setMemoryIndicators(memories)
      },
      (feedback) => {
        notification.open({
          key: 'progress-feedback',
          message: '进度提醒',
          description: feedback.message,
          icon: <span style={{ fontSize: 18 }}>{feedback.emoji}</span>,
          placement: 'bottomRight',
          duration: 8,
          actions: (
            <Button
              size="small"
              type="primary"
              onClick={() => {
                notification.destroy('progress-feedback')
                navigate('/progress')
              }}
            >
              查看详情
            </Button>
          ),
        })
      },
      selectedChatModelConfig.providerName,
      selectedChatModelConfig.model,
    )
  }

  // 停止生成
  const handleStopStreaming = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
  }, [])

  const forkAtMessage = async (messageIndex: number, title?: string) => {
    if (!activeConversationId) {
      message.warning('当前对话尚未保存，先发送一轮消息后再创建分支')
      return null
    }
    const fork = await forkConversation(activeConversationId, {
      title,
      up_to_index: messageIndex,
    })
    await setActiveConversation(fork.id)
    await loadConversations()
    return fork
  }

  const handleBranchFromAssistant = async (messageIndex: number) => {
    const prefix = chatMessages.slice(0, messageIndex + 1)
    const fork = await forkAtMessage(messageIndex, '对话分支')
    if (!fork) return
    setMessages(prefix)
    message.success('已创建对话分支')
  }

  const handleRegenerateAssistant = async (assistantIndex: number) => {
    if (chatLoading) return
    let userIndex = -1
    for (let i = assistantIndex - 1; i >= 0; i -= 1) {
      if (chatMessages[i].role === 'user') {
        userIndex = i
        break
      }
    }
    if (userIndex < 0) {
      message.warning('未找到对应的用户消息')
      return
    }
    const prefix = chatMessages.slice(0, userIndex)
    const fork = await forkAtMessage(userIndex - 1, '重新生成分支')
    if (!fork) return
    await handleSendMessage(chatMessages[userIndex].content, {
      conversationId: fork.id,
      history: prefix,
      replaceMessages: prefix,
    })
  }

  const handleEditUserMessage = async (messageIndex: number, nextContent: string) => {
    if (chatLoading) return
    const prefix = chatMessages.slice(0, messageIndex)
    const fork = await forkAtMessage(messageIndex - 1, '编辑消息分支')
    if (!fork) return
    await handleSendMessage(nextContent, {
      conversationId: fork.id,
      history: prefix,
      replaceMessages: prefix,
    })
  }

  const handleImageSelect = (file: File) => {
    if (!file.type.startsWith('image/')) return
    if (file.size > 5 * 1024 * 1024) {
      message.warning('图片不能超过 5MB')
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      const base64 = (reader.result as string).split(',')[1]
      setPendingImages(prev => [...prev, base64])
    }
    reader.readAsDataURL(file)
  }

  // Drag handler for panel splitters
  const leftWidthRef = useRef(leftWidth)
  leftWidthRef.current = leftWidth
  const rightWidthRef = useRef(rightWidth)
  rightWidthRef.current = rightWidth

  useEffect(() => {
    if (!dragging) return
    const onMouseMove = (e: MouseEvent) => {
      if (dragging === 'left') {
        const newWidth = Math.min(480, Math.max(180, e.clientX - 64))
        setLeftWidth(newWidth)
      } else {
        const newWidth = Math.min(480, Math.max(200, window.innerWidth - e.clientX))
        setRightWidth(newWidth)
      }
    }
    const onMouseUp = () => {
      if (dragging === 'left') {
        localStorage.setItem('layout_left_width', String(leftWidthRef.current))
      } else {
        localStorage.setItem('layout_right_width', String(rightWidthRef.current))
      }
      setDragging(null)
    }
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    return () => {
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [dragging])

  const loadWrongQuestions = async () => {
    try {
      const list = await listWrongQuestions()
      setWrongQuestions((list || []).slice(0, 6))
    } catch {
      setWrongQuestions([])
    }
  }

  const loadReviewOverview = async () => {
    try {
      const [due, count] = await Promise.all([
        listReviewTasks('due', 'all'),
        getDueReviewCount(),
      ])
      setReviewDueCount(count)
      setReviewPreviewTasks(due.slice(0, 3))
    } catch (error: any) {
      message.error(error?.message || '加载复习任务失败')
      setReviewDueCount(0)
      setReviewPreviewTasks([])
    }
  }

  const loadDashboardOverview = async () => {
    try {
      const d = await getDashboard()
      setDashboardData(d)
    } catch {
      setDashboardData(null)
    }
  }

  const loadDailyIntervention = async () => {
    try {
      const report = await getDailyIntervention()
      if (!report || !report.should_push) return

      // 每2小时最多提醒一次（key 包含时间段）
      const slot = Math.floor(new Date().getHours() / 2)
      const key = `intervention_notified_${report.date}_slot${slot}`
      if (localStorage.getItem(key)) return
      localStorage.setItem(key, '1')

      const notifyFn = report.risk_level === 'high' ? notification.warning : notification.info
      notifyFn({
        message: report.push_title,
        description: (
          <div>
            <div style={{ marginBottom: 8 }}>{report.push_body}</div>
            {report.suggestions.slice(0, 2).map((s, i) => (
              <div key={i} style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>• {s}</div>
            ))}
          </div>
        ),
        placement: 'bottomRight',
        duration: report.risk_level === 'high' ? 0 : 6,
        actions: (
          <Button size="small" type="primary" onClick={() => navigate('/eda?tab=intervention')}>
            查看详情
          </Button>
        ),
      })
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    let lastFocusRefreshAt = 0
    const onFocus = () => {
      if (!backendReady) return
      const now = Date.now()
      if (now - lastFocusRefreshAt < 30_000) return
      lastFocusRefreshAt = now

      // Focus refresh stays light; heavier overviews are background work.
      void loadMaterials()
      void loadProjects()
      void loadConversations()
      window.setTimeout(() => {
        void loadWrongQuestions()
        void loadReviewOverview()
        void loadDashboardOverview()
        void loadDailyIntervention()
      }, 600)
    }
    window.addEventListener('focus', onFocus)

    // 定时主动检查学习状态（响应式，依赖用户设置）
    const interventionTimer = interventionEnabled
      ? setInterval(() => { if (backendReady) void loadDailyIntervention() }, interventionIntervalMin * 60 * 1000)
      : null

    return () => {
      window.removeEventListener('focus', onFocus)
      if (interventionTimer) clearInterval(interventionTimer)
    }
  }, [loadMaterials, loadProjects, loadConversations, backendReady, interventionEnabled, interventionIntervalMin])

  const handleChatScroll = () => {
    const el = chatScrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    setAutoScrollEnabled(nearBottom)
  }

  const quoteAssistantToNote = (assistantContent: string) => {
    const lastUserText = (() => {
      for (let i = chatMessages.length - 1; i >= 0; i -= 1) {
        if (chatMessages[i].role === 'user') return chatMessages[i].content
      }
      return ''
    })()

    const body = `## AI 回答摘录\n\n${assistantContent}\n`
    const fallbackTitle = `对话摘录 ${dayjs().format('MM-DD HH:mm')}`
    const links: NoteLink[] = []
    const activeTaskId = (() => {
      try {
        const raw = localStorage.getItem('study_active_task_id')
        return raw ? Number(raw) : undefined
      } catch {
        return undefined
      }
    })()
    if (activeTaskId) {
      links.push({ link_type: 'task', link_id: activeTaskId })
    }

    setQuoteNoteDraft({
      sourceContent: assistantContent,
      title: fallbackTitle,
      content: body,
      tags: [],
      links,
      metadataLoading: true,
      saving: false,
      titleEdited: false,
      tagsEdited: false,
    })

    void suggestNoteMetadata(assistantContent, lastUserText)
      .then((suggested) => {
        setQuoteNoteDraft((prev) => {
          if (!prev || prev.sourceContent !== assistantContent) return prev
          return {
            ...prev,
            title: !prev.titleEdited && suggested?.title ? suggested.title : prev.title,
            tags: !prev.tagsEdited && suggested?.tags ? suggested.tags.slice(0, 5) : prev.tags,
            metadataLoading: false,
          }
        })
      })
      .catch(() => {
        setQuoteNoteDraft((prev) => (
          prev && prev.sourceContent === assistantContent
            ? { ...prev, metadataLoading: false }
            : prev
        ))
      })
  }

  const saveQuoteNoteDraft = async () => {
    if (!quoteNoteDraft || quoteNoteDraft.saving) return

    const title = quoteNoteDraft.title.trim()
    const content = quoteNoteDraft.content.trim()
    if (!title) {
      message.error('请输入笔记标题')
      return
    }
    if (!content) {
      message.error('笔记内容不能为空')
      return
    }

    setQuoteNoteDraft((prev) => prev ? { ...prev, saving: true } : prev)
    const created = await createNote({
      title,
      content,
      note_type: 'summary',
      tags: quoteNoteDraft.tags.map((tag) => tag.trim()).filter(Boolean).slice(0, 8),
      links: quoteNoteDraft.links,
    })
    if (created) {
      message.success('已引用到笔记')
      setQuoteNoteDraft(null)
    } else {
      message.error('创建笔记失败')
      setQuoteNoteDraft((prev) => prev ? { ...prev, saving: false } : prev)
    }
  }

  // 番茄钟倒计时
  useEffect(() => {
    // Clear any existing interval first
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }

    if (isRunning && remainingTime > 0) {
      timerNotifiedRef.current = false
      timerRef.current = setInterval(() => {
        tick()
      }, 1000)
    } else if (isRunning && remainingTime <= 0 && !timerNotifiedRef.current) {
      timerNotifiedRef.current = true
      notification.success({
        message: '番茄钟完成！',
        description: `恭喜完成任务：${currentTask}`,
        duration: 0,
      })
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('番茄钟完成！', {
          body: `任务：${currentTask}`,
          icon: '/favicon.ico',
        })
      }
    }

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }, [isRunning, remainingTime, tick, currentTask])

  // 标签页可见性变化时同步倒计时（避免后台节流导致的时间不准）
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (!document.hidden && isRunning) {
        tick()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [isRunning, tick])

  // 请求通知权限
  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  // 启动时迁移历史数据并同步未同步记录
  useEffect(() => {
    migrateLocalRecords().then(() => syncPendingRecords())
  }, [migrateLocalRecords, syncPendingRecords])

  // 番茄钟控制
  const handleStartPomodoro = () => {
    if (!pomodoroConfig.taskName) {
      message.warning('请先设置任务名称')
      setShowPomodoroModal(true)
      return
    }
    startTimer(pomodoroConfig.taskName, pomodoroConfig.duration, pomodoroConfig.taskId)
  }

  const handleCompletePomodoro = () => {
    completeTimer()
    message.success(`番茄钟完成！已记录到统计中，开始休息 ${pomodoroConfig.breakDuration} 分钟`)
    // 写入学习行为记忆，供 AI 感知学习状态
    if (pomodoroConfig.taskName) {
      void createMemory({
        memory_key: 'last_pomodoro_task',
        memory_value: `${pomodoroConfig.taskName}（${pomodoroConfig.duration}分钟，${new Date().toLocaleDateString('zh-CN')}）`,
        category: 'style',
        confidence: 0.9,
      })
    }
  }

  const handleAbandonPomodoro = () => {
    setSelectedStopReason(null)
    setShowStopReasonModal(true)
  }

  const handleConfirmStopReason = async (reason: 'early_done' | 'interrupted' | 'distracted') => {
    const { currentBackendId, startedAt, pausedTotalMs } = usePomodoroStore.getState()
    if (currentBackendId) {
      const elapsedMs = startedAt ? Math.max(0, Date.now() - startedAt - pausedTotalMs) : 0
      const actualMinutes = Math.max(0.1, Math.round(elapsedMs / 1000 / 60 * 10) / 10)
      await pomodoroApi.completePomodoro(currentBackendId, false, undefined, actualMinutes, reason)
    }
    resetTimer()
    setShowStopReasonModal(false)
    setSelectedStopReason(null)
    const msgs: Record<string, string> = {
      early_done: '提前完成，状态不错！已记录为高效时段 💪',
      interrupted: '临时中断，已记录。继续加油！',
      distracted: '没关系，休息一下再来。已记录状态 😊',
    }
    message.info(msgs[reason])
  }

  useEffect(() => {
    try {
      const raw = localStorage.getItem('pending_pomodoro_task')
      if (!raw) return
      const parsed = JSON.parse(raw) as { taskId?: number; title?: string }
      const pendingTitle = parsed?.title?.trim() || ''
      if (pendingTitle) {
        setPomodoroConfig((prev) => ({
          ...prev,
          taskName: pendingTitle,
          taskId: parsed.taskId ?? null,
        }))
      }
      localStorage.removeItem('pending_pomodoro_task')
    } catch {
      localStorage.removeItem('pending_pomodoro_task')
    }
  }, [])

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }

  // 周统计图表配置
  const weekChartOption = useMemo(() => ({
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const data = params[0]
        const dayData = stats.weeklyData[data.dataIndex]
        return `${['日', '一', '二', '三', '四', '五', '六'][new Date(dayData?.date).getDay()] || ''}<br/>🍅 ${data.value} 个<br/>⏱️ ${dayData?.minutes || 0} 分钟`
      },
    },
    grid: { top: 10, right: 10, bottom: 20, left: 30 },
    xAxis: {
      type: 'category',
      data: stats.weeklyData.map((d) => ['日', '一', '二', '三', '四', '五', '六'][new Date(d.date).getDay()]),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: 'var(--text-tertiary)', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: 'rgba(0,0,0,0.05)' } },
      axisLabel: { color: 'var(--text-tertiary)', fontSize: 10 },
    },
    series: [{
      type: 'bar',
      data: stats.weeklyData.map((d) => d.count),
      barWidth: '50%',
      itemStyle: {
        color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#ff7875' }, { offset: 1, color: '#ff4d4f' }] },
        borderRadius: [4, 4, 0, 0],
      },
    }],
  }), [stats.weeklyData])

  // 上传资料
  const handleUpload = async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('title', file.name)
    formData.append('sync_to_anythingllm', syncToRAG ? 'true' : 'false')

    try {
      const response = await apiFetch('/api/materials/upload', {
        method: 'POST',
        body: formData,
      })

      if (response.ok) {
        const data = await response.json()
        const isDuplicate = Boolean(data?.duplicate)
        const fileExt = file.name.split('.').pop()?.toLowerCase() || ''
        const newMaterial: Material = {
          id: data.id || Date.now(),
          name: data.title || file.name,
          uploadTime: dayjs().format('YYYY-MM-DD'),
          file_type: fileExt,
          file_path: data.file_path,
          project_ids: data.project_ids || [],
        }
        if (activeProjectId) {
          try {
            await addProjectMaterial(activeProjectId, newMaterial.id)
            newMaterial.project_ids = Array.from(new Set([...(newMaterial.project_ids || []), activeProjectId]))
            const detail = await getProject(activeProjectId)
            setActiveProjectMaterialIds(detail?.material_ids || [])
          } catch {
            // ignore
          }
        }
        setMaterials((prev) => {
          if (prev.some((m) => m.id === newMaterial.id)) return prev
          return [newMaterial, ...prev]
        })
        if (isDuplicate) {
          message.info(`已存在：${file.name}（已复用资料库）`)
        } else {
          message.success(`已上传：${file.name}`)
        }
      } else {
        const err = await response.json().catch(() => null)
        message.error(err?.detail || '上传失败')
      }
    } catch (error) {
      message.error('上传失败：无法连接后端（请确认后端已启动）')
    }
    return false
  }

  // 预览资料
  const handlePreview = async (material: Material) => {
    setCurrentMaterial(material)
    setPreviewVisible(true)
    setPreviewLoading(true)

    try {
      // 尝试从后端获取内容
      const response = await apiFetch(`/api/materials/${material.id}`)
      if (response.ok) {
        const data = await response.json()
        setPreviewContent(data.content || '暂无内容预览')
      } else {
        setPreviewContent('暂无内容预览，请确保后端服务已启动')
      }
    } catch (error) {
      // 本地模拟
      if (material.file_type === 'pdf') {
        setPreviewContent('PDF文件预览需要启动后端服务来提取文本内容')
      } else {
        setPreviewContent('请启动后端服务后，重新上传资料以支持预览功能')
      }
    }
    setPreviewLoading(false)
  }

  // 删除资料
  const deleteMaterial = async (id: number) => {
    try {
      await apiFetch(`/api/materials/${id}`, { method: 'DELETE' })

      setMaterials((prev) => prev.filter((m) => m.id !== id))
      setSelectedMaterialIds((prev) => {
        if (!prev.has(id)) return prev
        const next = new Set(prev)
        next.delete(id)
        return next
      })
      message.success('已删除')
    } catch (e: any) {
      message.error(e?.message || '删除失败（请确认后端已启动）')
    }
  }

  // loadWeeklyPlans is called by the backendReady effect above

  const loadWeeklyPlans = async () => {
    // 周一到周日
    const start = dayjs().startOf('week').add(1, 'day')
    const end = start.add(6, 'day')
    const startStr = start.format('YYYY-MM-DD')
    const endStr = end.format('YYYY-MM-DD')
    try {
      const arr = await apiFetch<any[]>(`/api/plans/?start=${startStr}&end=${endStr}`)
      const list: DailyPlan[] = (arr || []).map((p: any) => ({ date: p.date, content: p.content || '' }))
      setWeeklyPlans(list)
      // 合并到缓存，使日历上的小绿点即时显示
      setDailyPlans((prev) => {
        const next = { ...prev }
        for (const p of list) next[p.date] = p.content
        return next
      })
    } catch {
      // ignore
    }
  }

  // 日历相关
  const onDateSelect = (date: Dayjs) => {
    setSelectedDate(date)
    const dateStr = date.format('YYYY-MM-DD')
      ; (async () => {
        try {
          const j = await apiFetch<any>(`/api/plans/${dateStr}`)
          setCurrentPlan(j.content || '')
          setDailyPlans((prev) => ({ ...prev, [dateStr]: j.content || '' }))
        } catch {
          setCurrentPlan(dailyPlans[dateStr] || '')
        } finally {
          setShowPlanModal(true)
        }
      })()
  }

  const savePlan = () => {
    if (selectedDate) {
      const dateStr = selectedDate.format('YYYY-MM-DD')
        ; (async () => {
          try {
            await apiFetch(`/api/plans/${dateStr}`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ content: currentPlan }),
            })
            setDailyPlans((prev) => ({ ...prev, [dateStr]: currentPlan }))
            message.success('计划已保存')
            setShowPlanModal(false)
            await loadWeeklyPlans()
          } catch (e: any) {
            message.error(e?.message || '保存失败（请确认后端已启动）')
          }
        })()
    }
  }

  useEffect(() => {
    if (!showPlanModal) return
    const timer = window.setTimeout(() => {
      planEditorRef.current?.focus()
    }, 100)
    return () => window.clearTimeout(timer)
  }, [showPlanModal])

  const renderDateBadge = (value: Dayjs) => {
    const dateStr = value.format('YYYY-MM-DD')
    const hasPlan = dailyPlans[dateStr]
    return hasPlan ? (
      <Badge status="success" text="" />
    ) : null
  }

  // Feature 1: Show loading overlay while waiting for backend
  if (!backendReady) {
    return <BackendLoadingOverlay />
  }

  const isChatEmpty = chatMessages.length === 0 && !streamingContent
  const canSendMessage = Boolean(chatInput.trim()) && !chatLoading && !agentWriteLoading

  return (
    <Layout style={{ minHeight: '100vh', position: 'relative' }}>
      <GlobalNavRail
        pathname={location.pathname}
        isRunning={isRunning}
        isPaused={isPaused}
        remainingTimeLabel={formatTime(remainingTime)}
        onNavigate={navigate}
        onOpenPomodoro={() => setShowPomodoroModal(true)}
        onOpenOnboarding={() => setShowOnboarding(true)}
        onOpenSettings={() => setShowSettings(true)}
        beginnerMode={beginnerMode}
        onToggleBeginnerMode={() => setBeginnerMode((v) => !v)}
      />

      {bgImage && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 0, pointerEvents: 'none',
          backgroundImage: `url(${bgImage})`,
          backgroundSize: 'cover', backgroundPosition: 'center',
          opacity: bgOpacity,
        }} />
      )}
      {/* 第二层左侧边栏（对话/资料库） */}
      <Sider
        className={`mnemox-left-sidebar${leftCollapsed ? ' is-collapsed' : ''}`}
        width={effectiveLeftWidth}
        style={{
          background: 'var(--bg-surface)',
          borderRight: '1px solid var(--border-light)',
          overflow: 'hidden',
          height: '100vh',
          position: 'fixed',
          left: 64, // Shifted right by 64px
          display: 'flex',
          flexDirection: 'column',
          transition: 'width var(--duration-normal) var(--ease-out)',
        }}
      >
        {leftCollapsed ? (
          <div style={{ height: '100%', paddingBottom: 52 }}>
            <ConversationSidebar
              collapsed
              onExpandSidebar={(target) => {
                setLeftExpandTarget(target || 'default')
                setLeftCollapsed(false)
              }}
              onOpenProjectSettings={(projectId) => {
                setEditingProjectId(projectId)
                setProjectSettingsOpen(true)
              }}
              onOpenProjectMaterials={() => {
                setProjectMaterialsOpen(true)
                setLeftSidebarTab('conversations')
              }}
            />
          </div>
        ) : (
          <Tabs
            activeKey={leftSidebarTab}
            onChange={setLeftSidebarTab}
            size="small"
            centered
            style={{ height: '100%' }}
            items={[
              {
                key: 'conversations',
                label: (
                  <span>
                    <MessageOutlined /> 对话
                  </span>
                ),
                children: (
                  <div style={{ height: 'calc(100vh - 46px)', overflow: 'auto', background: 'var(--bg-primary)' }}>
                    <ConversationSidebar
                      expandTarget={leftExpandTarget}
                      onExpandTargetHandled={() => setLeftExpandTarget(null)}
                      onOpenProjectSettings={(projectId) => {
                        setEditingProjectId(projectId)
                        setProjectSettingsOpen(true)
                      }}
                      onOpenProjectMaterials={() => {
                        setProjectMaterialsOpen(true)
                        setLeftSidebarTab('conversations')
                      }}
                    />
                  </div>
                ),
              },
              {
                key: 'materials',
                label: (
                  <span>
                    <FileOutlined /> 资料
                  </span>
                ),
                children: (
                <div style={{ height: 'calc(100vh - 46px)', overflow: 'auto', background: 'var(--bg-primary)' }}>
                  {/* 资料 */}
                  <div style={{ padding: '16px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 16 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                          <FileOutlined /> 资料
                        </h3>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <Tag style={{ margin: 0, fontSize: 11 }}>
                            {filteredMaterials.length}/{visibleMaterials.length}
                          </Tag>
                          <Tooltip title={showUploadArea ? '收起上传' : '上传资料'}>
                            <Button
                              type={showUploadArea ? 'primary' : 'text'}
                              size="small"
                              icon={<UploadOutlined />}
                              onClick={() => setShowUploadArea((v) => !v)}
                              style={{ padding: '0 6px', color: showUploadArea ? undefined : 'var(--primary-600)' }}
                            />
                          </Tooltip>
                        </div>
                      </div>
                      <div style={{ display: 'grid', gap: 8 }}>
                        <Segmented
                          block
                          size="small"
                          value={activeProjectId && projectMaterialsOnly ? 'project' : 'all'}
                          onChange={(val) => setProjectMaterialsOnly(val === 'project')}
                          options={[
                            { label: '当前项目', value: 'project', disabled: !activeProjectId },
                            { label: '全部资料', value: 'all' },
                          ]}
                        />
                        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(96px, 0.8fr) minmax(0, 1.2fr)', gap: 8 }}>
                          <Select
                            size="small"
                            value={materialTypeFilter}
                            onChange={setMaterialTypeFilter}
                            options={materialTypeOptions}
                            style={{ width: '100%' }}
                          />
                          <Input
                            size="small"
                            placeholder="搜索资料..."
                            value={materialSearch}
                            onChange={(e) => setMaterialSearch(e.target.value)}
                            style={{ width: '100%' }}
                            allowClear
                          />
                        </div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                          {activeProjectId && selectedMaterialIds.size > 0 && (
                            <Button
                              type="primary"
                              size="small"
                              onClick={async () => {
                                const ids = Array.from(selectedMaterialIds)
                                try {
                                  await Promise.all(ids.map((id) => addProjectMaterial(activeProjectId, id)))
                                  const detail = await getProject(activeProjectId)
                                  setActiveProjectMaterialIds(detail?.material_ids || [])
                                  await loadMaterials()
                                  message.success('已绑定到当前项目')
                                } catch {
                                  message.error('绑定失败')
                                }
                              }}
                              style={{ fontSize: 11 }}
                            >
                              绑定到当前项目
                            </Button>
                          )}
                          {activeProjectId && selectedMaterialIds.size > 0 && (
                            <Button
                              type="text"
                              size="small"
                              onClick={async () => {
                                const ids = Array.from(selectedMaterialIds)
                                try {
                                  await Promise.all(ids.map((id) => removeProjectMaterial(activeProjectId, id)))
                                  const detail = await getProject(activeProjectId)
                                  setActiveProjectMaterialIds(detail?.material_ids || [])
                                  await loadMaterials()
                                  message.success('已从当前项目移除')
                                } catch {
                                  message.error('移除失败')
                                }
                              }}
                              style={{ fontSize: 11, color: 'var(--text-secondary)' }}
                            >
                              从当前项目移除
                            </Button>
                          )}
                          <Button
                            type="text"
                            size="small"
                            loading={archiveMaterialsLoading}
                            onClick={async () => {
                              setArchiveMaterialsLoading(true)
                              try {
                                const result = await archiveUnassignedMaterials()
                                if (result.added_count > 0) {
                                  message.success(`已归档 ${result.added_count} 份资料到 ${result.project_name}`)
                                } else {
                                  message.info('暂无未分类资料')
                                }
                                if (activeProjectId === result.project_id) {
                                  const detail = await getProject(result.project_id)
                                  setActiveProjectMaterialIds(detail.material_ids || [])
                                }
                              } catch {
                                message.error('归档失败')
                              } finally {
                                setArchiveMaterialsLoading(false)
                              }
                            }}
                            style={{ fontSize: 11, color: 'var(--text-secondary)' }}
                          >
                            归档未分类
                          </Button>
                          {selectedMaterialIds.size > 0 && (
                            <Button
                              type="primary"
                              size="small"
                              loading={batchLearningLoading}
                              onClick={async () => {
                                const ids = Array.from(selectedMaterialIds)
                                setBatchLearningLoading(true)
                                try {
                                  const result = await startBatchLearningPipeline(ids)
                                  if (result) {
                                    message.success(`批量学习完成：共生成 ${result.total_tasks} 个学习任务`)
                                    await loadReviewOverview()
                                    await loadDashboardOverview()
                                  } else {
                                    message.error('批量学习失败')
                                  }
                                } catch {
                                  message.error('批量学习失败')
                                } finally {
                                  setBatchLearningLoading(false)
                                }
                              }}
                              style={{ fontSize: 11 }}
                            >
                              批量学习 ({selectedMaterialIds.size})
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>

                    {showUploadArea && (
                      <div style={{ marginBottom: 12 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>同步到 RAG 知识库</span>
                          <Switch size="small" checked={syncToRAG} onChange={setSyncToRAG} />
                        </div>
                        {ragStatus && (
                          <div style={{ marginBottom: 6 }}>
                            <Tag color={ragStatus.enabled && ragStatus.rag_online ? 'green' : ragStatus.fallback_active || !ragStatus.embedding_enabled ? 'orange' : 'default'}>
                              RAG: {ragStatus.rag_online ? '在线' : 'Fallback'}
                            </Tag>
                            {ragStatus.rag_online && <Tag color="blue">{ragStatus.total_chunks} chunks</Tag>}
                          </div>
                        )}
                        <Upload.Dragger
                          multiple
                          beforeUpload={handleUpload}
                          showUploadList={false}
                          accept=".pdf,.docx,.txt,.md"
                        >
                          <p><UploadOutlined style={{ fontSize: 20, color: 'var(--text-secondary)' }} /></p>
                          <p style={{ fontSize: 12, color: 'var(--text-primary)', margin: '6px 0 2px' }}>点击或拖拽文件上传</p>
                          <p style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>PDF、Word、TXT、Markdown</p>
                        </Upload.Dragger>
                      </div>
                    )}

                    {selectedMaterialIds.size > 0 && (
                      <div style={{ marginBottom: 8, padding: '6px 8px', background: 'var(--accent-50)', borderRadius: 'var(--radius-sm)', fontSize: 11, color: 'var(--accent-700)' }}>
                        已选 {selectedMaterialIds.size} 份资料，将作为 AI 对话的参考上下文
                      </div>
                    )}

                    <List
                      size="small"
                      dataSource={filteredMaterials}
                      loading={materialsLoading}
                      locale={{
                        emptyText: materialSearch.trim() || materialTypeFilter !== 'all'
                          ? '没有匹配的资料'
                          : (activeProjectId ? '该项目暂无资料' : '暂无资料'),
                      }}
                      renderItem={(item) => {
                        const projectNames = (item.project_ids || []).map((id) => projectNameMap.get(id) || `项目 #${id}`)
                        const isHovered = hoveredMaterialId === item.id
                        const isSelected = selectedMaterialIds.has(item.id)
                        return (
                          <List.Item
                            actions={isHovered || isSelected ? [
                              <Button
                                type="text"
                                size="small"
                                loading={startLearningLoadingId === item.id}
                                onClick={async (e) => {
                                  e.stopPropagation()
                                  setStartLearningLoadingId(item.id)
                                  try {
                                    const result = await startLearningPipeline(item.id)
                                    if (result) {
                                      message.success(`已创建学习目标，自动生成 ${result.auto_created_tasks} 个学习任务`)
                                      await loadReviewOverview()
                                      await loadDashboardOverview()
                                    } else {
                                      message.error('分析失败，请确认资料已上传')
                                    }
                                  } catch {
                                    message.error('开始学习失败')
                                  } finally {
                                    setStartLearningLoadingId(null)
                                  }
                                }}
                                title="开始学习"
                                style={{ color: 'var(--success)', fontSize: 11 }}
                              >
                                学习
                              </Button>,
                              <Button
                                type="text"
                                size="small"
                                icon={<FileOutlined />}
                                onClick={(e) => { e.stopPropagation(); handlePreview(item) }}
                                title="预览"
                                style={{ color: 'var(--primary-600)' }}
                              />,
                              <Button
                                type="text"
                                size="small"
                                danger
                                icon={<DeleteOutlined />}
                                onClick={(e) => { e.stopPropagation(); deleteMaterial(item.id) }}
                                title="删除"
                              />,
                            ] : []}
                            style={{
                              cursor: 'pointer',
                              padding: '6px 10px',
                              background: isSelected ? 'var(--accent-50)' : isHovered ? 'var(--gray-50)' : 'transparent',
                              borderLeft: isSelected ? '3px solid var(--accent-600)' : '3px solid transparent',
                              transition: 'background var(--duration-fast)',
                            }}
                            onMouseEnter={() => setHoveredMaterialId(item.id)}
                            onMouseLeave={() => setHoveredMaterialId(null)}
                            onClick={() => {
                              setSelectedMaterialIds((prev) => {
                                const next = new Set(prev)
                                if (next.has(item.id)) {
                                  next.delete(item.id)
                                } else {
                                  next.add(item.id)
                                }
                                return next
                              })
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0, overflow: 'hidden' }}>
                              <Checkbox
                                checked={selectedMaterialIds.has(item.id)}
                                onClick={(e) => e.stopPropagation()}
                                onChange={() => {
                                  setSelectedMaterialIds((prev) => {
                                    const next = new Set(prev)
                                    if (next.has(item.id)) {
                                      next.delete(item.id)
                                    } else {
                                      next.add(item.id)
                                    }
                                    return next
                                  })
                                }}
                                style={{ flexShrink: 0 }}
                              />
                              <List.Item.Meta
                                avatar={<FileOutlined style={{ color: item.file_type === 'pdf' ? '#ff4d4f' : '#b07d3a' }} />}
                                title={
                                  <span style={{
                                    fontSize: 12,
                                    fontWeight: 500,
                                    color: 'var(--text-primary)',
                                    whiteSpace: 'nowrap',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    display: 'block',
                                  }}>
                                    {item.name}
                                  </span>
                                }
                                description={
                                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                                    <span style={{ fontSize: 10, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                                      {item.uploadTime} · {item.file_type?.toUpperCase() || 'FILE'}
                                    </span>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                                      {projectNames.length > 0 ? (
                                        projectNames.map((name) => (
                                          <Tag key={`${item.id}-${name}`} style={{ fontSize: 10, lineHeight: '16px' }}>
                                            {name}
                                          </Tag>
                                        ))
                                      ) : (
                                        <Tag style={{ fontSize: 10, lineHeight: '16px', color: 'var(--text-tertiary)' }}>未分类</Tag>
                                      )}
                                    </div>
                                  </div>
                                }
                              />
                            </div>
                          </List.Item>
                        )
                      }}
                    />
                  </div>
                </div>
                ),
              },
            ]}
          />
        )}
        {/* User info + logout */}
        <div style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          padding: '10px 14px',
          borderTop: '1px solid var(--border-color)',
          background: 'var(--bg-secondary)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
        }}>
          {leftCollapsed ? (
            <div style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
              <Tooltip title={user?.username || '用户'} placement="right" mouseEnterDelay={0.25}>
                <Button
                  type="text"
                  size="small"
                  icon={<UserOutlined />}
                  onClick={() => setLeftCollapsed(false)}
                  style={{ color: 'var(--text-tertiary)' }}
                />
              </Tooltip>
            </div>
          ) : (
            <>
              <span style={{ color: 'var(--text-secondary)', fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{
                  width: 24,
                  height: 24,
                  borderRadius: 'var(--radius-full)',
                  background: 'linear-gradient(135deg, var(--accent-200), var(--primary-200))',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 11,
                  fontWeight: 600,
                  color: 'var(--accent-700)',
                  flexShrink: 0,
                }}>
                  {(user?.username || '用')[0]}
                </div>
                {user?.username || ''}
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <SyncStatusIndicator />
                <Button
                  type="text"
                  size="small"
                  icon={<LogoutOutlined />}
                  onClick={() => { logout(); navigate('/login') }}
                  style={{ color: 'var(--text-tertiary)' }}
                  title="退出登录"
                />
              </span>
            </>
          )}
        </div>
      </Sider>

      <Tooltip title={leftCollapsed ? '展开左侧栏' : '收起左侧栏'} placement="right">
        <Button
          type="text"
          shape="circle"
          icon={leftCollapsed ? <DoubleRightOutlined /> : <DoubleLeftOutlined />}
          className="mnemox-sidebar-toggle mnemox-sidebar-toggle-left"
          onClick={() => setLeftCollapsed((value) => !value)}
          style={{ left: 64 + effectiveLeftWidth - 14 }}
          aria-label={leftCollapsed ? '展开左侧栏' : '收起左侧栏'}
        />
      </Tooltip>

      {/* 左侧拖拽分割线 */}
      {!leftCollapsed && (
        <div
          className={`panel-splitter${dragging === 'left' ? ' active' : ''}`}
          style={{
            position: 'fixed',
            left: effectiveLeftWidth + 64 - 3,
            top: 0,
            width: 6,
            height: '100vh',
            cursor: 'col-resize',
            zIndex: 100,
            background: 'transparent',
          }}
          onMouseDown={() => setDragging('left')}
        />
      )}

      {/* 中间内容区 */}
      <Layout
        className="mnemox-main-layout"
        style={{
          marginLeft: effectiveLeftWidth + 64,
          marginRight: effectiveRightWidth,
          background: 'transparent',
          transition: 'margin var(--duration-normal) var(--ease-out)',
        }}
      >
        <Content style={{ padding: '0', background: 'transparent', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
          <div className={`mnemox-chat-frame${isChatEmpty ? ' is-empty' : ' has-messages'}`}>
            {/* Top toolbar removed, replaced by PageShell global nav */}
            <div style={{ height: 16 }} />

            {!focusMode && <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, marginBottom: 8, padding: '6px 0' }}>
              <Tag style={{ fontSize: 11, borderRadius: 'var(--radius-sm)' }}>{activeConversationId ? `对话 #${activeConversationId}` : '未选择对话'}</Tag>
              <Tag color={activeProjectId ? 'blue' : 'default'} style={{ fontSize: 11, borderRadius: 'var(--radius-sm)' }}>{activeProjectId ? `项目 #${activeProjectId}` : '未分配项目'}</Tag>
              {chatLoading && <Tag color="orange" style={{ fontSize: 11, borderRadius: 'var(--radius-sm)' }}>正在生成</Tag>}
              <div style={{ flex: 1 }} />
              <Button
                size="small"
                type="dashed"
                onClick={async () => {
                  const today = dayjs().format('YYYY-MM-DD')
                  try {
                    const result = await generateDailyPlan(today)
                    if (result) {
                      message.success(`已生成今日计划，共 ${result.item_count} 项`)
                      await loadWeeklyPlans()
                      // Open the plan modal for today
                      setSelectedDate(dayjs())
                      setCurrentPlan(result.content)
                      setDailyPlans((prev) => ({ ...prev, [today]: result.content }))
                      setShowPlanModal(true)
                    } else {
                      message.warning('生成计划失败')
                    }
                  } catch {
                    message.error('生成计划失败')
                  }
                }}
              >
                生成今日计划
              </Button>
            </div>}

            {!focusMode && activeProjectId && (
              <div style={{ marginBottom: 8, padding: '8px 10px', border: '1px solid var(--border-light)', borderRadius: 'var(--radius-md)', background: 'var(--bg-tertiary)' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>当前项目默认资料（自动注入）</span>
                  <Button
                    type="link"
                    size="small"
                    onClick={() => {
                      setEditingProjectId(activeProjectId)
                      setProjectSettingsOpen(true)
                    }}
                  >
                    管理
                  </Button>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {activeProjectMaterialIds.length === 0 ? (
                    <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>未绑定资料</span>
                  ) : (
                    activeProjectMaterialIds.map((id) => {
                      const m = materials.find((x) => x.id === id)
                      return <Tag key={`proj-${id}`}>{m?.name || `资料 #${id}`}</Tag>
                    })
                  )}
                </div>
              </div>
            )}

            {!focusMode && (selectedMaterialIds.size > 0 || detectedMaterials.length > 0) && (
              <div style={{
                padding: '8px 12px',
                background: 'var(--accent-50)',
                borderRadius: 'var(--radius-md)',
                marginBottom: 4,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: selectedMaterialIds.size > 0 ? 4 : 0 }}>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                    <FileOutlined style={{ marginRight: 4 }} />
                    已选资料：
                  </span>
                  {selectedMaterialIds.size > 0 && (
                    <Button
                      type="text"
                      size="small"
                      onClick={() => setSelectedMaterialIds(new Set())}
                      style={{ color: 'var(--text-tertiary)', fontSize: 12 }}
                    >
                      全部取消
                    </Button>
                  )}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {Array.from(selectedMaterialIds).map((id) => {
                    const mat = materials.find((m) => m.id === id)
                    return mat ? (
                      <Tag
                        key={id}
                        closable
                        color="blue"
                        onClose={() => {
                          setSelectedMaterialIds((prev) => {
                            const next = new Set(prev)
                            next.delete(id)
                            return next
                          })
                        }}
                        style={{ fontSize: 12 }}
                      >
                        {mat.name}
                      </Tag>
                    ) : null
                  })}
                  {detectedMaterials
                    .filter((d) => !selectedMaterialIds.has(d.id))
                    .map((d) => (
                      <Tag key={`det-${d.id}`} color="green" style={{ fontSize: 12 }}>
                        {d.title}（AI 识别）
                      </Tag>
                    ))}
                </div>
              </div>
            )}

            {isChatEmpty ? (
              <div className="mnemox-start-screen" aria-label="聊天开始区">
                <h1 className="mnemox-start-title">
                  今天想从哪里开始？
                </h1>
              </div>
            ) : (
              <div
                ref={chatScrollRef}
                className="mnemox-chat-stage"
                onScroll={handleChatScroll}
              >
                {chatLoading && (
                  <div className="mnemox-streaming-status">
                    <span>
                      <i aria-hidden="true" />
                      AI 正在回答中...
                    </span>
                    <Button size="small" danger onClick={handleStopStreaming}>停止</Button>
                  </div>
                )}
                <div>
                  {chatMessages.map((msg, idx) => (
                    <ChatMessageBubble
                      key={idx}
                      role={msg.role}
                      content={msg.content}
                      imageData={msg.image_data}
                      onQuoteToNote={msg.role === 'assistant' ? quoteAssistantToNote : undefined}
                      onRegenerate={msg.role === 'assistant' ? () => void handleRegenerateAssistant(idx) : undefined}
                      onBranch={msg.role === 'assistant' ? () => void handleBranchFromAssistant(idx) : undefined}
                      onEdit={msg.role === 'user' ? (next) => void handleEditUserMessage(idx, next) : undefined}
                    />
                  ))}
                  {streamingContent && (
                    <ChatMessageBubble
                      role="assistant"
                      content={streamingContent}
                      isStreaming
                    />
                  )}
                  <div ref={chatEndRef} />
                </div>
              </div>
            )}

            {/* 输入区域 */}
            <div className="mnemox-chat-composer">
              <div className="mnemox-input-shell">
                <div className="mnemox-composer-row">
                  <Tooltip title="上传图片">
                    <Button
                      size="middle"
                      shape="circle"
                      className="mnemox-tool-button"
                      icon={<PictureOutlined />}
                      onClick={() => imageInputRef.current?.click()}
                      aria-label="上传图片"
                    />
                  </Tooltip>
                  <TextArea
                    id="mnemox-chat-input"
                    name="mnemox-chat-input"
                    className="mnemox-chat-input"
                    placeholder="输入问题，或让 AI 基于当前资料生成计划..."
                    autoSize={{ minRows: isChatEmpty ? 1 : 2, maxRows: 7 }}
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onPaste={(e) => {
                      const items = e.clipboardData?.items
                      if (!items) return
                      for (let i = 0; i < items.length; i++) {
                        if (items[i].type.startsWith('image/')) {
                          e.preventDefault()
                          const file = items[i].getAsFile()
                          if (file) handleImageSelect(file)
                          return
                        }
                      }
                    }}
                    onPressEnter={(e) => {
                      if (!e.shiftKey) {
                        e.preventDefault()
                        if (canSendMessage) {
                          void handleSendMessage()
                        }
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'ArrowUp' && !chatInput.trim()) {
                        const last = getLastUserMessage()
                        if (last) {
                          e.preventDefault()
                          setChatInput(last)
                        }
                      }
                    }}
                    disabled={chatLoading}
                  />
                </div>
                {/* Image preview strip */}
                {pendingImages.length > 0 && (
                  <div className="mnemox-image-preview-strip">
                    {pendingImages.map((img, idx) => (
                      <div key={idx} style={{ position: 'relative', width: 64, height: 64 }}>
                        <img
                          src={`data:image/png;base64,${img}`}
                          alt={`待发送图片 ${idx + 1}`}
                          style={{ width: 64, height: 64, objectFit: 'cover', borderRadius: 8, border: '1px solid var(--border-light)' }}
                        />
                        <CloseCircleFilled
                          onClick={() => setPendingImages(prev => prev.filter((_, i) => i !== idx))}
                          style={{
                            position: 'absolute',
                            top: -6,
                            right: -6,
                            fontSize: 18,
                            color: '#ff4d4f',
                            cursor: 'pointer',
                            background: 'var(--bg-elevated)',
                            borderRadius: '50%',
                          }}
                        />
                      </div>
                    ))}
                  </div>
                )}
                {/* Hidden file input for image upload */}
                <input
                  id="mnemox-image-upload"
                  name="mnemox-image-upload"
                  ref={imageInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/gif,image/webp,image/bmp"
                  style={{ display: 'none' }}
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (file) handleImageSelect(file)
                    e.target.value = ''
                  }}
                />
                <div className="mnemox-input-actions">
                  {!autoScrollEnabled && (
                    <Button
                      size="middle"
                      onClick={() => {
                        setAutoScrollEnabled(true)
                        chatScrollRef.current?.scrollTo({ top: chatScrollRef.current.scrollHeight, behavior: 'smooth' })
                      }}
                    >
                      回到底部
                    </Button>
                  )}
                  <Select
                    size="small"
                    className="mnemox-model-select"
                    showSearch
                    value={selectedChatModel}
                    onChange={setSelectedChatModel}
                    options={chatModelOptions}
                    optionFilterProp="label"
                    popupMatchSelectWidth={false}
                    aria-label="聊天模型"
                  />
                  {chatLoading ? (
                    <Button
                      type="primary"
                      danger
                      size="middle"
                      className="mnemox-stop-button"
                      onClick={handleStopStreaming}
                    >
                      停止生成
                    </Button>
                  ) : (
                    <Button
                      type="primary"
                      size="middle"
                      shape="circle"
                      className="mnemox-send-button"
                      icon={<SendOutlined />}
                      disabled={!canSendMessage}
                      loading={agentWriteLoading}
                      onClick={() => void handleSendMessage()}
                      aria-label="发送"
                    />
                  )}
                </div>
              </div>
              {isChatEmpty && (
                <div className="mnemox-prompt-chips" aria-label="快捷提问">
                  {['复习昨天', '生成今日计划', '出 5 道题', '费曼解释'].map((label) => (
                    <button
                      key={label}
                      className="mnemox-prompt-chip"
                      type="button"
                      onClick={() => setChatInput(label)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </Content>
      </Layout>

      <Tooltip title={rightCollapsed ? '展开右侧栏' : '收起右侧栏'} placement="left">
        <Button
          type="text"
          shape="circle"
          icon={rightCollapsed ? <DoubleLeftOutlined /> : <DoubleRightOutlined />}
          className="mnemox-sidebar-toggle mnemox-sidebar-toggle-right"
          onClick={() => setRightCollapsed((value) => !value)}
          style={{ right: rightCollapsed ? 12 : effectiveRightWidth - 14 }}
          aria-label={rightCollapsed ? '展开右侧栏' : '收起右侧栏'}
        />
      </Tooltip>

      {/* 右侧拖拽分割线 */}
      {!rightCollapsed && (
        <div
          className={`panel-splitter${dragging === 'right' ? ' active' : ''}`}
          style={{
            position: 'fixed',
            right: rightWidth - 3,
            top: 0,
            width: 6,
            height: '100vh',
            cursor: 'col-resize',
            zIndex: 100,
            background: 'transparent',
          }}
          onMouseDown={() => setDragging('right')}
        />
      )}

      {/* 右侧信息栏 */}
      <Sider
        className={`mnemox-right-sidebar${rightCollapsed ? ' is-collapsed' : ''}`}
        width={effectiveRightWidth}
        style={{
          overflow: 'hidden',
          height: '100vh',
          position: 'fixed',
          right: 0,
          transition: 'width var(--duration-normal) var(--ease-out)',
        }}
      >
        {!rightCollapsed && (
        <div className="mnemox-right-sidebar-content" style={{ height: '100%', overflowY: 'auto', padding: '16px' }}>
        {/* 设置小组件按钮 */}
        <div style={{ position: 'relative', display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
          <Button
            size="small"
            type={sortMode || customizeOpen ? 'primary' : 'text'}
            icon={<SettingOutlined />}
            onClick={() => setCustomizeOpen(value => !value)}
          >
            {sortMode ? '完成排序' : '自定义'}
          </Button>
          {customizeOpen && (
            <div
              style={{
                position: 'absolute',
                top: 34,
                right: 0,
                zIndex: 20,
                width: 236,
                padding: 8,
                borderRadius: 12,
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border-color)',
                boxShadow: 'var(--shadow-lg)',
              }}
            >
                <Button
                  type="text"
                  block
                  icon={sortMode ? <CheckSquareOutlined /> : <MenuOutlined />}
                  onClick={() => setSortMode(v => !v)}
                  style={{ justifyContent: 'flex-start', marginBottom: 6 }}
                >
                  {sortMode ? '完成排序' : '开启排序模式'}
                </Button>
                <div style={{ height: 1, background: 'var(--border-light)', margin: '4px 0 6px' }} />
                {ALL_CARDS.map(card => (
                  <div
                    key={card.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 12,
                      minHeight: 34,
                      padding: '4px 8px',
                    }}
                  >
                    <span style={{ fontSize: 13, color: 'var(--text-primary)' }}>{card.label}</span>
                    <Switch
                      size="small"
                      checked={visibleCards.includes(card.id)}
                      onChange={(checked) => updateCardVisibility(card.id, checked)}
                    />
                  </div>
                ))}
              </div>
          )}
        </div>
        {/* 右侧卡片按 cardOrder 动态渲染 */}
        {cardOrder.filter(id => visibleCards.includes(id)).map(cardId => {
          const dragProps = sortMode ? {
            draggable: true,
            onDragStart: () => { dragCardRef.current = cardId },
            onDragOver: (e: React.DragEvent) => e.preventDefault(),
            onDrop: () => {
              if (!dragCardRef.current || dragCardRef.current === cardId) return
              const from = dragCardRef.current
              setCardOrder(prev => {
                const next = [...prev]
                const fi = next.indexOf(from), ti = next.indexOf(cardId)
                if (fi < 0 || ti < 0) return prev
                next.splice(fi, 1)
                next.splice(ti, 0, from)
                localStorage.setItem('right_card_order', JSON.stringify(next))
                return next
              })
              dragCardRef.current = null
            },
            style: { cursor: 'grab', opacity: 1, marginBottom: 0 } as React.CSSProperties,
          } : {}

          if (cardId === 'motivation') return (
            <div key="motivation" {...dragProps}>
            <Card
              size="small"
              title={
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ fontSize: 14 }}>💪</span>
                  <span style={{ fontSize: 13, fontWeight: 500 }}>今日激励</span>
                </div>
              }
              extra={
                <div style={{ display: 'flex', gap: 2 }}>
                  <Button type="text" size="small" onClick={handleRefreshQuote} title="换一句" style={{ fontSize: 13 }}>🔄</Button>
                  <Button type="text" size="small" onClick={() => { setShowMotivationModal(true); void loadMotivationSettings(); void loadAllQuotes() }} title="管理" style={{ fontSize: 13 }}>⚙️</Button>
                </div>
              }
              style={{ marginBottom: 12 }}
            >
              <div style={{ textAlign: 'center', padding: '12px 4px' }}>
                <div style={{ fontSize: 14, fontStyle: 'italic', color: 'var(--text-secondary)', lineHeight: 1.7 }}>{motivationQuote?.content || '加载中...'}</div>
                {motivationQuote?.author && <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 8 }}>—— {motivationQuote.author}</div>}
              </div>
            </Card>
            </div>
          )

          if (cardId === 'calendar') return (
            <div key="calendar" {...dragProps}>
            <Card
              size="small"
              title={<div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><CalendarOutlined style={{ color: 'var(--accent-600)' }} /><span style={{ fontSize: 13, fontWeight: 500 }}>日历</span></div>}
              extra={<Button type="text" size="small" icon={calendarExpanded ? <UpOutlined /> : <DownOutlined />} onClick={() => setCalendarExpanded(!calendarExpanded)} />}
              style={{ marginBottom: 12 }}
            >
              {calendarExpanded ? (
                <div className="compact-calendar">
                  <Calendar
                    fullscreen={false}
                    onSelect={onDateSelect}
                    cellRender={(current, info) => (
                      info.type === 'date' ? <>{info.originNode}{renderDateBadge(current)}</> : info.originNode
                    )}
                  />
                </div>
              ) : (
                <div style={{ textAlign: 'center', padding: '4px 0', color: 'var(--text-tertiary)', fontSize: 12 }}>点击展开查看完整日历</div>
              )}
            </Card>
            </div>
          )

          if (cardId === 'current') return (
            <div key="current" {...dragProps}>
            <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 500 }}>当前学习</span>} style={{ marginBottom: 12 }}>
              <p style={{ color: 'var(--text-tertiary)', fontSize: 13, margin: 0 }}>暂未选择章节</p>
            </Card>
            </div>
          )

          if (cardId === 'review') return (
            <div key="review" {...dragProps}>
            <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 500 }}>复习任务</span>} style={{ marginBottom: 12 }}
              extra={<Button type="link" size="small" onClick={() => navigate('/review')} style={{ fontSize: 12 }}>去复习</Button>}
            >
              <div style={{ marginBottom: 10 }}>
                <Tag color={reviewDueCount > 0 ? 'red' : 'green'}>今日待复习 {reviewDueCount}</Tag>
              </div>
              <List size="small" dataSource={reviewPreviewTasks} locale={{ emptyText: '暂无到期任务' }}
                renderItem={(task) => (
                  <List.Item style={{ padding: '6px 0', cursor: 'pointer' }} onClick={() => navigate('/review')}>
                    <div style={{ width: '100%' }}>
                      <div style={{ fontSize: 12, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{task.content || '复习任务'}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{task.item_type === 'chapter' ? '章节复习' : '错题复习'} · {task.chapter_title || '未分类'}</div>
                    </div>
                  </List.Item>
                )}
              />
            </Card>
            </div>
          )

          if (cardId === 'progress') return (
            <div key="progress" {...dragProps}>
            <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 500 }}>今日进度</span>} style={{ marginBottom: 12 }}>
              {(() => {
                const totalTasks = dashboardData?.today_task_count || 0
                const completedTasks = dashboardData?.today_completed_count || 0
                const taskPercent = totalTasks > 0 ? Math.round((completedTasks / totalTasks) * 100) : 0
                return (
                  <div>
                    <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginBottom: 4 }}>完成任务（{completedTasks}/{totalTasks}）</div>
                    <Progress percent={taskPercent} size="small" status="active" strokeColor="var(--accent-500)" />
                  </div>
                )
              })()}
            </Card>
            </div>
          )

          if (cardId === 'pomodoro') return (
            <div key="pomodoro" {...dragProps}>
            <Card
              size="small"
              title={
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ fontSize: 14 }}>🍅</span>
                  <span style={{ fontSize: 13, fontWeight: 500 }}>番茄工作法</span>
                  <span title={backendOnline ? '已连接后端' : '离线模式'} style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: backendOnline ? 'var(--success)' : 'var(--gray-300)', marginLeft: 4 }} />
                </span>
              }
              extra={
                <div style={{ display: 'flex', gap: 4 }}>
                  <Button type="text" size="small" icon={<BarChartOutlined />} onClick={() => setShowStatsModal(true)} title="查看统计" />
                  <Button type="link" size="small" onClick={() => setShowPomodoroModal(true)}>设置</Button>
                </div>
              }
              style={{ marginBottom: 16 }}
            >
          <div style={{ textAlign: 'center' }}>
            {/* 今日统计 */}
            <Row gutter={8} style={{ marginBottom: 8 }}>
              <Col span={12}>
                <Statistic
                  title={<span style={{ fontSize: 11 }}>今日番茄</span>}
                  value={stats.todayCount}
                  suffix="个"
                  valueStyle={{ fontSize: 16, color: '#ff4d4f' }}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title={<span style={{ fontSize: 11 }}>专注时长</span>}
                  value={stats.todayMinutes}
                  suffix="分钟"
                  valueStyle={{ fontSize: 16, color: 'var(--primary-600)' }}
                />
              </Col>
            </Row>

            {(currentTask || pomodoroConfig.taskName) && (
              <div style={{ marginBottom: 4, fontSize: 12, color: 'var(--text-tertiary)' }}>
                {timerMode === 'break' ? `休息中（${duration} 分钟）` : (currentTask || pomodoroConfig.taskName)}
              </div>
            )}

            <div
              style={{
                fontSize: 40,
                fontWeight: 'bold',
                fontFamily: "'JetBrains Mono', monospace",
                margin: '8px 0',
                color: isRunning ? (timerMode === 'break' ? 'var(--teal-500)' : 'var(--error)') : 'var(--text-primary)',
                letterSpacing: '2px',
              }}
            >
              {formatTime(remainingTime)}
            </div>

            <Progress
              percent={Math.round(
                (1 - remainingTime / Math.max(1, duration * 60)) * 100
              )}
              showInfo={false}
              strokeColor={isRunning ? (timerMode === 'break' ? 'var(--teal-500)' : 'var(--error)') : 'var(--success)'}
            />

            <div
              style={{ marginTop: 10, display: 'flex', gap: 8, justifyContent: 'center' }}
            >
              {!isRunning && !isPaused && (
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  onClick={handleStartPomodoro}
                >
                  开始
                </Button>
              )}

              {isRunning && (
                <>
                  <Button icon={<PauseCircleOutlined />} onClick={pauseTimer}>
                    暂停
                  </Button>
                  {timerMode === 'break' ? (
                    <Button onClick={() => resetTimer()}>
                      结束休息
                    </Button>
                  ) : (
                    <Button danger onClick={handleAbandonPomodoro}>
                      放弃
                    </Button>
                  )}
                </>
              )}

              {isPaused && (
                <>
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    onClick={resumeTimer}
                  >
                    继续
                  </Button>
                  {timerMode === 'break' ? (
                    <Button onClick={() => resetTimer()}>
                      结束休息
                    </Button>
                  ) : (
                    <>
                      <Button icon={<CheckCircleOutlined />} onClick={handleCompletePomodoro}>
                        完成
                      </Button>
                      <Button danger onClick={handleAbandonPomodoro}>
                        放弃
                      </Button>
                    </>
                  )}
                </>
              )}
            </div>
          </div>
        </Card>
            </div>
          )

          return null
        })}
        </div>
        )}
      </Sider>

      {/* 番茄钟设置弹窗 */}
      <Modal
        title="番茄钟设置"
        open={showPomodoroModal}
        onOk={() => {
          setBreakDuration(pomodoroConfig.breakDuration)
          resetTimer(pomodoroConfig.duration)
          setShowPomodoroModal(false)
          message.success('设置成功')
        }}
        onCancel={() => setShowPomodoroModal(false)}
      >
        <div style={{ marginBottom: 16 }}>
          <label>任务名称</label>
          <Input
            placeholder="例如：学习第一章"
            value={pomodoroConfig.taskName}
            onChange={(e) =>
              setPomodoroConfig({ ...pomodoroConfig, taskName: e.target.value, taskId: null })
            }
            style={{ marginTop: 8 }}
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label>番茄时长（分钟）</label>
          <InputNumber
            min={1}
            max={120}
            value={pomodoroConfig.duration}
            onChange={(value) => {
              if (value !== null && value >= 1) {
                setPomodoroConfig({ ...pomodoroConfig, duration: value })
              }
            }}
            onBlur={(e) => {
              const parsed = parseInt(e.target.value, 10)
              const valid = !isNaN(parsed) && parsed >= 1 ? Math.min(parsed, 120) : pomodoroConfig.duration
              setPomodoroConfig({ ...pomodoroConfig, duration: valid })
            }}
            keyboard
            style={{ marginTop: 8, width: '100%' }}
          />
        </div>
        <div>
          <label>休息时长（分钟）</label>
          <InputNumber
            min={1}
            max={60}
            value={pomodoroConfig.breakDuration}
            onChange={(value) => {
              if (value !== null && value >= 1) {
                setPomodoroConfig({ ...pomodoroConfig, breakDuration: value })
              }
            }}
            onBlur={(e) => {
              const parsed = parseInt(e.target.value, 10)
              const valid = !isNaN(parsed) && parsed >= 1 ? Math.min(parsed, 60) : pomodoroConfig.breakDuration
              setPomodoroConfig({ ...pomodoroConfig, breakDuration: valid })
            }}
            keyboard
            style={{ marginTop: 8, width: '100%' }}
          />
        </div>
      </Modal>

      {/* 番茄钟中断原因选择弹窗 */}
      <Modal
        title="为什么停止番茄钟？"
        open={showStopReasonModal}
        footer={null}
        onCancel={() => setShowStopReasonModal(false)}
        width={420}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '8px 0' }}>
          <Button
            block
            size="large"
            type={selectedStopReason === 'early_done' ? 'primary' : 'default'}
            onClick={() => setSelectedStopReason('early_done')}
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', justifyContent: 'center', textAlign: 'left', height: 'auto', minHeight: 68, padding: '12px 16px', whiteSpace: 'normal' }}
          >
            <div style={{ width: '100%', fontWeight: 600, lineHeight: 1.35 }}>✅ 提前完成了任务</div>
            <div style={{ width: '100%', fontSize: 12, color: 'var(--text-secondary)', fontWeight: 400, lineHeight: 1.45 }}>任务做完了，状态不错</div>
          </Button>
          <Button
            block
            size="large"
            type={selectedStopReason === 'interrupted' ? 'primary' : 'default'}
            onClick={() => setSelectedStopReason('interrupted')}
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', justifyContent: 'center', textAlign: 'left', height: 'auto', minHeight: 68, padding: '12px 16px', whiteSpace: 'normal' }}
          >
            <div style={{ width: '100%', fontWeight: 600, lineHeight: 1.35 }}>📱 临时有事，被打断了</div>
            <div style={{ width: '100%', fontSize: 12, color: 'var(--text-secondary)', fontWeight: 400, lineHeight: 1.45 }}>外部原因，不影响学习评估</div>
          </Button>
          <Button
            block
            size="large"
            type={selectedStopReason === 'distracted' ? 'primary' : 'default'}
            onClick={() => setSelectedStopReason('distracted')}
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', justifyContent: 'center', textAlign: 'left', height: 'auto', minHeight: 68, padding: '12px 16px', whiteSpace: 'normal' }}
          >
            <div style={{ width: '100%', fontWeight: 600, lineHeight: 1.35 }}>😔 状态不好，没学进去</div>
            <div style={{ width: '100%', fontSize: 12, color: 'var(--text-secondary)', fontWeight: 400, lineHeight: 1.45 }}>走神了，AI 会帮你分析改善</div>
          </Button>
          <Button
            block
            type="primary"
            disabled={!selectedStopReason}
            onClick={() => selectedStopReason && handleConfirmStopReason(selectedStopReason)}
            style={{ marginTop: 4 }}
          >
            确认
          </Button>
        </div>
      </Modal>

      {/* 日程计划弹窗 */}
      <Modal
        title={`${selectedDate?.format('YYYY年MM月DD日')} 的计划`}
        open={showPlanModal}
        onOk={savePlan}
        onCancel={() => { setShowPlanModal(false) }}
        width={600}
      >
        {showPlanModal && (
          <Suspense fallback={<Spin />}>
            <MarkdownLiveEditor
              ref={planEditorRef}
              value={currentPlan}
              onChange={setCurrentPlan}
              height="420px"
              placeholder={`输入今日计划或学习记录...\n例如：\n- [ ] 复习第一章\n- [ ] 完成10道练习题\n- [ ] 整理笔记`}
            />
          </Suspense>
        )}
      </Modal>

      {/* 今日激励管理弹窗 */}
      {showMotivationModal && (
        <Suspense fallback={null}>
          <MotivationModal
            open={showMotivationModal}
            onClose={() => setShowMotivationModal(false)}
            allQuotes={allQuotes}
            motivationSettings={motivationSettings}
            setMotivationSettings={setMotivationSettings}
            savingMotivationSettings={savingMotivationSettings}
            newQuoteContent={newQuoteContent}
            setNewQuoteContent={setNewQuoteContent}
            newQuoteAuthor={newQuoteAuthor}
            setNewQuoteAuthor={setNewQuoteAuthor}
            onSaveSettings={handleSaveMotivationSettings}
            onAddQuote={handleAddCustomQuote}
            onDeleteQuote={handleDeleteQuote}
            onPinQuote={handlePinCurrentQuote}
          />
        </Suspense>
      )}

      {/* 番茄钟统计弹窗 - 增强版 */}
      {showStatsModal && (
        <Suspense fallback={null}>
          <StatsModal
            open={showStatsModal}
            onClose={() => setShowStatsModal(false)}
            stats={stats}
            statsRange={statsRange}
            setStatsRange={setStatsRange}
            getCumulativeStats={getCumulativeStats}
            getTaskDistribution={getTaskDistribution}
            weekChartOption={weekChartOption}
          />
        </Suspense>
      )}

      <Modal
        title="引用到笔记"
        open={!!quoteNoteDraft}
        width={720}
        okText="保存到笔记"
        cancelText="取消"
        confirmLoading={!!quoteNoteDraft?.saving}
        onOk={() => void saveQuoteNoteDraft()}
        onCancel={() => {
          if (!quoteNoteDraft?.saving) {
            setQuoteNoteDraft(null)
          }
        }}
        destroyOnHidden
      >
        {quoteNoteDraft && (
          <div style={{ display: 'grid', gap: 14 }}>
            <div>
              <div style={{ marginBottom: 6, fontSize: 12, color: 'var(--text-secondary)' }}>标题</div>
              <Input
                value={quoteNoteDraft.title}
                onChange={(e) =>
                  setQuoteNoteDraft((prev) =>
                    prev ? { ...prev, title: e.target.value, titleEdited: true } : prev
                  )
                }
                placeholder="给这条摘录起一个标题"
              />
            </div>
            <div>
              <div style={{ marginBottom: 6, fontSize: 12, color: 'var(--text-secondary)' }}>标签</div>
              <Select
                mode="tags"
                style={{ width: '100%' }}
                tokenSeparators={[',', '，', ' ']}
                value={quoteNoteDraft.tags}
                onChange={(tags) =>
                  setQuoteNoteDraft((prev) =>
                    prev ? { ...prev, tags, tagsEdited: true } : prev
                  )
                }
                placeholder="可选：添加标签"
              />
            </div>
            <div>
              <div style={{ marginBottom: 6, fontSize: 12, color: 'var(--text-secondary)' }}>内容</div>
              <TextArea
                value={quoteNoteDraft.content}
                onChange={(e) =>
                  setQuoteNoteDraft((prev) =>
                    prev ? { ...prev, content: e.target.value } : prev
                  )
                }
                rows={12}
                placeholder="确认无误后再保存到笔记"
              />
            </div>
            {quoteNoteDraft.metadataLoading && (
              <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                正在后台建议标题和标签，不影响你先编辑内容。
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* 资料预览抽屉 */}
      <Drawer
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <FileOutlined style={{ color: currentMaterial?.file_type === 'pdf' ? '#ff4d4f' : '#b07d3a' }} />
            <span>{currentMaterial?.name || '资料预览'}</span>
          </div>
        }
        placement="right"
        width={700}
        open={previewVisible}
        onClose={() => setPreviewVisible(false)}
        extra={
          <div style={{ color: 'var(--text-tertiary)', fontSize: 12 }}>
            上传时间：{currentMaterial?.uploadTime}
          </div>
        }
      >
        {previewLoading ? (
          <div style={{ textAlign: 'center', padding: '100px 0', color: 'var(--text-tertiary)' }}>
            加载中...
          </div>
        ) : (
          <div>
            {/* 文件信息卡片 */}
            <Card size="small" style={{ marginBottom: 16, background: 'var(--bg-tertiary)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>{currentMaterial?.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 4 }}>
                    类型：{currentMaterial?.file_type?.toUpperCase() || '未知'} ·
                    上传：{currentMaterial?.uploadTime}
                  </div>
                </div>
                <Badge
                  count={currentMaterial?.file_type?.toUpperCase()}
                  style={{
                    backgroundColor: currentMaterial?.file_type === 'pdf' ? '#ff4d4f' : '#b07d3a'
                  }}
                />
              </div>
            </Card>

            {/* 内容预览区 */}
            <Card
              title="📄 内容预览"
              size="small"
              bodyStyle={{
                maxHeight: 'calc(100vh - 280px)',
                overflow: 'auto',
                background: 'var(--bg-tertiary)',
                padding: 16
              }}
            >
              {currentMaterial?.file_type === 'pdf' ? (
                <div>
                  <div style={{
                    padding: '40px',
                    textAlign: 'center',
                    border: '2px dashed var(--border-color)',
                    borderRadius: 'var(--radius-md)',
                    marginBottom: 16
                  }}>
                    <FileOutlined style={{ fontSize: 48, color: '#ff4d4f', marginBottom: 16 }} />
                    <div style={{ color: 'var(--text-secondary)' }}>PDF 文件</div>
                    <div style={{ color: 'var(--text-tertiary)', fontSize: 12, marginTop: 8 }}>
                      {currentMaterial?.name}
                    </div>
                  </div>
                  <div style={{
                    background: 'var(--bg-tertiary)',
                    padding: 16,
                    borderRadius: 'var(--radius-md)',
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.8,
                    fontSize: 14
                  }}>
                    {previewContent || '正在提取PDF文本内容...'}
                  </div>
                </div>
              ) : (
                currentMaterial?.file_type === 'md' ? (
                  <div
                    className="chat-markdown"
                    style={{
                      lineHeight: 1.8,
                      fontSize: 14,
                      background: 'var(--bg-tertiary)',
                      padding: 16,
                      borderRadius: 'var(--radius-md)',
                    }}
                  >
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      skipHtml
                      components={{
                        a(props) {
                          return <a {...props} target="_blank" rel="noreferrer noopener" />
                        },
                      }}
                    >
                      {previewContent || '暂无预览内容'}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <div style={{
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.8,
                    fontSize: 14,
                    background: 'var(--bg-tertiary)',
                    padding: 16,
                    borderRadius: 'var(--radius-md)'
                  }}>
                    {previewContent || '暂无预览内容'}
                  </div>
                )
              )}
            </Card>
          </div>
        )}
      </Drawer>

      <Drawer
        title={activeProjectId ? `项目资料库 · ${projects.find((p) => p.id === activeProjectId)?.name || ''}` : '项目资料库'}
        placement="right"
        width={Math.min(520, window.innerWidth - 40)}
        open={projectMaterialsOpen}
        onClose={() => setProjectMaterialsOpen(false)}
      >
        {!activeProjectId ? (
          <div style={{ color: 'var(--text-secondary)', fontSize: 13 }}>请先选择一个项目</div>
        ) : (
          <div>
            <div style={{ marginBottom: 12 }}>
              <Input.Search
                placeholder="在当前项目中搜索资料"
                value={projectSearchQuery}
                onChange={(e) => setProjectSearchQuery(e.target.value)}
                onSearch={(val) => void handleProjectSearch(val)}
                enterButton="搜索"
                loading={projectSearchLoading}
                allowClear
              />
            </div>
            {projectSearchResults.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <List
                  size="small"
                  dataSource={projectSearchResults}
                  renderItem={(item) => {
                    const material = resolveMaterialById(item.material_id)
                    return (
                      <List.Item
                        actions={material ? [
                          <Button
                            key="preview"
                            type="text"
                            size="small"
                            icon={<FileOutlined />}
                            onClick={() => handlePreview(material)}
                          />,
                        ] : []}
                      >
                        <List.Item.Meta
                          title={
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <span style={{ fontSize: 12, fontWeight: 500 }}>{item.title || `资料 #${item.material_id}`}</span>
                              <Tag color="blue" style={{ fontSize: 10, lineHeight: '16px' }}>
                                {Math.round((item.score || 0) * 100)}%
                              </Tag>
                            </div>
                          }
                          description={
                            <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                              {(item.text || '').slice(0, 120)}{(item.text || '').length > 120 ? '…' : ''}
                            </span>
                          }
                        />
                      </List.Item>
                    )
                  }}
                />
              </div>
            )}
            <div style={{ marginBottom: 12 }}>
              <Upload.Dragger
                multiple
                beforeUpload={handleUpload}
                showUploadList={false}
                accept=".pdf,.docx,.txt,.md"
              >
                <p><UploadOutlined style={{ fontSize: 22, color: 'var(--text-secondary)' }} /></p>
                <p style={{ fontSize: 13, color: 'var(--text-primary)', margin: '6px 0 2px' }}>上传到当前项目</p>
                <p style={{ fontSize: 11, color: '#999' }}>支持 PDF、Word、TXT、Markdown</p>
              </Upload.Dragger>
            </div>
            <List
              size="small"
              dataSource={projectMaterials}
              locale={{ emptyText: '该项目暂无资料' }}
              renderItem={(item) => (
                <List.Item
                  actions={[
                    <Button
                      type="text"
                      size="small"
                      icon={<FileOutlined />}
                      onClick={() => handlePreview(item)}
                      title="预览"
                    />,
                    <Button
                      type="text"
                      size="small"
                      onClick={async () => {
                        if (!activeProjectId) return
                        try {
                          await removeProjectMaterial(activeProjectId, item.id)
                          const detail = await getProject(activeProjectId)
                          setActiveProjectMaterialIds(detail?.material_ids || [])
                          setMaterials((prev) => prev.map((m) => {
                            if (m.id !== item.id) return m
                            const nextIds = (m.project_ids || []).filter((pid) => pid !== activeProjectId)
                            return { ...m, project_ids: nextIds }
                          }))
                          message.success('已从项目移除')
                        } catch {
                          message.error('移除失败')
                        }
                      }}
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      移除
                    </Button>,
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => deleteMaterial(item.id)}
                      title="删除"
                    />,
                  ]}
                  style={{ cursor: 'pointer' }}
                  onClick={() => handlePreview(item)}
                >
                  <List.Item.Meta
                    avatar={<FileOutlined style={{ color: item.file_type === 'pdf' ? '#ff4d4f' : '#b07d3a' }} />}
                    title={
                      <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-primary)' }}>{item.name}</span>
                    }
                    description={
                      <span style={{ fontSize: 10, color: 'var(--text-secondary)' }}>
                        {item.uploadTime} · {item.file_type?.toUpperCase() || 'FILE'}
                      </span>
                    }
                  />
                </List.Item>
              )}
            />
          </div>
        )}
      </Drawer>

      <Modal
        title={agentWriteDraft?.intent === 'create_note' ? '确认创建笔记' : agentWriteDraft?.intent === 'add_daily_plan_items' ? '确认加入当天计划' : '确认创建目标与任务'}
        open={!!agentWriteDraft}
        onCancel={() => {
          setAgentWriteDraft(null)
          setAgentWriteSourceText('')
        }}
        onOk={() => void confirmAgentWrite()}
        confirmLoading={agentWriteExecuting}
        okText="确认写入"
        cancelText="取消"
        width={680}
      >
        {agentWriteDraft && (
          <div>
            <div style={{ marginBottom: 12, color: 'var(--text-secondary)' }}>
              {agentWriteDraft.summary || 'Agent 已生成写入草案，请确认。'}
            </div>
            {(agentWriteDraft.duplicate_warnings || []).length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <Space wrap>
                  {agentWriteDraft.duplicate_warnings?.map((item) => (
                    <Tag key={item} color={item.includes('跳过') ? 'orange' : 'blue'}>{item}</Tag>
                  ))}
                </Space>
              </div>
            )}
            {agentWriteDraft.intent === 'create_note' ? (
              <Space direction="vertical" size={10} style={{ width: '100%' }}>
                <div>
                  <div style={{ marginBottom: 4, fontWeight: 600 }}>标题</div>
                  <Input
                    value={agentWriteDraft.draft.title || ''}
                    placeholder="对话笔记"
                    onChange={event => updateAgentWriteDraft({ title: event.target.value })}
                  />
                </div>
                <Space wrap>
                  <span style={{ fontWeight: 600 }}>类型</span>
                  <Select
                    size="small"
                    value={agentWriteDraft.draft.note_type || 'general'}
                    style={{ width: 120 }}
                    onChange={value => updateAgentWriteDraft({ note_type: value })}
                    options={[
                      { value: 'general', label: '普通' },
                      { value: 'idea', label: '灵感' },
                      { value: 'method', label: '方法' },
                      { value: 'summary', label: '总结' },
                      { value: 'question', label: '问题' },
                      { value: 'resource', label: '资料' },
                    ]}
                  />
                  <span style={{ fontWeight: 600 }}>标签</span>
                  <Select
                    mode="tags"
                    size="small"
                    value={(agentWriteDraft.draft.tags || []) as string[]}
                    style={{ minWidth: 260, flex: 1 }}
                    maxTagCount="responsive"
                    tokenSeparators={[',', '，', ' ']}
                    onChange={tags => updateAgentWriteDraft({ tags: tags.slice(0, 6) })}
                    placeholder="输入标签后回车"
                  />
                </Space>
                <div>
                  <div style={{ marginBottom: 4, fontWeight: 600 }}>内容</div>
                  <TextArea
                    value={agentWriteDraft.draft.content || ''}
                    autoSize={{ minRows: 5, maxRows: 10 }}
                    onChange={event => updateAgentWriteDraft({ content: event.target.value })}
                  />
                </div>
              </Space>
            ) : agentWriteDraft.intent === 'add_daily_plan_items' ? (
              <Space direction="vertical" size={10} style={{ width: '100%' }}>
                <Space wrap>
                  <strong>日期</strong>
                  <DatePicker
                    size="small"
                    value={agentWriteDraft.draft.date ? dayjs(agentWriteDraft.draft.date) : undefined}
                    onChange={value => updateAgentWriteDraft({ date: value ? value.format('YYYY-MM-DD') : undefined })}
                  />
                  {agentWriteDraft.draft.existing_plan_id && <Tag color="blue">追加到已有计划</Tag>}
                </Space>
                <List
                  size="small"
                  bordered
                  dataSource={(agentWriteDraft.draft.items || []) as AgentWriteTaskDraftItem[]}
                  locale={{ emptyText: '暂无计划项' }}
                  renderItem={(item, index) => (
                    <List.Item actions={[<Button key="remove" size="small" type="link" danger onClick={() => removeAgentWriteListItem('items', index)}>删除</Button>]}>
                      <Space direction="vertical" size={6} style={{ width: '100%' }}>
                        <Input
                          size="small"
                          value={item.title || ''}
                          placeholder="计划项标题"
                          status={item.duplicate ? 'warning' : undefined}
                          onChange={event => updateAgentWriteListItem('items', index, { title: event.target.value })}
                        />
                        <Space wrap>
                          <Select
                            size="small"
                            value={item.task_type || 'learn'}
                            style={{ width: 110 }}
                            onChange={value => updateAgentWriteListItem('items', index, { task_type: value })}
                            options={[
                              { value: 'learn', label: '学习' },
                              { value: 'review', label: '复习' },
                              { value: 'practice', label: '练习' },
                              { value: 'summarize', label: '总结' },
                            ]}
                          />
                          <DatePicker
                            size="small"
                            value={item.planned_date ? dayjs(item.planned_date) : agentWriteDraft.draft.date ? dayjs(agentWriteDraft.draft.date) : undefined}
                            onChange={value => updateAgentWriteListItem('items', index, { planned_date: value ? value.format('YYYY-MM-DD') : undefined })}
                          />
                          {item.duplicate && <Tag color="orange">疑似重复，编辑后可继续写入</Tag>}
                        </Space>
                      </Space>
                    </List.Item>
                  )}
                />
              </Space>
            ) : (
              <Space direction="vertical" size={10} style={{ width: '100%' }}>
                <div>
                  <div style={{ marginBottom: 4, fontWeight: 600 }}>目标</div>
                  <Input
                    value={agentWriteDraft.draft.goal_title || ''}
                    placeholder="学习目标"
                    onChange={event => updateAgentWriteDraft({ goal_title: event.target.value })}
                  />
                  {agentWriteDraft.draft.existing_goal_id && <Tag color="blue" style={{ marginTop: 6 }}>复用已有目标</Tag>}
                </div>
                <List
                  size="small"
                  bordered
                  dataSource={(agentWriteDraft.draft.tasks || []) as AgentWriteTaskDraftItem[]}
                  locale={{ emptyText: '暂无任务' }}
                  renderItem={(item, index) => (
                    <List.Item actions={[<Button key="remove" size="small" type="link" danger onClick={() => removeAgentWriteListItem('tasks', index)}>删除</Button>]}>
                      <Space direction="vertical" size={6} style={{ width: '100%' }}>
                        <Input
                          size="small"
                          value={item.title || ''}
                          placeholder="任务标题"
                          status={item.duplicate ? 'warning' : undefined}
                          onChange={event => updateAgentWriteListItem('tasks', index, { title: event.target.value })}
                        />
                        <Space wrap>
                          <Select
                            size="small"
                            value={item.task_type || 'learn'}
                            style={{ width: 110 }}
                            onChange={value => updateAgentWriteListItem('tasks', index, { task_type: value })}
                            options={[
                              { value: 'learn', label: '学习' },
                              { value: 'review', label: '复习' },
                              { value: 'practice', label: '练习' },
                              { value: 'summarize', label: '总结' },
                            ]}
                          />
                          <DatePicker
                            size="small"
                            value={item.planned_date ? dayjs(item.planned_date) : undefined}
                            onChange={value => updateAgentWriteListItem('tasks', index, { planned_date: value ? value.format('YYYY-MM-DD') : undefined })}
                          />
                          {item.duplicate && <Tag color="orange">疑似重复，编辑后可继续写入</Tag>}
                        </Space>
                      </Space>
                    </List.Item>
                  )}
                />
              </Space>
            )}
          </div>
        )}
      </Modal>

      <OnboardingModal
        open={showOnboarding}
        status={onboardingStatus}
        seedLoading={demoSeedLoading}
        onClose={closeOnboarding}
        onSeedDemo={handleSeedDemo}
        onNavigate={(path) => {
          setShowOnboarding(false)
          navigate(path)
        }}
        onOpenMaterials={openOnboardingMaterials}
      />
      <SettingsModal open={showSettings} onClose={() => setShowSettings(false)} />
      <ProjectSettingsModal
        open={projectSettingsOpen}
        projectId={editingProjectId}
        onClose={() => {
          setProjectSettingsOpen(false)
          setEditingProjectId(undefined)
        }}
      />
    </Layout>
  )
}
