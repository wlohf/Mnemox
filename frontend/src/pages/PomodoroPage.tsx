import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button,
  Card,
  Col,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Tag,
  Tooltip,
  Upload,
  message,
} from 'antd'
import {
  BarChartOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  FolderAddOutlined,
  HistoryOutlined,
  MoreOutlined,
  PauseCircleFilled,
  PictureOutlined,
  PlayCircleFilled,
  PlusOutlined,
  ReloadOutlined,
  StopFilled,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { usePomodoroStore, type DateRange, type PomodoroRecord } from '../stores/pomodoroStore'
import { PageShell } from '../components/PageShell'
import { getCurrentQuote, type MotivationQuote } from '../services/motivationApi'

const MAX_BACKGROUND_IMAGE_SIZE = 3 * 1024 * 1024
const TASK_STORAGE_KEY = 'mnemox_pomodoro_focus_tasks'
const TASK_SET_STORAGE_KEY = 'mnemox_pomodoro_task_sets'
const DEFAULT_TASK_SET_ID = 'default'

const TASK_BACKGROUNDS = [
  'linear-gradient(135deg, #f45d5d 0%, #f65d6b 100%)',
  'linear-gradient(135deg, #42c9d6 0%, #56bfd7 100%)',
  'linear-gradient(135deg, #8fa2cc 0%, #7d8fc0 100%)',
  'linear-gradient(135deg, #f8c924 0%, #f6b51f 100%)',
  'linear-gradient(135deg, #4a98c8 0%, #2f87b6 100%)',
  'linear-gradient(135deg, #b697dd 0%, #8d81c9 100%)',
  'linear-gradient(135deg, #5bc7b7 0%, #7bd4c8 100%)',
  'linear-gradient(135deg, #2d415f 0%, #172437 100%)',
]

type PomodoroStageStyle = CSSProperties & {
  '--mnemox-pomodoro-background'?: string
}

type FocusTaskCardStyle = CSSProperties & {
  '--mnemox-focus-task-bg'?: string
}

interface ReusablePomodoroTaskSet {
  id: string
  name: string
  color: string
  createdAt: string
}

interface ReusablePomodoroTask {
  id: string
  title: string
  minutes: number
  setId: string
  color: string
  completed: boolean
  createdAt: string
  updatedAt: string
  completedAt?: string | null
  lastStartedAt?: string | null
}

interface TaskFormState {
  title: string
  minutes: number
  setId: string
  color: string
}

interface ReusableTaskStats {
  count: number
  minutes: number
  lastCompletedAt: string | null
}

const DEFAULT_TASK_SETS: ReusablePomodoroTaskSet[] = [
  {
    id: DEFAULT_TASK_SET_ID,
    name: '待办',
    color: '#f45d5d',
    createdAt: new Date(0).toISOString(),
  },
]

function createLocalId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function readStoredJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

function normalizeTaskTitle(value: string) {
  return value.trim().toLowerCase()
}

function normalizeTaskSets(value: unknown): ReusablePomodoroTaskSet[] {
  const list = Array.isArray(value) ? value : []
  const seen = new Set<string>()
  const normalized = [...DEFAULT_TASK_SETS, ...list]
    .filter((item): item is ReusablePomodoroTaskSet => {
      if (!item || typeof item !== 'object') return false
      const candidate = item as Partial<ReusablePomodoroTaskSet>
      return Boolean(candidate.id && candidate.name)
    })
    .filter((item) => {
      if (seen.has(item.id)) return false
      seen.add(item.id)
      return true
    })

  return normalized.length ? normalized : DEFAULT_TASK_SETS
}

function normalizeTasks(value: unknown, sets: ReusablePomodoroTaskSet[]): ReusablePomodoroTask[] {
  const list = Array.isArray(value) ? value : []
  const setIds = new Set(sets.map((set) => set.id))
  return list
    .filter((item): item is ReusablePomodoroTask => {
      if (!item || typeof item !== 'object') return false
      const candidate = item as Partial<ReusablePomodoroTask>
      return Boolean(candidate.id && candidate.title)
    })
    .map((task, index) => ({
      ...task,
      title: String(task.title).trim() || '专注学习',
      minutes: Math.max(1, Math.min(120, Math.floor(Number(task.minutes) || 25))),
      setId: setIds.has(task.setId) ? task.setId : DEFAULT_TASK_SET_ID,
      color: task.color || TASK_BACKGROUNDS[index % TASK_BACKGROUNDS.length],
      completed: Boolean(task.completed),
      createdAt: task.createdAt || new Date().toISOString(),
      updatedAt: task.updatedAt || task.createdAt || new Date().toISOString(),
      completedAt: task.completedAt ?? null,
      lastStartedAt: task.lastStartedAt ?? null,
    }))
}

function formatDuration(minutes: number) {
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60)
    const rest = Math.round(minutes % 60)
    return rest > 0 ? `${hours} 小时 ${rest} 分钟` : `${hours} 小时`
  }
  return `${Math.round(minutes)} 分钟`
}

function formatShortDateTime(value: string | null | undefined) {
  if (!value) return '暂无'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '暂无'
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function makeEmptyStats(): ReusableTaskStats {
  return { count: 0, minutes: 0, lastCompletedAt: null }
}

export function PomodoroPage() {
  const navigate = useNavigate()
  const {
    getStats,
    getCumulativeStats,
    getTaskDistribution,
    getRecordsByRange,
    records,
    isRunning,
    isPaused,
    duration,
    remainingTime,
    currentTask,
    timerMode,
    breakDuration,
    startTimer,
    startBreakTimer,
    setBreakDuration,
    pauseTimer,
    resumeTimer,
    completeTimer,
    resetTimer,
    backgroundImage,
    setBackgroundImage,
  } = usePomodoroStore()

  const [range, setRange] = useState<DateRange>('week')
  const [taskName, setTaskName] = useState('专注学习')
  const [focusMinutes, setFocusMinutes] = useState(25)
  const [stopReasonModalVisible, setStopReasonModalVisible] = useState(false)
  const [stopReason, setStopReason] = useState('')
  const [quote, setQuote] = useState<MotivationQuote | null>(null)
  const [taskSets, setTaskSets] = useState<ReusablePomodoroTaskSet[]>(() => (
    normalizeTaskSets(readStoredJson<ReusablePomodoroTaskSet[]>(TASK_SET_STORAGE_KEY, DEFAULT_TASK_SETS))
  ))
  const [tasks, setTasks] = useState<ReusablePomodoroTask[]>(() => (
    normalizeTasks(readStoredJson<ReusablePomodoroTask[]>(TASK_STORAGE_KEY, []), normalizeTaskSets(readStoredJson<ReusablePomodoroTaskSet[]>(TASK_SET_STORAGE_KEY, DEFAULT_TASK_SETS)))
  ))
  const [activeSetId, setActiveSetId] = useState<'all' | string>('all')
  const [taskModalOpen, setTaskModalOpen] = useState(false)
  const [editingTask, setEditingTask] = useState<ReusablePomodoroTask | null>(null)
  const [taskForm, setTaskForm] = useState<TaskFormState>({
    title: '',
    minutes: 25,
    setId: DEFAULT_TASK_SET_ID,
    color: TASK_BACKGROUNDS[0],
  })
  const [setModalOpen, setSetModalOpen] = useState(false)
  const [newSetName, setNewSetName] = useState('')
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)

  useEffect(() => {
    void getCurrentQuote().then(setQuote).catch(() => undefined)
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem(TASK_SET_STORAGE_KEY, JSON.stringify(taskSets))
    } catch {
      // ignore storage failures
    }
  }, [taskSets])

  useEffect(() => {
    try {
      localStorage.setItem(TASK_STORAGE_KEY, JSON.stringify(tasks))
    } catch {
      // ignore storage failures
    }
  }, [tasks])

  const stats = getStats()
  const cumulative = getCumulativeStats()
  const distribution = getTaskDistribution(range)
  const rangeRecords = getRecordsByRange(range)

  const taskStatsByName = useMemo(() => {
    const map = new Map<string, ReusableTaskStats>()
    for (const record of records) {
      const key = normalizeTaskTitle(record.taskName)
      const existing = map.get(key) || makeEmptyStats()
      map.set(key, {
        count: existing.count + 1,
        minutes: existing.minutes + record.duration,
        lastCompletedAt: !existing.lastCompletedAt || record.completedAt > existing.lastCompletedAt
          ? record.completedAt
          : existing.lastCompletedAt,
      })
    }
    return map
  }, [records])

  const activeTasks = useMemo(() => {
    const filtered = activeSetId === 'all' ? tasks : tasks.filter((task) => task.setId === activeSetId)
    return filtered
      .filter((task) => !task.completed)
      .sort((a, b) => (b.lastStartedAt || b.updatedAt).localeCompare(a.lastStartedAt || a.updatedAt))
  }, [activeSetId, tasks])

  const completedTasks = useMemo(() => {
    const filtered = activeSetId === 'all' ? tasks : tasks.filter((task) => task.setId === activeSetId)
    return filtered
      .filter((task) => task.completed)
      .sort((a, b) => (b.completedAt || b.updatedAt).localeCompare(a.completedAt || a.updatedAt))
  }, [activeSetId, tasks])

  const selectedTask = useMemo(() => (
    selectedTaskId ? tasks.find((task) => task.id === selectedTaskId) || null : null
  ), [selectedTaskId, tasks])

  const selectedTaskRecords = useMemo(() => {
    if (!selectedTask) return []
    const key = normalizeTaskTitle(selectedTask.title)
    return records
      .filter((record) => normalizeTaskTitle(record.taskName) === key)
      .sort((a, b) => b.completedAt.localeCompare(a.completedAt))
      .slice(0, 8)
  }, [records, selectedTask])

  const selectedTaskStats = selectedTask
    ? taskStatsByName.get(normalizeTaskTitle(selectedTask.title)) || makeEmptyStats()
    : makeEmptyStats()

  const taskSetOptions = taskSets.map((set) => ({ label: set.name, value: set.id }))

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  const getTaskStats = (task: ReusablePomodoroTask) => (
    taskStatsByName.get(normalizeTaskTitle(task.title)) || makeEmptyStats()
  )

  const updateTask = (taskId: string, updater: (task: ReusablePomodoroTask) => ReusablePomodoroTask) => {
    setTasks((prev) => prev.map((task) => (task.id === taskId ? updater(task) : task)))
  }

  const guardNoActiveTimer = () => {
    if (isRunning || isPaused) {
      message.warning('当前已有番茄钟在进行中')
      return false
    }
    return true
  }

  const handleStart = () => {
    if (!guardNoActiveTimer()) return
    const safeName = taskName.trim() || '专注学习'
    startTimer(safeName, focusMinutes)
    setTasks((prev) => prev.map((task) => (
      normalizeTaskTitle(task.title) === normalizeTaskTitle(safeName)
        ? { ...task, lastStartedAt: new Date().toISOString(), updatedAt: new Date().toISOString(), completed: false, completedAt: null }
        : task
    )))
    message.success('番茄钟已启动')
  }

  const handleStartTask = (task: ReusablePomodoroTask) => {
    if (!guardNoActiveTimer()) return
    const now = new Date().toISOString()
    setTaskName(task.title)
    setFocusMinutes(task.minutes)
    updateTask(task.id, (item) => ({
      ...item,
      completed: false,
      completedAt: null,
      lastStartedAt: now,
      updatedAt: now,
    }))
    setSelectedTaskId(null)
    startTimer(task.title, task.minutes)
    message.success(`开始：${task.title}`)
  }

  const handleStop = () => {
    if (timerMode === 'break') {
      resetTimer()
      message.success('休息已结束')
      return
    }
    setStopReasonModalVisible(true)
  }

  const confirmStop = () => {
    completeTimer(undefined, { startBreak: false })
    message.success(stopReason.trim() ? '已记录本次停止原因' : '番茄钟已停止')
    setStopReasonModalVisible(false)
    setStopReason('')
  }

  const handleTakeBreak = () => {
    if (isRunning || isPaused) {
      message.warning('当前已有番茄钟在进行中')
      return
    }
    startBreakTimer(breakDuration)
    message.success('开始休息')
  }

  const openCreateTaskModal = (seed?: Partial<TaskFormState>) => {
    setEditingTask(null)
    setTaskForm({
      title: seed?.title ?? taskName,
      minutes: seed?.minutes ?? focusMinutes,
      setId: seed?.setId ?? (activeSetId === 'all' ? DEFAULT_TASK_SET_ID : activeSetId),
      color: seed?.color ?? TASK_BACKGROUNDS[tasks.length % TASK_BACKGROUNDS.length],
    })
    setTaskModalOpen(true)
  }

  const openEditTaskModal = (task: ReusablePomodoroTask) => {
    setSelectedTaskId(null)
    setEditingTask(task)
    setTaskForm({
      title: task.title,
      minutes: task.minutes,
      setId: task.setId,
      color: task.color,
    })
    setTaskModalOpen(true)
  }

  const handleSaveTask = () => {
    const title = taskForm.title.trim()
    if (!title) {
      message.warning('请输入任务名称')
      return
    }

    const now = new Date().toISOString()
    const minutes = Math.max(1, Math.min(120, Math.floor(Number(taskForm.minutes) || 25)))
    if (editingTask) {
      setTasks((prev) => prev.map((task) => (
        task.id === editingTask.id
          ? { ...task, title, minutes, setId: taskForm.setId, color: taskForm.color, updatedAt: now }
          : task
      )))
      message.success('任务已更新')
    } else {
      const newTask: ReusablePomodoroTask = {
        id: createLocalId(),
        title,
        minutes,
        setId: taskForm.setId,
        color: taskForm.color,
        completed: false,
        createdAt: now,
        updatedAt: now,
        completedAt: null,
        lastStartedAt: null,
      }
      setTasks((prev) => [newTask, ...prev])
      message.success('任务已创建')
    }
    setTaskName(title)
    setFocusMinutes(minutes)
    setTaskModalOpen(false)
    setEditingTask(null)
  }

  const handleAddTaskSet = () => {
    const name = newSetName.trim()
    if (!name) {
      message.warning('请输入待办集名称')
      return
    }
    if (taskSets.some((set) => set.name === name)) {
      message.warning('待办集已存在')
      return
    }

    const set: ReusablePomodoroTaskSet = {
      id: createLocalId(),
      name,
      color: TASK_BACKGROUNDS[taskSets.length % TASK_BACKGROUNDS.length],
      createdAt: new Date().toISOString(),
    }
    setTaskSets((prev) => [...prev, set])
    setActiveSetId(set.id)
    setNewSetName('')
    setSetModalOpen(false)
    message.success('待办集已创建')
  }

  const handleToggleTaskDone = (task: ReusablePomodoroTask, completed: boolean) => {
    const now = new Date().toISOString()
    updateTask(task.id, (item) => ({
      ...item,
      completed,
      completedAt: completed ? now : null,
      updatedAt: now,
    }))
  }

  const handleDeleteTask = (task: ReusablePomodoroTask) => {
    Modal.confirm({
      title: '删除专注任务',
      content: `确定删除“${task.title}”？已有番茄钟历史记录不会删除。`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => {
        setTasks((prev) => prev.filter((item) => item.id !== task.id))
        setSelectedTaskId((prev) => (prev === task.id ? null : prev))
        message.success('任务已删除')
      },
    })
  }

  const handleBackgroundUpload = (file: File) => {
    if (!file.type.startsWith('image/')) {
      message.warning('请选择图片文件')
      return false
    }

    if (file.size > MAX_BACKGROUND_IMAGE_SIZE) {
      message.warning('背景图不能超过 3MB')
      return false
    }

    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result
      if (typeof result !== 'string') {
        message.error('背景图读取失败')
        return
      }

      try {
        setBackgroundImage(result)
        message.success('番茄背景已更新')
      } catch {
        message.error('背景图保存失败，请换一张更小的图片')
      }
    }
    reader.onerror = () => message.error('背景图读取失败')
    reader.readAsDataURL(file)
    return false
  }

  const handleResetBackground = () => {
    setBackgroundImage(null)
    message.success('已恢复默认背景')
  }

  const weekOption = useMemo(() => ({
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const data = params[0]
        const dayData = stats.weeklyData[data.dataIndex]
        const minutes = dayData?.minutes || 0
        return `${['日', '一', '二', '三', '四', '五', '六'][new Date(dayData?.date).getDay()] || ''}<br/>番茄 ${data.value} 个<br/>${minutes.toFixed(1)} 分钟`
      },
    },
    grid: { top: 10, right: 10, bottom: 20, left: 30 },
    xAxis: {
      type: 'category',
      data: stats.weeklyData.map((d) => ['日', '一', '二', '三', '四', '五', '六'][new Date(d.date).getDay()]),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: 'var(--text-secondary)', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: 'var(--border-light)' } },
      axisLabel: { color: 'var(--text-secondary)', fontSize: 10 },
    },
    series: [{
      type: 'bar',
      data: stats.weeklyData.map((d) => d.count),
      barWidth: '50%',
      itemStyle: {
        color: '#eef4f1',
        borderRadius: [4, 4, 0, 0],
      },
    }],
  }), [stats.weeklyData])

  const pieOption = useMemo(() => ({
    tooltip: {
      trigger: 'item',
      formatter: (params: any) => {
        const minutes = params.data.minutes as number
        const hours = minutes / 60
        const display = hours >= 1 ? `${hours.toFixed(1)}h` : `${minutes.toFixed(1)}m`
        return `${params.name}<br/>${display}<br/>番茄 ${params.data.count} 个 (${params.percent}%)`
      },
    },
    legend: {
      orient: 'vertical',
      right: 10,
      top: 'center',
      textStyle: { fontSize: 11, color: 'var(--text-secondary)' },
    },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['35%', '50%'],
      data: distribution.map((t) => ({
        value: t.minutes,
        name: t.taskName,
        minutes: t.minutes,
        count: t.count,
        itemStyle: { color: t.color },
      })),
      label: { show: false },
      itemStyle: { borderColor: 'var(--bg-surface)', borderWidth: 2 },
    }],
  }), [distribution])

  const totalDuration = Math.max(1, duration * 60)
  const progress = isRunning || isPaused ? Math.max(0, Math.min(1, 1 - remainingTime / totalDuration)) : 0
  const radius = 132
  const circumference = 2 * Math.PI * radius
  const strokeDashoffset = circumference - progress * circumference
  const isBreak = timerMode === 'break'
  const statusLabel = isRunning || isPaused ? (isBreak ? '休息中' : '专注中') : '准备开始'
  const activeTask = isRunning || isPaused ? currentTask || (isBreak ? '休息' : '专注学习') : taskName
  const stageStyle: PomodoroStageStyle | undefined = backgroundImage
    ? { '--mnemox-pomodoro-background': `url("${backgroundImage}")` }
    : undefined

  const renderTaskCard = (task: ReusablePomodoroTask) => {
    const taskStats = getTaskStats(task)
    const taskSet = taskSets.find((set) => set.id === task.setId)
    const cardStyle: FocusTaskCardStyle = { '--mnemox-focus-task-bg': task.color }

    return (
      <div
        key={task.id}
        className={`mnemox-focus-task-card${task.completed ? ' is-completed' : ''}`}
        style={cardStyle}
      >
        <div className="mnemox-focus-task-card-main" onClick={() => setSelectedTaskId(task.id)}>
          <div>
            <div className="mnemox-focus-task-title">{task.title}</div>
            <div className="mnemox-focus-task-meta">
              <span>{task.minutes} 分钟</span>
              <span>{taskStats.count} 次</span>
              {taskSet && <span>{taskSet.name}</span>}
            </div>
          </div>
          <Button
            className="mnemox-focus-task-start"
            type="text"
            icon={<PlayCircleFilled />}
            onClick={(event) => {
              event.stopPropagation()
              handleStartTask(task)
            }}
          >
            开始
          </Button>
        </div>
        <div className="mnemox-focus-task-footer">
          <span>累计 {formatDuration(taskStats.minutes)}</span>
          <Space size={4}>
            <Tooltip title={task.completed ? '恢复到待办' : '标记完成'}>
              <Button
                type="text"
                size="small"
                icon={<CheckCircleOutlined />}
                onClick={() => handleToggleTaskDone(task, !task.completed)}
              />
            </Tooltip>
            <Tooltip title="编辑">
              <Button
                type="text"
                size="small"
                icon={<EditOutlined />}
                onClick={() => openEditTaskModal(task)}
              />
            </Tooltip>
            <Tooltip title="详情和统计">
              <Button
                type="text"
                size="small"
                icon={<MoreOutlined />}
                onClick={() => setSelectedTaskId(task.id)}
              />
            </Tooltip>
          </Space>
        </div>
      </div>
    )
  }

  return (
    <PageShell
      title="番茄专注"
      onBack={() => navigate('/')}
      maxWidth={1480}
      rightExtra={(
        <div className="mnemox-pomodoro-header-actions">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openCreateTaskModal()}>
            新建任务
          </Button>
          <Upload
            accept="image/png,image/jpeg,image/gif,image/webp,image/bmp"
            showUploadList={false}
            beforeUpload={handleBackgroundUpload}
          >
            <Button icon={<PictureOutlined />}>{backgroundImage ? '更换背景' : '上传背景'}</Button>
          </Upload>
          {backgroundImage && (
            <Button icon={<DeleteOutlined />} onClick={handleResetBackground}>
              默认背景
            </Button>
          )}
          <Segmented
            value={range}
            onChange={(value) => setRange(value as DateRange)}
            options={[
              { label: '日', value: 'day' },
              { label: '周', value: 'week' },
              { label: '月', value: 'month' },
              { label: '全部', value: 'all' },
            ]}
          />
        </div>
      )}
    >
      <div className="mnemox-pomodoro-workbench">
        <aside className="mnemox-pomodoro-task-pane">
          <div className="mnemox-pomodoro-pane-header">
            <div>
              <span>待办</span>
              <small>{activeTasks.length} 个未完成</small>
            </div>
            <Space size={4}>
              <Tooltip title="新建待办集">
                <Button type="text" icon={<FolderAddOutlined />} onClick={() => setSetModalOpen(true)} />
              </Tooltip>
              <Tooltip title="新建任务">
                <Button type="text" icon={<PlusOutlined />} onClick={() => openCreateTaskModal()} />
              </Tooltip>
            </Space>
          </div>

          <div className="mnemox-pomodoro-set-list">
            <button
              type="button"
              className={`mnemox-pomodoro-set-item${activeSetId === 'all' ? ' is-active' : ''}`}
              onClick={() => setActiveSetId('all')}
            >
              <span>全部任务</span>
              <Tag>{tasks.length}</Tag>
            </button>
            {taskSets.map((set) => (
              <button
                key={set.id}
                type="button"
                className={`mnemox-pomodoro-set-item${activeSetId === set.id ? ' is-active' : ''}`}
                onClick={() => setActiveSetId(set.id)}
              >
                <i style={{ background: set.color }} />
                <span>{set.name}</span>
                <Tag>{tasks.filter((task) => task.setId === set.id).length}</Tag>
              </button>
            ))}
          </div>

          <div className="mnemox-pomodoro-task-list">
            {activeTasks.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无可继续的专注任务"
              >
                <Button type="primary" onClick={() => openCreateTaskModal()}>
                  创建一个任务
                </Button>
              </Empty>
            ) : (
              activeTasks.map(renderTaskCard)
            )}

            {completedTasks.length > 0 && (
              <div className="mnemox-focus-task-completed">
                <div className="mnemox-focus-task-completed-title">已完成</div>
                {completedTasks.slice(0, 4).map(renderTaskCard)}
              </div>
            )}
          </div>
        </aside>

        <main className="mnemox-pomodoro-main">
          <section className="mnemox-pomodoro-stage" style={stageStyle}>
            <div className="mnemox-pomodoro-quote">
              <span className="mnemox-pomodoro-quote-mark">“</span>
              <p>{quote?.content || '如果一个人不知道他要驶向哪个码头，那么任何风都不会是顺风。'}</p>
              {quote?.author && <small>{quote.author}</small>}
            </div>

            <div className="mnemox-pomodoro-ring" aria-label="番茄倒计时">
              <svg viewBox="0 0 320 320" aria-hidden="true">
                <circle cx="160" cy="160" r={radius} className="mnemox-pomodoro-ring-track" />
                <circle
                  cx="160"
                  cy="160"
                  r={radius}
                  className="mnemox-pomodoro-ring-progress"
                  strokeDasharray={circumference}
                  strokeDashoffset={strokeDashoffset}
                />
              </svg>
              <div className="mnemox-pomodoro-time">
                <strong>{formatTime(remainingTime || focusMinutes * 60)}</strong>
                <span>{statusLabel}</span>
              </div>
            </div>

            <div className="mnemox-pomodoro-task">{activeTask}</div>

            {!isRunning && !isPaused && (
              <div className="mnemox-pomodoro-setup">
                <Input
                  value={taskName}
                  onChange={(event) => setTaskName(event.target.value)}
                  placeholder="临时专注任务"
                />
                <InputNumber
                  min={1}
                  max={120}
                  value={focusMinutes}
                  onChange={(value) => {
                    const next = Number(value)
                    if (Number.isFinite(next)) setFocusMinutes(Math.max(1, Math.min(120, next)))
                  }}
                  addonAfter="分钟"
                />
                <Button onClick={() => openCreateTaskModal({ title: taskName, minutes: focusMinutes })}>
                  保存为任务
                </Button>
              </div>
            )}

            <div className="mnemox-pomodoro-controls">
              {!isRunning && !isPaused ? (
                <>
                  <Button type="primary" size="large" icon={<PlayCircleFilled />} onClick={handleStart}>
                    开始专注
                  </Button>
                  <Button size="large" icon={<ReloadOutlined />} onClick={handleTakeBreak}>
                    休息 {breakDuration} 分钟
                  </Button>
                  <InputNumber
                    min={1}
                    max={60}
                    value={breakDuration}
                    onChange={(value) => {
                      const next = Number(value)
                      if (Number.isFinite(next)) setBreakDuration(Math.max(1, Math.min(60, next)))
                    }}
                    addonAfter="休息"
                  />
                </>
              ) : (
                <>
                  {isPaused ? (
                    <Button type="primary" size="large" shape="circle" icon={<PlayCircleFilled />} onClick={resumeTimer} aria-label="继续" />
                  ) : (
                    <Button size="large" shape="circle" icon={<PauseCircleFilled />} onClick={pauseTimer} aria-label="暂停" />
                  )}
                  <Button danger size="large" shape="circle" icon={<StopFilled />} onClick={handleStop} aria-label="停止" />
                </>
              )}
            </div>
          </section>

          <Row gutter={[16, 16]} style={{ marginTop: 18 }}>
            <Col xs={12} md={6}>
              <Card size="small"><Statistic title="累计番茄" value={cumulative.totalCount} suffix="个" /></Card>
            </Col>
            <Col xs={12} md={6}>
              <Card size="small"><Statistic title="累计时长" value={cumulative.totalHours.toFixed(1)} suffix="小时" /></Card>
            </Col>
            <Col xs={12} md={6}>
              <Card size="small"><Statistic title="当前范围" value={rangeRecords.length} suffix="次" /></Card>
            </Col>
            <Col xs={12} md={6}>
              <Card size="small"><Statistic title="活跃天数" value={cumulative.activeDays} suffix="天" /></Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} lg={14}>
              <Card size="small" title={<span><BarChartOutlined /> 任务时长分布</span>}>
                {distribution.length === 0 ? (
                  <div style={{ textAlign: 'center', color: 'var(--text-tertiary)', padding: '48px 0' }}>暂无数据，先完成一个番茄吧</div>
                ) : (
                  <ReactECharts option={pieOption} style={{ height: 300 }} />
                )}
              </Card>
            </Col>
            <Col xs={24} lg={10}>
              <Card size="small" title="本周趋势">
                <ReactECharts option={weekOption} style={{ height: 300 }} />
              </Card>
            </Col>
          </Row>
        </main>
      </div>

      <Modal
        title={editingTask ? '编辑专注任务' : '新建专注任务'}
        open={taskModalOpen}
        onOk={handleSaveTask}
        onCancel={() => {
          setTaskModalOpen(false)
          setEditingTask(null)
        }}
        okText={editingTask ? '保存' : '创建'}
        cancelText="取消"
      >
        <div className="mnemox-focus-task-form">
          <label>
            <span>任务名称</span>
            <Input
              value={taskForm.title}
              onChange={(event) => setTaskForm((prev) => ({ ...prev, title: event.target.value }))}
              placeholder="例如：英语单词、计算机网络"
            />
          </label>
          <label>
            <span>默认时长</span>
            <InputNumber
              min={1}
              max={120}
              value={taskForm.minutes}
              onChange={(value) => {
                const next = Number(value)
                if (Number.isFinite(next)) setTaskForm((prev) => ({ ...prev, minutes: Math.max(1, Math.min(120, next)) }))
              }}
              addonAfter="分钟"
              style={{ width: '100%' }}
            />
          </label>
          <label>
            <span>待办集</span>
            <Select
              value={taskForm.setId}
              options={taskSetOptions}
              onChange={(value) => setTaskForm((prev) => ({ ...prev, setId: value }))}
            />
          </label>
          <div>
            <span className="mnemox-focus-task-form-label">任务卡背景</span>
            <div className="mnemox-focus-task-swatches">
              {TASK_BACKGROUNDS.map((color) => (
                <button
                  key={color}
                  type="button"
                  className={taskForm.color === color ? 'is-active' : ''}
                  style={{ background: color }}
                  onClick={() => setTaskForm((prev) => ({ ...prev, color }))}
                  aria-label="选择任务卡背景"
                />
              ))}
            </div>
          </div>
        </div>
      </Modal>

      <Modal
        title="新建待办集"
        open={setModalOpen}
        onOk={handleAddTaskSet}
        onCancel={() => setSetModalOpen(false)}
        okText="创建"
        cancelText="取消"
      >
        <Input
          value={newSetName}
          onChange={(event) => setNewSetName(event.target.value)}
          placeholder="例如：期末复习、英语学习"
        />
      </Modal>

      <Modal
        title={selectedTask?.title || '任务详情'}
        open={Boolean(selectedTask)}
        onCancel={() => setSelectedTaskId(null)}
        footer={selectedTask ? (
          <Space wrap>
            <Button icon={<EditOutlined />} onClick={() => openEditTaskModal(selectedTask)}>编辑</Button>
            <Button icon={<CheckCircleOutlined />} onClick={() => handleToggleTaskDone(selectedTask, !selectedTask.completed)}>
              {selectedTask.completed ? '恢复待办' : '标记完成'}
            </Button>
            <Button icon={<PlayCircleFilled />} type="primary" onClick={() => handleStartTask(selectedTask)}>开始</Button>
            <Button icon={<DeleteOutlined />} danger onClick={() => handleDeleteTask(selectedTask)}>删除</Button>
          </Space>
        ) : null}
        width={720}
      >
        {selectedTask && (
          <div className="mnemox-focus-task-detail">
            <div className="mnemox-focus-task-detail-summary">
              <div>
                <ClockCircleOutlined />
                <span>默认时长</span>
                <strong>{selectedTask.minutes} 分钟</strong>
              </div>
              <div>
                <HistoryOutlined />
                <span>累计专注</span>
                <strong>{formatDuration(selectedTaskStats.minutes)}</strong>
              </div>
              <div>
                <BarChartOutlined />
                <span>完成番茄</span>
                <strong>{selectedTaskStats.count} 次</strong>
              </div>
            </div>
            <div className="mnemox-focus-task-detail-meta">
              <Tag>{taskSets.find((set) => set.id === selectedTask.setId)?.name || '待办'}</Tag>
              <Tag color={selectedTask.completed ? 'green' : 'orange'}>{selectedTask.completed ? '已完成' : '待继续'}</Tag>
              <Tag>最近专注：{formatShortDateTime(selectedTaskStats.lastCompletedAt)}</Tag>
            </div>
            <List<PomodoroRecord>
              size="small"
              dataSource={selectedTaskRecords}
              locale={{ emptyText: '暂无专注历史' }}
              renderItem={(record) => (
                <List.Item>
                  <span>{formatShortDateTime(record.completedAt)}</span>
                  <span>{formatDuration(record.duration)}</span>
                </List.Item>
              )}
            />
          </div>
        )}
      </Modal>

      <Modal
        title="停止专注"
        open={stopReasonModalVisible}
        onOk={confirmStop}
        onCancel={() => setStopReasonModalVisible(false)}
        okText="确认停止"
        okButtonProps={{ danger: true }}
      >
        <p style={{ color: 'var(--text-secondary)' }}>请输入提前停止的原因（可选）：</p>
        <Input.TextArea
          value={stopReason}
          onChange={(event) => setStopReason(event.target.value)}
          placeholder="例如：被打断、任务已完成..."
          rows={3}
        />
      </Modal>
    </PageShell>
  )
}
