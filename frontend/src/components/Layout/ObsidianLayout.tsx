import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Layout,
  Card,
  List,
  Button,
  Input,
  InputNumber,
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
  Collapse,
  Spin,
  Tooltip,
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
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PictureOutlined,
  CloseCircleFilled,
  LogoutOutlined,
  UserOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { usePomodoroStore, type DateRange } from '../../stores/pomodoroStore'
import * as pomodoroApi from '../../services/pomodoroApi'
import { AISettingsDrawer } from '../AISettingsDrawer'
import { sendMessageStream, type ChatMessage, type DetectedMaterial, type MemoryIndicator, type ProgressFeedback } from '../../services/chatApi'
import { ChatMessageBubble } from '../ChatMessageBubble'
import { ConversationSidebar } from '../ConversationSidebar'
import { ProjectSettingsModal } from '../ProjectSettingsModal'
import { useChatStore } from '../../stores/chatStore'
import { getProject, archiveUnassignedMaterials, addProjectMaterial, removeProjectMaterial } from '../../services/conversationApi'
import { listWrongQuestions } from '../../services/wrongQuestionApi'
import { useAuthStore } from '../../stores/authStore'
import { listReviewTasks, getDueReviewCount, type ReviewTaskItem } from '../../services/reviewApi'
import { createNote, suggestNoteMetadata } from '../../services/noteApi'
import { getDashboard, startLearningPipeline, startBatchLearningPipeline, generateDailyPlan, type DashboardData } from '../../services/learningApi'
import {
  getCurrentQuote,
  listQuotes,
  addCustomQuote,
  deleteQuote,
  generateAIQuote,
  getMotivationSettings,
  updateMotivationSettings,
  type MotivationQuote,
  type MotivationSettings,
} from '../../services/motivationApi'
import { apiFetch } from '../../services/apiClient'
import { SyncStatusIndicator } from '../SyncStatusIndicator'
import { TodayFocusActions } from './TodayFocusActions'

const { Sider, Content } = Layout
const { TextArea } = Input

const QUOTE_SORT_OPTIONS = [
  { label: '最新优先', value: 'created_desc' },
  { label: '最早优先', value: 'created_asc' },
  { label: '来源优先（自定义→AI→预设）', value: 'source_priority' },
  { label: '作者 A→Z', value: 'author_asc' },
  { label: '内容 A→Z', value: 'content_asc' },
]

const QUOTE_ROTATION_OPTIONS = [
  { label: '30分钟', value: 30 * 60 },
  { label: '1小时', value: 60 * 60 },
  { label: '3小时', value: 3 * 60 * 60 },
  { label: '6小时', value: 6 * 60 * 60 },
  { label: '12小时', value: 12 * 60 * 60 },
  { label: '1天', value: 24 * 60 * 60 },
]

interface PomodoroConfig {
  duration: number
  taskName: string
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

interface DailyPlan {
  date: string
  content: string
}

interface WrongQuestionPreview {
  id: number
  content: string
  mastery_status: 'not_mastered' | 'partial' | 'mastered'
}

export function ObsidianLayout() {
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()
  // 使用zustand store管理番茄钟
  const {
    isRunning,
    isPaused,
    remainingTime,
    currentTask,
    duration,
    startTimer,
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
    taskName: '',
  })
  const [showPomodoroModal, setShowPomodoroModal] = useState(false)
  const [showStopReasonModal, setShowStopReasonModal] = useState(false)
  const [selectedStopReason, setSelectedStopReason] = useState<'early_done' | 'interrupted' | 'distracted' | null>(null)
  const [showStatsModal, setShowStatsModal] = useState(false)
  const [focusMode, setFocusMode] = useState(true)
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
  const [ragStatus, setRagStatus] = useState<{
    enabled: boolean
    rag_online: boolean
    total_chunks: number
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
  const [weeklyPlans, setWeeklyPlans] = useState<DailyPlan[]>([])
  const [showAISettings, setShowAISettings] = useState(false)
  const [motivationQuote, setMotivationQuote] = useState<MotivationQuote | null>(null)
  const [refreshOffset, setRefreshOffset] = useState(0)
  const [aiGenerating, setAiGenerating] = useState(false)
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

  // Chat store
  const {
    projects,
    messages: chatMessages,
    streamingContent,
    isStreaming: chatLoading,
    activeConversationId,
    activeProjectId,
    addMessage,
    setStreamingContent,
    setIsStreaming: setChatLoading,
    clearMessages,
    loadProjects,
    loadConversations,
    createNewConversation,
    setActiveConversation,
  } = useChatStore()

  const [chatInput, setChatInput] = useState('')
  const [selectedMaterialIds, setSelectedMaterialIds] = useState<Set<number>>(new Set())
  const [detectedMaterials, setDetectedMaterials] = useState<DetectedMaterial[]>([])
  const [autoScrollEnabled, setAutoScrollEnabled] = useState(true)
  const chatScrollRef = useRef<HTMLDivElement>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  // Image upload state
  const [pendingImages, setPendingImages] = useState<string[]>([])
  const imageInputRef = useRef<HTMLInputElement>(null)

  // Project settings modal
  const [projectSettingsOpen, setProjectSettingsOpen] = useState(false)
  const [editingProjectId, setEditingProjectId] = useState<number | undefined>()
  const [leftSidebarTab, setLeftSidebarTab] = useState<string>('conversations')
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [leftExpandTarget, setLeftExpandTarget] = useState<'default' | 'search' | 'categories' | 'history' | null>(null)
  const [projectMaterialsOpen, setProjectMaterialsOpen] = useState(false)

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
  const [activeProjectMaterialIds, setActiveProjectMaterialIds] = useState<number[]>([])
  const [wrongQuestions, setWrongQuestions] = useState<WrongQuestionPreview[]>([])
  const [reviewDueCount, setReviewDueCount] = useState(0)
  const [reviewPreviewTasks, setReviewPreviewTasks] = useState<ReviewTaskItem[]>([])
  const [dashboardData, setDashboardData] = useState<DashboardData | null>(null)

  const topPendingTask = useMemo(
    () => (dashboardData?.today_tasks || []).find((task) => task.status !== 'completed'),
    [dashboardData],
  )

  // Backend readiness polling (Feature 1)
  const [backendReady, setBackendReady] = useState(false)

  // Plan checklist view mode (Feature 3)
  const [planViewMode, setPlanViewMode] = useState<'edit' | 'checklist'>('edit')

  // Coach mode (Feature 5)
  const [chatMode, setChatMode] = useState<'normal' | 'coach'>('normal')

  // Memory indicators (Feature 2)
  const [memoryIndicators, setMemoryIndicators] = useState<MemoryIndicator[]>([])

  // Progress feedback (achievement card)
  const [progressFeedback, setProgressFeedback] = useState<ProgressFeedback | null>(null)
  // Start learning loading state (Feature 1)
  const [startLearningLoadingId, setStartLearningLoadingId] = useState<number | null>(null)
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
      const res = await apiFetch('/api/materials/?skip=0&limit=100')
      if (res.ok) {
        const arr = await res.json()
        const mapped: Material[] = (arr || []).map((m: any) => ({
          id: m.id,
          name: m.title,
          uploadTime: (m.created_at || '').slice(0, 10) || dayjs().format('YYYY-MM-DD'),
          file_type: m.file_type,
          file_path: m.file_path,
          project_ids: m.project_ids || [],
        }))
        setMaterials(mapped.reverse())
      }
    } catch {
      // backend may not be ready yet
    } finally {
      setMaterialsLoading(false)
    }
  }, [])

  const loadCurrentQuote = useCallback(async (offset?: number) => {
    const res = await getCurrentQuote(offset ?? refreshOffset)
    if (res) setMotivationQuote(res)
  }, [refreshOffset])

  const loadAllQuotes = useCallback(async (sortMode?: string) => {
    const list = await listQuotes(undefined, sortMode ?? motivationSettings.sort_mode)
    setAllQuotes(list)
  }, [motivationSettings.sort_mode])

  const loadMotivationSettings = useCallback(async () => {
    const data = await getMotivationSettings()
    if (data) {
      setMotivationSettings(data)
      return data
    }
    return null
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
      const res = await apiFetch(`/api/materials/search?query=${encodeURIComponent(q)}&project_id=${activeProjectId}`)
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(err?.detail || '搜索失败')
      }
      const data = await res.json()
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

  const handleGenerateAIQuote = async () => {
    setAiGenerating(true)
    try {
      const created = await generateAIQuote()
      if (!created) {
        message.error('生成失败，请稍后重试')
        return
      }
      setMotivationQuote(created)
      await loadAllQuotes()
      message.success('已生成新的激励语录')
    } finally {
      setAiGenerating(false)
    }
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

  useEffect(() => {
    if (leftCollapsed && leftSidebarTab !== 'conversations') {
      setLeftSidebarTab('conversations')
    }
  }, [leftCollapsed, leftSidebarTab])

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

  // Once backend is ready, load ALL data
  useEffect(() => {
    if (!backendReady) return
    const loadAll = async () => {
      await loadMaterials()
      await loadProjects()
      await loadConversations()
      if (activeConversationId) {
        setActiveConversation(activeConversationId)
      }
      try {
        const ragRes = await fetch('/api/rag/health')
        if (ragRes.ok) {
          const j = await ragRes.json()
          setRagStatus(j)
        }
      } catch {
        // ignore
      }
      await loadWeeklyPlans()
      await loadWrongQuestions()
      await loadReviewOverview()
      await loadDashboardOverview()
      // Sync pomodoro data
      await syncPendingRecords()
    }
    loadAll()
  }, [backendReady])

  useEffect(() => {
    if (!backendReady) return
    void loadCurrentQuote()
    void loadMotivationSettings()
    void loadAllQuotes()
    const interval = setInterval(() => {
      void loadCurrentQuote()
    }, 5 * 60 * 1000)
    return () => clearInterval(interval)
  }, [backendReady, loadAllQuotes, loadCurrentQuote, loadMotivationSettings])

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
    if (!activeProjectId) {
      setActiveProjectMaterialIds([])
      return
    }
    ; (async () => {
      const detail = await getProject(activeProjectId)
      setActiveProjectMaterialIds(detail?.material_ids || [])
    })()
  }, [activeProjectId, projectSettingsOpen])

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

  const handleSendMessage = async (forcedText?: string) => {
    const text = (forcedText ?? chatInput).trim()
    if (!text || chatLoading) return

    // Auto-create conversation if none active
    let convId = activeConversationId
    if (!convId) {
      const conv = await createNewConversation(activeProjectId)
      if (!conv) {
        message.error('创建对话失败')
        return
      }
      convId = conv.id
    }

    const userMsg: ChatMessage = { role: 'user', content: text }
    addMessage(userMsg)
    if (!forcedText) setChatInput('')
    setPendingImages([])
    setAutoScrollEnabled(true)
    setChatLoading(true)
    setStreamingContent('')
    setDetectedMaterials([])
    setProgressFeedback(null)
    let accumulated = ''
    const controller = new AbortController()
    abortControllerRef.current = controller

    await sendMessageStream(
      text,
      chatMessages,
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
        loadConversations()
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
      pendingImages.length > 0 ? pendingImages : undefined,
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
        setProgressFeedback(feedback)
        setTimeout(() => setProgressFeedback(null), 6000)
      },
    )
  }

  // 停止生成
  const handleStopStreaming = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
  }, [])

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
        const newWidth = Math.min(480, Math.max(180, e.clientX))
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
    } catch {
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

  // ---- Feature 3: Plan task helpers ----
  const parsePlanLines = (text: string) => {
    return text.split('\n').map((line, index) => {
      const unchecked = /^- \[ \] (.*)/.exec(line)
      const checked = /^- \[x\] (.*)/.exec(line)
      if (unchecked) return { index, type: 'task' as const, checked: false, label: unchecked[1], raw: line }
      if (checked) return { index, type: 'task' as const, checked: true, label: checked[1], raw: line }
      return { index, type: 'text' as const, checked: false, label: line, raw: line }
    })
  }

  const toggleTaskLine = (text: string, lineIndex: number): string => {
    const lines = text.split('\n')
    const line = lines[lineIndex]
    if (!line) return text
    if (/^- \[ \] /.test(line)) {
      lines[lineIndex] = line.replace('- [ ] ', '- [x] ')
    } else if (/^- \[x\] /.test(line)) {
      lines[lineIndex] = line.replace('- [x] ', '- [ ] ')
    }
    return lines.join('\n')
  }

  const getCompletionStats = (text: string): { completed: number; total: number } => {
    const lines = text.split('\n')
    let total = 0
    let completed = 0
    for (const line of lines) {
      if (/^- \[ \] /.test(line)) { total++ }
      else if (/^- \[x\] /.test(line)) { total++; completed++ }
    }
    return { completed, total }
  }

  useEffect(() => {
    const onFocus = () => {
      if (!backendReady) return
      // 重新加载所有关键数据
      void loadMaterials()
      void loadProjects()
      void loadConversations()
      void loadWrongQuestions()
      void loadReviewOverview()
      void loadDashboardOverview()
    }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [loadMaterials, loadProjects, loadConversations, backendReady])

  const handleChatScroll = () => {
    const el = chatScrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    setAutoScrollEnabled(nearBottom)
  }

  const quoteAssistantToNote = async (assistantContent: string) => {
    const lastUserText = (() => {
      for (let i = chatMessages.length - 1; i >= 0; i -= 1) {
        if (chatMessages[i].role === 'user') return chatMessages[i].content
      }
      return ''
    })()

    const body = `## AI 回答摘录\n\n${assistantContent}\n`
    const suggested = await suggestNoteMetadata(assistantContent, lastUserText)
    const title = suggested?.title || `对话摘录 ${dayjs().format('MM-DD HH:mm')}`
    const tags = (suggested?.tags || []).slice(0, 5)
    const links: Array<{ link_type: string; link_id: number }> = []
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

    const created = await createNote({
      title,
      content: body,
      note_type: 'summary',
      tags,
      links,
    })
    if (created) {
      message.success('已引用到笔记')
    } else {
      message.error('创建笔记失败')
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
    startTimer(pomodoroConfig.taskName, pomodoroConfig.duration)
  }

  const handleCompletePomodoro = () => {
    completeTimer()
    message.success('番茄钟完成！已记录到统计中')
  }

  const handleAbandonPomodoro = () => {
    setSelectedStopReason(null)
    setShowStopReasonModal(true)
  }

  const handleConfirmStopReason = async (reason: 'early_done' | 'interrupted' | 'distracted') => {
    const { currentBackendId, duration, startedAt, pausedTotalMs } = usePomodoroStore.getState()
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

  const handleStartFocusFromToday = () => {
    if (!pomodoroConfig.taskName && topPendingTask?.title) {
      setPomodoroConfig((prev) => ({ ...prev, taskName: topPendingTask.title }))
      startTimer(topPendingTask.title, pomodoroConfig.duration)
      return
    }
    handleStartPomodoro()
  }

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
      const res = await apiFetch(`/api/materials/${id}`, { method: 'DELETE' })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(err?.detail || '删除失败')
      }

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
      const res = await apiFetch(`/api/plans/?start=${startStr}&end=${endStr}`)
      if (res.ok) {
        const arr = await res.json()
        const list: DailyPlan[] = (arr || []).map((p: any) => ({ date: p.date, content: p.content || '' }))
        setWeeklyPlans(list)
        // 合并到缓存，使日历上的小绿点即时显示
        setDailyPlans((prev) => {
          const next = { ...prev }
          for (const p of list) next[p.date] = p.content
          return next
        })
      }
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
          const res = await apiFetch(`/api/plans/${dateStr}`)
          if (res.ok) {
            const j = await res.json()
            setCurrentPlan(j.content || '')
            setDailyPlans((prev) => ({ ...prev, [dateStr]: j.content || '' }))
          } else {
            setCurrentPlan(dailyPlans[dateStr] || '')
          }
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
            const res = await apiFetch(`/api/plans/${dateStr}`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ content: currentPlan }),
            })
            if (!res.ok) {
              const err = await res.json().catch(() => null)
              throw new Error(err?.detail || '保存失败')
            }
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

  const dateCellRender = (value: Dayjs) => {
    const dateStr = value.format('YYYY-MM-DD')
    const hasPlan = dailyPlans[dateStr]
    return hasPlan ? (
      <Badge status="success" text="" />
    ) : null
  }

  // Feature 1: Show loading overlay while waiting for backend
  if (!backendReady) {
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        background: '#faf6f0',
        gap: 16,
      }}>
        <Spin size="large" />
        <div style={{ color: 'var(--text-secondary)', fontSize: 16 }}>正在等待后端服务启动...</div>
        <div style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>后端服务就绪后将自动加载数据</div>
      </div>
    )
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* 左侧边栏 */}
      <Sider
        width={effectiveLeftWidth}
        style={{
          background: 'var(--bg-secondary)',
          borderRight: '1px solid #ede4d9',
          overflow: 'hidden',
          height: '100vh',
          position: 'fixed',
          left: 0,
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
                  <div style={{ height: 'calc(100vh - 46px)', overflow: 'auto', background: '#faf5ed' }}>
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
                <div style={{ height: 'calc(100vh - 46px)', overflow: 'auto', background: '#faf5ed' }}>
                  {/* 资料 */}
                  <div style={{ padding: '16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                      <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                        <FileOutlined /> 资料
                      </h3>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
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
                        <Segmented
                          size="small"
                          value={activeProjectId && projectMaterialsOnly ? 'project' : 'all'}
                          onChange={(val) => setProjectMaterialsOnly(val === 'project')}
                          options={[
                            { label: '当前项目资料', value: 'project', disabled: !activeProjectId },
                            { label: '全部资料库', value: 'all' },
                          ]}
                        />
                        <Select
                          size="small"
                          value={materialTypeFilter}
                          onChange={setMaterialTypeFilter}
                          options={materialTypeOptions}
                          style={{ minWidth: 110 }}
                        />
                        <Input
                          size="small"
                          placeholder="搜索资料..."
                          value={materialSearch}
                          onChange={(e) => setMaterialSearch(e.target.value)}
                          style={{ width: 140 }}
                          allowClear
                        />
                        <Button
                          type="text"
                          size="small"
                          loading={archiveMaterialsLoading}
                          onClick={async () => {
                            setArchiveMaterialsLoading(true)
                            try {
                              const result = await archiveUnassignedMaterials()
                              if (!result) {
                                message.error('归档失败')
                                return
                              }
                              if (result.added_count > 0) {
                                message.success(`已归档 ${result.added_count} 份资料到 ${result.project_name}`)
                              } else {
                                message.info('暂无未分类资料')
                              }
                              if (activeProjectId === result.project_id) {
                                const detail = await getProject(result.project_id)
                                setActiveProjectMaterialIds(detail?.material_ids || [])
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
                        return (
                          <List.Item
                            actions={[
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
                                style={{ color: '#52c41a', fontSize: 11 }}
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
                            ]}
                            style={{
                              cursor: 'pointer',
                              padding: '6px 10px',
                              background: selectedMaterialIds.has(item.id) ? 'var(--accent-50)' : 'transparent',
                              borderLeft: selectedMaterialIds.has(item.id) ? '3px solid var(--accent-600)' : '3px solid transparent',
                            }}
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

                  <div style={{ padding: '0 16px 16px', borderTop: '1px solid var(--border-color)' }}>
                    <Collapse
                      size="small"
                      ghost
                      items={[
                        {
                          key: 'upload',
                          label: '导入资料',
                          children: (
                            <div style={{ padding: '8px 0' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                                <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>同步到 RAG 知识库</span>
                                <Switch size="small" checked={syncToRAG} onChange={setSyncToRAG} />
                              </div>
                              {ragStatus && (
                                <div style={{ marginBottom: 8 }}>
                                  <Tag color={ragStatus.enabled && ragStatus.rag_online ? 'green' : 'default'}>
                                    RAG 知识库: {ragStatus.rag_online ? '在线' : '离线'}
                                  </Tag>
                                  {ragStatus.rag_online && (
                                    <Tag color="blue">
                                      {ragStatus.total_chunks} chunks
                                    </Tag>
                                  )}
                                </div>
                              )}
                              <Upload.Dragger
                                multiple
                                beforeUpload={handleUpload}
                                showUploadList={false}
                                accept=".pdf,.doc,.docx,.txt,.md,.epub"
                              >
                                <p><UploadOutlined style={{ fontSize: 24, color: 'var(--text-secondary)' }} /></p>
                                <p style={{ fontSize: 13, color: 'var(--text-primary)', margin: '8px 0 4px' }}>点击或拖拽文件到此处上传</p>
                                <p style={{ fontSize: 11, color: '#999' }}>支持 PDF、Word、TXT、Markdown、EPUB</p>
                              </Upload.Dragger>
                            </div>
                          ),
                        },
                        {
                          key: 'wrong-questions',
                          label: '错题本',
                          children: (
                            <List
                              size="small"
                              dataSource={wrongQuestions}
                              locale={{ emptyText: '暂无错题，去错题本添加' }}
                              renderItem={(item) => (
                                <List.Item style={{ cursor: 'pointer' }} onClick={() => navigate('/wrong-questions')}>
                                  <List.Item.Meta
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
                                        {item.content}
                                      </span>
                                    }
                                    description={
                                      <span style={{ fontSize: 10, color: 'var(--text-secondary)' }}>
                                        {item.mastery_status === 'mastered' ? '已掌握' : item.mastery_status === 'partial' ? '部分掌握' : '未掌握'}
                                      </span>
                                    }
                                  />
                                </List.Item>
                              )}
                            />
                          ),
                        },
                        {
                          key: 'weekly-plans',
                          label: '本周计划',
                          children: (
                            <List
                              size="small"
                              dataSource={weeklyPlans}
                              locale={{ emptyText: '本周暂无计划（在右侧日历中添加）' }}
                              renderItem={(p) => {
                                const planStats = getCompletionStats(p.content || '')
                                return (
                                  <List.Item style={{ padding: '6px 0' }}>
                                    <div style={{ width: '100%' }}>
                                      <div style={{ fontSize: 11, color: 'var(--text-secondary)', fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6 }}>
                                        {p.date}
                                        {planStats.total > 0 && (
                                          <Tag
                                            color={planStats.completed === planStats.total ? 'green' : 'blue'}
                                            style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}
                                          >
                                            {planStats.completed}/{planStats.total}
                                          </Tag>
                                        )}
                                      </div>
                                      <div
                                        style={{
                                          fontSize: 11,
                                          color: 'var(--text-secondary)',
                                          whiteSpace: 'nowrap',
                                          overflow: 'hidden',
                                          textOverflow: 'ellipsis',
                                        }}
                                      >
                                        {(p.content || '').split('\n')[0] || '（空）'}
                                      </div>
                                    </div>
                                  </List.Item>
                                )
                              }}
                            />
                          ),
                        },
                      ]}
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

      {/* 左侧拖拽分割线 */}
      {!leftCollapsed && (
        <div
          className={`panel-splitter${dragging === 'left' ? ' active' : ''}`}
          style={{
            position: 'fixed',
            left: effectiveLeftWidth - 3,
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
      <Layout style={{ marginLeft: effectiveLeftWidth, marginRight: rightWidth, background: 'var(--bg-primary)' }}>
        <Content style={{ padding: '0', background: 'var(--bg-primary)', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
          <div style={{ maxWidth: 860, margin: '0 auto', width: '100%', padding: '0 24px', display: 'flex', flexDirection: 'column', flex: 1 }}>
            {/* Top toolbar - clean and minimal */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '14px 0 10px',
              borderBottom: '1px solid var(--border-light)',
              marginBottom: 4,
              flexWrap: 'wrap',
            }}>
              <Button
                type="text"
                size="small"
                icon={leftCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                onClick={() => {
                  if (leftCollapsed) {
                    setLeftCollapsed(false)
                    return
                  }
                  setLeftExpandTarget(null)
                  setLeftCollapsed(true)
                }}
                style={{ color: 'var(--text-tertiary)' }}
              />
              <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>AI 学习助手</span>
              <div style={{ flex: 1 }} />

              {/* Mode toggle */}
              <Segmented
                size="small"
                value={focusMode ? 'focus' : 'full'}
                onChange={(v) => setFocusMode(v === 'focus')}
                options={[
                  { label: '全量', value: 'full' },
                  { label: '聚焦', value: 'focus' },
                ]}
                style={{ borderRadius: 'var(--radius-sm)' }}
              />

              {/* Quick nav buttons */}
              <div style={{ display: 'flex', gap: 4 }}>
                <Badge count={reviewDueCount} size="small" offset={[-4, 0]}>
                  <Button size="small" type="text" onClick={() => navigate('/review')} style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                    复习
                  </Button>
                </Badge>
                <Button size="small" type="text" onClick={() => navigate('/goals')} style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                  任务
                </Button>
                <Button size="small" type="text" onClick={() => navigate('/wrong-questions')} style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                  错题
                </Button>
                {!focusMode && (
                  <>
                    <Button size="small" type="text" onClick={() => navigate('/notes')} style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                      笔记
                    </Button>
                    <Button size="small" type="text" onClick={() => navigate('/dashboard')} style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                      驾驶舱
                    </Button>
                    <Button size="small" type="text" onClick={() => navigate('/profile')} style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                      我的画像
                    </Button>
                    <Button size="small" type="text" onClick={() => navigate('/prompts')} style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                      Prompt
                    </Button>
                  </>
                )}
              </div>

              <Button
                type="text"
                icon={<SettingOutlined />}
                onClick={() => setShowAISettings(true)}
                style={{ color: 'var(--text-tertiary)' }}
                title="AI 提供商设置"
              />
            </div>
            <TodayFocusActions
              todayTaskCount={dashboardData?.today_task_count || 0}
              pendingCount={dashboardData?.today_pending_count || 0}
              dueReviewCount={reviewDueCount}
              studyMinutes={dashboardData?.today_study_minutes || 0}
              onOpenGoals={() => navigate('/goals')}
              onOpenReview={() => navigate('/review')}
              onStartFocus={handleStartFocusFromToday}
              onOpenFeynman={() => {
                navigate('/goals')
                message.info('请在任务中点击“评估输出”，完成今日费曼复盘')
              }}
            />

            {!focusMode && <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, marginBottom: 8, padding: '6px 0' }}>
              <Tag style={{ fontSize: 11, borderRadius: 'var(--radius-sm)' }}>{activeConversationId ? `对话 #${activeConversationId}` : '未选择对话'}</Tag>
              <Tag color={activeProjectId ? 'blue' : 'default'} style={{ fontSize: 11, borderRadius: 'var(--radius-sm)' }}>{activeProjectId ? `项目 #${activeProjectId}` : '未分配项目'}</Tag>
              {chatLoading && <Tag color="orange" style={{ fontSize: 11, borderRadius: 'var(--radius-sm)' }}>正在生成</Tag>}
              {chatMode === 'coach' && <Tag color="purple" style={{ fontSize: 11, borderRadius: 'var(--radius-sm)' }}>教练模式</Tag>}
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
              <div style={{ marginBottom: 8, padding: '8px 10px', border: '1px solid #f0e8dd', borderRadius: 8, background: '#faf6f0' }}>
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
                background: '#fef9ef',
                borderRadius: 6,
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

            {/* 对话区域 */}
            <div
              ref={chatScrollRef}
              style={{
                flex: 1,
                minHeight: 400,
                maxHeight: 'calc(100vh - 300px)',
                marginTop: 8,
                padding: '20px 8px',
                background: 'var(--bg-primary)',
                borderRadius: 'var(--radius-xl)',
                overflowY: 'auto',
              }}
              onScroll={handleChatScroll}
            >
              {chatLoading && (
                <div style={{ position: 'sticky', top: 0, zIndex: 2, background: 'var(--bg-primary)', paddingBottom: 8, marginBottom: 8, borderBottom: '1px dashed var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent-500)', animation: 'pulse 1.5s infinite' }} />
                    AI 正在回答中...
                  </span>
                  <Button size="small" danger onClick={handleStopStreaming} style={{ borderRadius: 'var(--radius-sm)' }}>停止</Button>
                </div>
              )}
              {chatMessages.length === 0 && !streamingContent ? (
                <div style={{ textAlign: 'center', color: 'var(--text-tertiary)', padding: '80px 20px' }}>
                  <div style={{
                    width: 64,
                    height: 64,
                    borderRadius: 'var(--radius-xl)',
                    background: 'linear-gradient(135deg, var(--accent-100), var(--primary-100))',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    margin: '0 auto 20px',
                    fontSize: 28,
                  }}>
                    🎓
                  </div>
                  <p style={{ fontSize: 17, color: 'var(--text-primary)', marginBottom: 8, fontWeight: 500 }}>
                    准备好继续学习了吗？
                  </p>
                  <p style={{ fontSize: 13.5, color: 'var(--text-tertiary)', maxWidth: 320, margin: '0 auto' }}>
                    勾选左侧资料，或直接提问，我随时在这里陪你学习
                  </p>
                </div>
              ) : (
                <div>
                  {chatMessages.map((msg, idx) => (
                    <ChatMessageBubble
                      key={idx}
                      role={msg.role}
                      content={msg.content}
                      imageData={msg.image_data}
                      onQuoteToNote={quoteAssistantToNote}
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
              )}
            </div>

            {/* 输入区域 */}
            <div style={{ marginTop: 12, position: 'sticky', bottom: 12, paddingBottom: 8 }}>
              {/* Memory indicators banner */}
              {!focusMode && memoryIndicators.length > 0 && (
                <div style={{
                  padding: '6px 12px',
                  marginBottom: 6,
                  background: 'linear-gradient(90deg, #fef9ef, #fdf2e9)',
                  borderRadius: 8,
                  fontSize: 12,
                  color: '#6b5b48',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  flexWrap: 'wrap',
                }}>
                  <span style={{ color: 'var(--text-tertiary)', flexShrink: 0 }}>AI 记忆：</span>
                  {memoryIndicators.slice(0, 4).map((m) => (
                    <Tag key={m.id} color={
                      m.category === 'weakness' ? 'orange'
                        : m.category === 'goal' ? 'gold'
                        : m.category === 'confusion' ? 'volcano'
                        : m.category === 'misconception' ? 'red'
                        : m.memory_type === 'episodic' ? 'cyan'
                        : 'default'
                    } style={{ fontSize: 11 }}>
                      {m.value.length > 20 ? m.value.slice(0, 20) + '...' : m.value}
                    </Tag>
                  ))}
                </div>
              )}
              {/* Progress feedback achievement card */}
              {!focusMode && progressFeedback && (
                <div style={{
                  padding: '10px 16px',
                  marginBottom: 8,
                  background: 'linear-gradient(135deg, #fef9ef, #fdf2e9)',
                  borderRadius: 12,
                  border: '1px solid #f5e6d3',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  animation: 'fadeIn 0.3s ease',
                }}>
                  <span style={{ fontSize: 20 }}>{progressFeedback.emoji}</span>
                  <span style={{ fontSize: 13, color: '#8b6914', flex: 1 }}>
                    {progressFeedback.message}
                  </span>
                  <Button
                    type="text"
                    size="small"
                    onClick={() => setProgressFeedback(null)}
                    style={{ color: '#c4a35a', fontSize: 11 }}
                  >
                    收起
                  </Button>
                </div>
              )}
              <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-xl)', padding: 12, boxShadow: 'var(--shadow-md)' }}>
              {/* Coach mode toggle */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <Segmented
                  size="small"
                  value={chatMode}
                  onChange={(v) => setChatMode(v as 'normal' | 'coach')}
                  options={[
                    { label: '普通模式', value: 'normal' },
                    { label: '教练模式', value: 'coach' },
                  ]}
                />
                {chatMode === 'coach' && (
                  <span style={{ fontSize: 11, color: '#722ed1' }}>
                    AI 将用苏格拉底式提问引导你思考
                  </span>
                )}
              </div>
              <TextArea
                placeholder="给学习助手发送消息（Enter 发送，Shift+Enter 换行）..."
                autoSize={{ minRows: 2, maxRows: 6 }}
                style={{ marginBottom: 8, borderRadius: 'var(--radius-md)', border: 'none', background: 'var(--gray-50)', resize: 'none' }}
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
                    handleSendMessage()
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
                disabled={false}
              />
              {/* Image preview strip */}
              {pendingImages.length > 0 && (
                <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                  {pendingImages.map((img, idx) => (
                    <div key={idx} style={{ position: 'relative', width: 64, height: 64 }}>
                      <img
                        src={`data:image/png;base64,${img}`}
                        alt={`待发送图片 ${idx + 1}`}
                        style={{ width: 64, height: 64, objectFit: 'cover', borderRadius: 8, border: '1px solid #ede4d9' }}
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
                          background: '#fff',
                          borderRadius: '50%',
                        }}
                      />
                    </div>
                  ))}
                </div>
              )}
              {/* Hidden file input for image upload */}
              <input
                ref={imageInputRef}
                type="file"
                accept="image/*"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) handleImageSelect(file)
                  e.target.value = ''
                }}
              />
              <div style={{ display: 'flex', gap: 8 }}>
                <Button
                  size="middle"
                  icon={<PictureOutlined />}
                  onClick={() => imageInputRef.current?.click()}
                  title="上传图片"
                />
                {chatLoading ? (
                  <Button
                    type="primary"
                    danger
                    size="middle"
                    block
                    onClick={handleStopStreaming}
                  >
                    停止生成
                  </Button>
                ) : (
                  <Button
                    type="primary"
                    size="middle"
                    block
                    onClick={() => void handleSendMessage()}
                  >
                    发送
                  </Button>
                )}
                {chatMessages.length > 0 && (
                  <Button
                    size="middle"
                    onClick={() => clearMessages()}
                    disabled={chatLoading}
                  >
                    清空
                  </Button>
                )}
                {!chatLoading && chatMessages.length > 1 && (
                  <Button
                    size="middle"
                    onClick={() => {
                      const last = getLastUserMessage()
                      if (last) void handleSendMessage(last)
                    }}
                  >
                    重新生成
                  </Button>
                )}
                {!chatLoading && chatMessages.length > 0 && (
                  <Button
                    size="middle"
                    onClick={() => void handleSendMessage('请继续上一个回答，衔接上文继续输出。')}
                  >
                    继续生成
                  </Button>
                )}
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
              </div>
              </div>
            </div>
          </div>
        </Content>
      </Layout>

      {/* 右侧拖拽分割线 */}
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

      {/* 右侧信息栏 */}
      <Sider
        width={rightWidth}
        style={{
          background: 'var(--bg-secondary)',
          borderLeft: '1px solid var(--border-color)',
          overflow: 'hidden',
          height: '100vh',
          position: 'fixed',
          right: 0,
        }}
      >
        <div style={{ height: '100%', overflowY: 'auto', padding: '16px' }}>
        {/* 今日激励 */}
        {!focusMode && <Card
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
              <Button
                type="text"
                size="small"
                onClick={() => {
                  setShowMotivationModal(true)
                  void loadMotivationSettings()
                  void loadAllQuotes()
                }}
                title="管理"
                style={{ fontSize: 13 }}
              >
                ⚙️
              </Button>
            </div>
          }
          style={{ marginBottom: 12 }}
        >
          <div style={{ textAlign: 'center', padding: '12px 4px' }}>
            <div style={{ fontSize: 14, fontStyle: 'italic', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
              {motivationQuote?.content || '加载中...'}
            </div>
            {motivationQuote?.author && (
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 8 }}>
                —— {motivationQuote.author}
              </div>
            )}
          </div>
          <div style={{ textAlign: 'center', marginTop: 10 }}>
            <Button type="dashed" size="small" loading={aiGenerating} onClick={handleGenerateAIQuote} style={{ borderRadius: 'var(--radius-sm)' }}>
              ✨ AI 生成激励
            </Button>
          </div>
        </Card>}
        {/* 日历 - 可折叠 */}
        {!focusMode && <Card
          size="small"
          title={
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <CalendarOutlined style={{ color: 'var(--accent-600)' }} />
              <span style={{ fontSize: 13, fontWeight: 500 }}>日历</span>
            </div>
          }
          extra={
            <Button
              type="text"
              size="small"
              icon={calendarExpanded ? <UpOutlined /> : <DownOutlined />}
              onClick={() => setCalendarExpanded(!calendarExpanded)}
            />
          }
          style={{ marginBottom: 12 }}
        >
          {calendarExpanded ? (
            <Calendar
              fullscreen={false}
              onSelect={onDateSelect}
              cellRender={dateCellRender}
            />
          ) : (
            <div style={{ textAlign: 'center', padding: '4px 0', color: 'var(--text-tertiary)', fontSize: 12 }}>
              点击展开查看完整日历
            </div>
          )}
        </Card>}

        {/* 当前学习信息 */}
        <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 500 }}>当前学习</span>} style={{ marginBottom: 12 }}>
          <p style={{ color: 'var(--text-tertiary)', fontSize: 13, margin: 0 }}>暂未选择章节</p>
        </Card>

        {/* 复习任务概览 */}
        <Card
          size="small"
          title={<span style={{ fontSize: 13, fontWeight: 500 }}>复习任务</span>}
          style={{ marginBottom: 12 }}
          extra={
            <Button type="link" size="small" onClick={() => navigate('/review')} style={{ fontSize: 12 }}>
              去复习
            </Button>
          }
        >
          <div style={{ marginBottom: 10 }}>
            <Tag color={reviewDueCount > 0 ? 'red' : 'green'}>
              今日待复习 {reviewDueCount}
            </Tag>
          </div>
          <List
            size="small"
            dataSource={reviewPreviewTasks}
            locale={{ emptyText: '暂无到期任务' }}
            renderItem={(task) => (
              <List.Item
                style={{ padding: '6px 0', cursor: 'pointer' }}
                onClick={() => navigate('/review')}
              >
                <div style={{ width: '100%' }}>
                  <div
                    style={{
                      fontSize: 12,
                      color: 'var(--text-primary)',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {task.content || '复习任务'}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                    {task.item_type === 'chapter' ? '章节复习' : '错题复习'} · {task.chapter_title || '未分类'}
                  </div>
                </div>
              </List.Item>
            )}
          />
        </Card>

        {/* 学习进度 */}
        <Card size="small" title={<span style={{ fontSize: 13, fontWeight: 500 }}>今日进度</span>} style={{ marginBottom: 12 }}>
          {(() => {
            const totalTasks = dashboardData?.today_task_count || 0
            const completedTasks = dashboardData?.today_completed_count || 0
            const taskPercent = totalTasks > 0 ? Math.round((completedTasks / totalTasks) * 100) : 0
            return (
              <div>
                <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginBottom: 4 }}>
                  完成任务（{completedTasks}/{totalTasks}）
                </div>
                <Progress percent={taskPercent} size="small" status="active" strokeColor="var(--accent-500)" />
              </div>
            )
          })()}
        </Card>

        {/* 番茄钟 */}
        <Card
          size="small"
          title={
            <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 14 }}>🍅</span>
              <span style={{ fontSize: 13, fontWeight: 500 }}>番茄工作法</span>
              <span
                title={backendOnline ? '已连接后端' : '离线模式'}
                style={{
                  display: 'inline-block',
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: backendOnline ? 'var(--success)' : 'var(--gray-300)',
                  marginLeft: 4,
                }}
              />
            </span>
          }
          extra={
            <div style={{ display: 'flex', gap: 4 }}>
              <Button
                type="text"
                size="small"
                icon={<BarChartOutlined />}
                onClick={() => setShowStatsModal(true)}
                title="查看统计"
              />
              <Button
                type="link"
                size="small"
                onClick={() => setShowPomodoroModal(true)}
              >
                设置
              </Button>
            </div>
          }
          style={{
            marginBottom: 16,
          }}
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
                {currentTask || pomodoroConfig.taskName}
              </div>
            )}

            <div
              style={{
                fontSize: 40,
                fontWeight: 'bold',
                fontFamily: "'JetBrains Mono', monospace",
                margin: '8px 0',
                color: isRunning ? 'var(--error)' : 'var(--text-primary)',
                letterSpacing: '2px',
              }}
            >
              {formatTime(remainingTime)}
            </div>

            <Progress
              percent={Math.round(
                (1 - remainingTime / (duration * 60)) * 100
              )}
              showInfo={false}
              strokeColor={isRunning ? 'var(--error)' : 'var(--success)'}
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
                  <Button danger onClick={handleAbandonPomodoro}>
                    放弃
                  </Button>
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
                  <Button icon={<CheckCircleOutlined />} onClick={handleCompletePomodoro}>
                    完成
                  </Button>
                  <Button danger onClick={handleAbandonPomodoro}>
                    放弃
                  </Button>
                </>
              )}
            </div>
          </div>
        </Card>
        </div>
      </Sider>

      {/* 番茄钟设置弹窗 */}
      <Modal
        title="番茄钟设置"
        open={showPomodoroModal}
        onOk={() => {
          resetTimer()
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
              setPomodoroConfig({ ...pomodoroConfig, taskName: e.target.value })
            }
            style={{ marginTop: 8 }}
          />
        </div>
        <div>
          <label>番茄时长（分钟）</label>
          <InputNumber
            min={1}
            max={60}
            value={pomodoroConfig.duration}
            onChange={(value) =>
              setPomodoroConfig({ ...pomodoroConfig, duration: value || 25 })
            }
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
        width={360}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '8px 0' }}>
          <Button
            block
            size="large"
            type={selectedStopReason === 'early_done' ? 'primary' : 'default'}
            onClick={() => setSelectedStopReason('early_done')}
            style={{ textAlign: 'left', height: 'auto', padding: '12px 16px' }}
          >
            <div style={{ fontWeight: 600 }}>✅ 提前完成了任务</div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 400 }}>任务做完了，状态不错</div>
          </Button>
          <Button
            block
            size="large"
            type={selectedStopReason === 'interrupted' ? 'primary' : 'default'}
            onClick={() => setSelectedStopReason('interrupted')}
            style={{ textAlign: 'left', height: 'auto', padding: '12px 16px' }}
          >
            <div style={{ fontWeight: 600 }}>📱 临时有事，被打断了</div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 400 }}>外部原因，不影响学习评估</div>
          </Button>
          <Button
            block
            size="large"
            type={selectedStopReason === 'distracted' ? 'primary' : 'default'}
            onClick={() => setSelectedStopReason('distracted')}
            style={{ textAlign: 'left', height: 'auto', padding: '12px 16px' }}
          >
            <div style={{ fontWeight: 600 }}>😔 状态不好，没学进去</div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 400 }}>走神了，AI 会帮你分析改善</div>
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

      {/* 日程计划弹窗 */}}
      <Modal
        title={`${selectedDate?.format('YYYY年MM月DD日')} 的计划`}
        open={showPlanModal}
        onOk={savePlan}
        onCancel={() => { setShowPlanModal(false); setPlanViewMode('edit') }}
        width={600}
      >
        <Segmented
          value={planViewMode}
          onChange={(v) => setPlanViewMode(v as 'edit' | 'checklist')}
          options={[
            { label: '编辑', value: 'edit' },
            { label: '清单', value: 'checklist' },
          ]}
          style={{ marginBottom: 12 }}
        />
        {planViewMode === 'edit' ? (
          <>
            <TextArea
              placeholder={`输入今日计划或学习记录...\n例如：\n- [ ] 复习第一章\n- [ ] 完成10道练习题\n- [ ] 整理笔记`}
              value={currentPlan}
              onChange={(e) => setCurrentPlan(e.target.value)}
              autoSize={{ minRows: 8, maxRows: 15 }}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-tertiary)' }}>
              使用 <code>- [ ]</code> 创建可勾选任务，切换到「清单」视图查看和勾选
            </div>
          </>
        ) : (
          <div style={{ minHeight: 160, padding: '8px 0' }}>
            {parsePlanLines(currentPlan).map((line) => (
              line.type === 'task' ? (
                <div key={line.index} style={{ padding: '4px 0' }}>
                  <Checkbox
                    checked={line.checked}
                    onChange={() => {
                      const updated = toggleTaskLine(currentPlan, line.index)
                      setCurrentPlan(updated)
                      // Auto-save on toggle
                      if (selectedDate) {
                        const dateStr = selectedDate.format('YYYY-MM-DD')
                        apiFetch(`/api/plans/${dateStr}`, {
                          method: 'PUT',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ content: updated }),
                        }).then(() => {
                          setDailyPlans((prev) => ({ ...prev, [dateStr]: updated }))
                          loadWeeklyPlans()
                        }).catch(() => {})
                      }
                    }}
                  >
                    <span style={{
                      textDecoration: line.checked ? 'line-through' : 'none',
                      color: line.checked ? '#999' : '#1d1d1f',
                    }}>
                      {line.label}
                    </span>
                  </Checkbox>
                </div>
              ) : (
                <div key={line.index} style={{ padding: '4px 0', color: 'var(--text-secondary)' }}>
                  {line.label || '\u00A0'}
                </div>
              )
            ))}
            {parsePlanLines(currentPlan).every((l) => l.type === 'text' && !l.label.trim()) && (
              <div style={{ textAlign: 'center', color: 'var(--text-tertiary)', padding: '40px 0' }}>
                暂无任务。切换到「编辑」视图，使用 <code>- [ ]</code> 添加任务
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* 今日激励管理弹窗 */}
      <Modal
        title="管理激励语录"
        open={showMotivationModal}
        onCancel={() => setShowMotivationModal(false)}
        footer={null}
        width={520}
      >
        <Card size="small" style={{ marginBottom: 12, background: '#fffdf8' }}>
          <div style={{ display: 'grid', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>展示模式</span>
              <Segmented
                size="small"
                value={motivationSettings.display_mode}
                options={[
                  { label: '自动轮换', value: 'auto' },
                  { label: '固定展示', value: 'manual' },
                ]}
                onChange={(v) => setMotivationSettings((prev) => ({ ...prev, display_mode: v as 'auto' | 'manual' }))}
              />
            </div>

            {motivationSettings.display_mode === 'manual' && (
              <div style={{ display: 'grid', gap: 4 }}>
                <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>固定语录</span>
                <Select
                  size="small"
                  placeholder="选择一条语录作为固定展示"
                  value={motivationSettings.selected_quote_id ?? undefined}
                  onChange={(v) => setMotivationSettings((prev) => ({ ...prev, selected_quote_id: Number(v) }))}
                  options={allQuotes.map((q) => ({
                    value: q.id,
                    label: `${q.content.slice(0, 36)}${q.content.length > 36 ? '…' : ''}`,
                  }))}
                />
              </div>
            )}

            <div style={{ display: 'grid', gap: 4 }}>
              <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>轮换顺序</span>
              <Select
                size="small"
                value={motivationSettings.sort_mode}
                onChange={(v) => setMotivationSettings((prev) => ({ ...prev, sort_mode: String(v) }))}
                options={QUOTE_SORT_OPTIONS}
              />
            </div>

            <div style={{ display: 'grid', gap: 4 }}>
              <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>轮换周期</span>
              <Select
                size="small"
                value={motivationSettings.rotation_seconds}
                onChange={(v) => setMotivationSettings((prev) => ({ ...prev, rotation_seconds: Number(v) }))}
                options={QUOTE_ROTATION_OPTIONS}
              />
            </div>

            <Button
              type="primary"
              loading={savingMotivationSettings}
              onClick={handleSaveMotivationSettings}
            >
              保存展示设置
            </Button>
          </div>
        </Card>

        <div style={{ marginBottom: 12 }}>
          <TextArea
            placeholder="写一句你喜欢的激励语录..."
            value={newQuoteContent}
            onChange={(e) => setNewQuoteContent(e.target.value)}
            autoSize={{ minRows: 2, maxRows: 4 }}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <Input
              placeholder="作者/来源（可选）"
              value={newQuoteAuthor}
              onChange={(e) => setNewQuoteAuthor(e.target.value)}
            />
            <Button type="primary" onClick={handleAddCustomQuote}>
              添加
            </Button>
          </div>
        </div>
        <List
          size="small"
          dataSource={allQuotes}
          locale={{ emptyText: '暂无语录' }}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button
                  key="pin-current"
                  type="text"
                  size="small"
                  disabled={savingMotivationSettings}
                  onClick={() => handlePinCurrentQuote(item.id)}
                >
                  设为当前
                </Button>,
                <Button
                  key="delete"
                  type="text"
                  danger
                  size="small"
                  onClick={() => handleDeleteQuote(item.id)}
                >
                  删除
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 500 }}>{item.content}</span>
                    {motivationSettings.selected_quote_id === item.id && (
                      <Tag color="gold" style={{ fontSize: 10, lineHeight: '16px' }}>当前固定</Tag>
                    )}
                    <Tag
                      color={item.source_type === 'preset' ? 'default' : item.source_type === 'ai' ? 'purple' : 'blue'}
                      style={{ fontSize: 10, lineHeight: '16px' }}
                    >
                      {item.source_type === 'preset' ? '预设' : item.source_type === 'ai' ? 'AI' : '自定义'}
                    </Tag>
                  </div>
                }
                description={item.author ? `—— ${item.author}` : undefined}
              />
            </List.Item>
          )}
        />
      </Modal>

      {/* 番茄钟统计弹窗 - 增强版 */}
      <Modal
        title={<span><BarChartOutlined /> 番茄钟统计</span>}
        open={showStatsModal}
        onCancel={() => setShowStatsModal(false)}
        footer={null}
        width={680}
        styles={{ body: { padding: '16px 24px' } }}
      >
        {/* 累计统计面板 */}
        {(() => {
          const cumulativeStats = getCumulativeStats()
          return (
            <Card
              size="small"
              style={{
                marginBottom: 16,
                background: 'linear-gradient(135deg, rgba(255,77,79,0.08) 0%, rgba(255,149,0,0.08) 100%)',
                border: '1px solid rgba(255,77,79,0.15)',
              }}
            >
              <div style={{ textAlign: 'center', marginBottom: 8 }}>
                <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>累计专注</span>
              </div>
              <Row gutter={16}>
                <Col span={8} style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 32, fontWeight: 'bold', color: '#ff4d4f' }}>
                    {cumulativeStats.totalCount}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>次数</div>
                </Col>
                <Col span={8} style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 32, fontWeight: 'bold', color: '#007AFF' }}>
                    {cumulativeStats.totalHours}<span style={{ fontSize: 14, fontWeight: 'normal' }}>h</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>时长</div>
                </Col>
                <Col span={8} style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 32, fontWeight: 'bold', color: '#34C759' }}>
                    {cumulativeStats.dailyAverageMinutes}<span style={{ fontSize: 14, fontWeight: 'normal' }}>m</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>日均</div>
                </Col>
              </Row>
            </Card>
          )
        })()}

        {/* 时间范围选择器 */}
        <div style={{ marginBottom: 16, textAlign: 'center' }}>
          <Segmented
            value={statsRange}
            onChange={(value) => setStatsRange(value as DateRange)}
            options={[
              { label: '日', value: 'day' },
              { label: '周', value: 'week' },
              { label: '月', value: 'month' },
              { label: '全部', value: 'all' },
            ]}
            style={{
              background: 'rgba(0,0,0,0.04)',
              padding: 2,
            }}
          />
        </div>

        {/* 当前范围统计 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small" style={{ textAlign: 'center', background: '#fff2e8' }}>
              <div style={{ fontSize: 20, fontWeight: 'bold', color: '#ff4d4f' }}>{stats.todayCount}</div>
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>今日番茄</div>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" style={{ textAlign: 'center', background: '#fef9ef' }}>
              <div style={{ fontSize: 20, fontWeight: 'bold', color: 'var(--primary-600)' }}>{stats.todayMinutes}</div>
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>今日分钟</div>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" style={{ textAlign: 'center', background: '#f6ffed' }}>
              <div style={{ fontSize: 20, fontWeight: 'bold', color: '#52c41a' }}>{stats.weekCount}</div>
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>本周番茄</div>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" style={{ textAlign: 'center', background: '#f9f0ff' }}>
              <div style={{ fontSize: 20, fontWeight: 'bold', color: '#722ed1' }}>{Math.round(stats.weekMinutes / 60)}</div>
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>本周小时</div>
            </Card>
          </Col>
        </Row>

        {/* 饼状图 - 任务时长分布 */}
        {(() => {
          const distribution = getTaskDistribution(statsRange)
          const totalMinutes = distribution.reduce((sum, t) => sum + t.minutes, 0)

          if (distribution.length === 0) {
            return (
              <Card size="small" title="专注时长分布" style={{ marginBottom: 16 }}>
                <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-tertiary)' }}>
                  暂无数据，开始专注计时吧
                </div>
              </Card>
            )
          }

          const pieOption = {
            tooltip: {
              trigger: 'item',
              backgroundColor: 'rgba(255, 255, 255, 0.95)',
              borderColor: 'rgba(0, 0, 0, 0.1)',
              borderWidth: 1,
              textStyle: { color: 'var(--text-primary)', fontSize: 12 },
              formatter: (params: any) => {
                const hours = Math.floor(params.data.minutes / 60)
                const mins = params.data.minutes % 60
                const timeStr = hours > 0 ? `${hours}h ${mins}m` : `${mins}m`
                return `<b>${params.name}</b><br/>⏱️ ${timeStr}<br/>🍅 ${params.data.count}个 (${params.percent}%)`
              },
            },
            legend: {
              orient: 'vertical',
              right: 10,
              top: 'center',
              itemWidth: 10,
              itemHeight: 10,
              textStyle: { fontSize: 11, color: 'var(--text-secondary)' },
            },
            series: [{
              type: 'pie',
              radius: ['45%', '70%'],
              center: ['35%', '50%'],
              avoidLabelOverlap: true,
              itemStyle: {
                borderRadius: 4,
                borderColor: '#fff',
                borderWidth: 2,
              },
              label: { show: false },
              emphasis: {
                label: { show: true, fontSize: 12, fontWeight: 'bold' },
                itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.2)' },
              },
              data: distribution.map((t) => ({
                value: t.minutes,
                name: t.taskName,
                minutes: t.minutes,
                count: t.count,
                itemStyle: { color: t.color },
              })),
            }],
          }

          return (
            <Card
              size="small"
              title={
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>专注时长分布</span>
                  <span style={{ fontSize: 12, color: 'var(--text-tertiary)', fontWeight: 'normal' }}>
                    共 {Math.floor(totalMinutes / 60)}h {totalMinutes % 60}m
                  </span>
                </div>
              }
              style={{ marginBottom: 16 }}
            >
              <ReactECharts option={pieOption} style={{ height: 200 }} />

              {/* 任务列表 */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(2, 1fr)',
                gap: 8,
                marginTop: 12,
                paddingTop: 12,
                borderTop: '1px solid rgba(0,0,0,0.06)',
              }}>
                {distribution.slice(0, 6).map((task) => (
                  <div
                    key={task.taskName}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      padding: '6px 8px',
                      background: 'rgba(0,0,0,0.02)',
                      borderRadius: 6,
                    }}
                  >
                    <div style={{
                      width: 10,
                      height: 10,
                      borderRadius: 3,
                      background: task.color,
                      flexShrink: 0,
                    }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{
                        fontSize: 12,
                        fontWeight: 500,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}>
                        {task.taskName}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                        {Math.floor(task.minutes / 60)}h {task.minutes % 60}m · {task.percentage}%
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )
        })()}

        {/* 本周趋势 */}
        <Card size="small" title="本周趋势">
          <ReactECharts option={weekChartOption} style={{ height: 160 }} />
        </Card>
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
            <Card size="small" style={{ marginBottom: 16, background: '#faf6f0' }}>
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
                background: '#faf6f0',
                padding: 16
              }}
            >
              {currentMaterial?.file_type === 'pdf' ? (
                <div>
                  <div style={{
                    padding: '40px',
                    textAlign: 'center',
                    border: '2px dashed #ede4d9',
                    borderRadius: 8,
                    marginBottom: 16
                  }}>
                    <FileOutlined style={{ fontSize: 48, color: '#ff4d4f', marginBottom: 16 }} />
                    <div style={{ color: 'var(--text-secondary)' }}>PDF 文件</div>
                    <div style={{ color: 'var(--text-tertiary)', fontSize: 12, marginTop: 8 }}>
                      {currentMaterial?.name}
                    </div>
                  </div>
                  <div style={{
                    background: '#fffbf5',
                    padding: 16,
                    borderRadius: 8,
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
                      background: '#fffbf5',
                      padding: 16,
                      borderRadius: 8,
                    }}
                  >
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {previewContent || '暂无预览内容'}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <div style={{
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.8,
                    fontSize: 14,
                    background: '#fffbf5',
                    padding: 16,
                    borderRadius: 8
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
                accept=".pdf,.doc,.docx,.txt,.md,.epub"
              >
                <p><UploadOutlined style={{ fontSize: 22, color: 'var(--text-secondary)' }} /></p>
                <p style={{ fontSize: 13, color: 'var(--text-primary)', margin: '6px 0 2px' }}>上传到当前项目</p>
                <p style={{ fontSize: 11, color: '#999' }}>支持 PDF、Word、TXT、Markdown、EPUB</p>
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

      <AISettingsDrawer open={showAISettings} onClose={() => setShowAISettings(false)} />
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
