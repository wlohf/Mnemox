import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BookOpen,
  CalendarDays,
  CalendarPlus,
  Check,
  CheckCheck,
  CircleCheck,
  CloudOff,
  Flag,
  ListTree,
  MessageSquareText,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Plus,
  Square,
  Target,
  Timer,
  Trash2,
  Undo2,
} from 'lucide-react'
import { Button, Confirm, Empty, IconButton, Menu, ProgressRing, Segmented, Skeleton, toast, type MenuEntry } from '../../ui'
import { useOfflineGoals, type OfflineGoalItem } from '../../hooks/useOfflineGoals'
import { useOfflineGoalTasks, type OfflineGoalTaskItem } from '../../hooks/useOfflineGoalTasks'
import {
  completeStudySession,
  listActiveStudySessions,
  startStudySession,
  type StudySessionItem,
} from '../../services/studySessionApi'
import { generateNextWeekGoalTasks } from '../../services/goalApi'
import { getApiErrorMessage } from '../../services/apiClient'
import { syncEngine } from '../../sync/SyncEngine'
import { useSyncStatus } from '../../sync/useSyncStatus'
import { usePageChrome } from '../../app/shell/shellStore'
import { qk } from '../../app/queryClient'
import { EvalDialog, GoalDialog, PlanDialog, TaskDialog } from './GoalDialogs'
import {
  buildTaskTree,
  deadlineLabel,
  dueLabel,
  flattenTree,
  minutesSince,
  progressOf,
  taskTypeLabel,
  type TaskNode,
} from './taskTree'
import s from './goals.module.css'

type Filter = 'all' | 'active' | 'completed' | 'paused'

const STATUS_LABEL: Record<string, string> = { active: '进行中', completed: '已完成', paused: '已暂停' }

const invalidateToday = (qc: ReturnType<typeof useQueryClient>) => {
  void qc.invalidateQueries({ queryKey: ['goals'] })
  void qc.invalidateQueries({ queryKey: qk.dashboard })
  void qc.invalidateQueries({ queryKey: ['agent', 'goal-context'] })
}

export function GoalsPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [filter, setFilter] = useState<Filter>('all')
  const { goals: allGoals, createGoal, updateGoal, deleteGoal } = useOfflineGoals()
  const { goalTasks: allTasks, createGoalTask, updateGoalTask, deleteGoalTask } = useOfflineGoalTasks()
  const [goalDialog, setGoalDialog] = useState<{ goal: OfflineGoalItem | null } | null>(null)
  const [taskDialog, setTaskDialog] = useState<{ mode: 'task' | 'milestone'; task?: OfflineGoalTaskItem; parentId?: number | null } | null>(null)
  const [planOpen, setPlanOpen] = useState(false)
  const [evalTask, setEvalTask] = useState<OfflineGoalTaskItem | null>(null)
  const [removingGoal, setRemovingGoal] = useState<OfflineGoalItem | null>(null)
  const [removingTask, setRemovingTask] = useState<OfflineGoalTaskItem | null>(null)
  const [busyTask, setBusyTask] = useState<Record<string, boolean>>({})
  const [generating, setGenerating] = useState(false)
  const sync = useSyncStatus()

  const sessions = useQuery({
    queryKey: ['study-sessions', 'active'],
    queryFn: () => listActiveStudySessions(),
    staleTime: 30_000,
  })
  const sessionByTask = useMemo(() => {
    const map = new Map<number, StudySessionItem>()
    for (const sess of sessions.data ?? []) if (sess.task_id) map.set(sess.task_id, sess)
    return map
  }, [sessions.data])

  // Minute tick so "学习中 12 分钟" stays honest.
  const [, setTick] = useState(0)
  useEffect(() => {
    if (sessionByTask.size === 0) return
    const id = window.setInterval(() => setTick(t => t + 1), 30_000)
    return () => window.clearInterval(id)
  }, [sessionByTask.size])

  const goals = useMemo(
    () =>
      allGoals
        .filter(g => filter === 'all' || g.status === filter)
        .sort((a, b) => {
          // Active goals first, then soonest deadline, then most recent.
          const rank = (g: OfflineGoalItem) => (g.status === 'active' ? 0 : g.status === 'paused' ? 1 : 2)
          if (rank(a) !== rank(b)) return rank(a) - rank(b)
          const ad = a.deadline ?? '9999'
          const bd = b.deadline ?? '9999'
          if (ad !== bd) return ad < bd ? -1 : 1
          return a.updated_at > b.updated_at ? -1 : 1
        }),
    [allGoals, filter],
  )

  const tasksByGoal = useMemo(() => {
    const map = new Map<string, OfflineGoalTaskItem[]>()
    for (const t of allTasks) {
      const key = t._localGoalId ?? allGoals.find(g => g._serverId != null && g._serverId === t.goal_id)?._localId
      if (!key) continue
      const bucket = map.get(key)
      if (bucket) bucket.push(t)
      else map.set(key, [t])
    }
    return map
  }, [allTasks, allGoals])

  // Selection lives in the URL (?goal=<localId>) so it survives reloads and links.
  const selectedId = params.get('goal')
  const selected = goals.find(g => g._localId === selectedId) ?? goals[0] ?? null
  const select = (g: OfflineGoalItem) => {
    const next = new URLSearchParams(params)
    next.set('goal', g._localId)
    setParams(next, { replace: true })
  }

  const tasks = useMemo(() => (selected ? tasksByGoal.get(selected._localId) ?? [] : []), [selected, tasksByGoal])
  const tree = useMemo(() => buildTaskTree(tasks), [tasks])

  usePageChrome({ title: '目标' })

  const setBusy = (t: OfflineGoalTaskItem, v: boolean) => setBusyTask(p => ({ ...p, [t._localId]: v }))

  const setStatus = async (t: OfflineGoalTaskItem, status: 'pending' | 'in_progress' | 'completed', quiet = false) => {
    setBusy(t, true)
    try {
      await updateGoalTask(t._localId, {
        status,
        completed_at: status === 'completed' ? new Date().toISOString() : null,
      })
      invalidateToday(qc)
      if (!quiet && status === 'completed') {
        toast.success('完成一项', {
          description: t.title,
          actions: [{ label: '撤销', onClick: () => void setStatus(t, 'pending', true) }],
        })
      }
    } catch (error) {
      toast.error(getApiErrorMessage(error, '更新任务失败'))
    } finally {
      setBusy(t, false)
    }
  }

  const toggleDone = (t: OfflineGoalTaskItem) => {
    if (t.status === 'completed') void setStatus(t, 'pending')
    else if (t.task_type === 'milestone') void setStatus(t, 'completed')
    else setEvalTask(t)
  }

  const startSession = async (t: OfflineGoalTaskItem) => {
    if (t._serverId == null) {
      toast.warning('任务还没同步，稍后再开始')
      return
    }
    setBusy(t, true)
    try {
      const session = await startStudySession(t._serverId)
      if (!session) throw new Error('开始学习失败')
      if (t.status === 'pending') await updateGoalTask(t._localId, { status: 'in_progress' })
      await sessions.refetch()
      toast.info('学习计时开始', { description: '结束时记得写下这次的产出。' })
    } catch (error) {
      toast.error(getApiErrorMessage(error, '开始学习失败'))
    } finally {
      setBusy(t, false)
    }
  }

  const endSession = async (t: OfflineGoalTaskItem) => {
    const session = t._serverId != null ? sessionByTask.get(t._serverId) : undefined
    if (!session) return
    setBusy(t, true)
    try {
      await completeStudySession(session.id, { mark_task_completed: false })
      await sessions.refetch()
      setEvalTask(t)
    } catch (error) {
      toast.error(getApiErrorMessage(error, '结束学习失败'))
    } finally {
      setBusy(t, false)
    }
  }

  const nextWeek = async () => {
    if (!selected?._serverId) {
      toast.warning('目标还没同步到服务器')
      return
    }
    setGenerating(true)
    try {
      const r = await generateNextWeekGoalTasks(selected._serverId)
      toast.success(r.generated_tasks > 0 ? `已生成 ${r.generated_tasks} 个下周任务` : '下周没有新的章节任务')
      await syncEngine.syncAll()
      invalidateToday(qc)
    } catch (error) {
      toast.error(getApiErrorMessage(error, '生成失败'))
    } finally {
      setGenerating(false)
    }
  }

  const loading = allGoals.length === 0 && sync.status === 'syncing'

  return (
    <div className={s.page}>
      <GoalRail
        goals={goals}
        total={allGoals.length}
        filter={filter}
        onFilter={setFilter}
        selected={selected}
        onSelect={select}
        tasksByGoal={tasksByGoal}
        loading={loading}
        onCreate={() => setGoalDialog({ goal: null })}
      />

      {!selected ? (
        <div className={s.blank}>
          <Empty
            icon={<Target />}
            title={allGoals.length === 0 ? '还没有学习目标' : '这个分组里没有目标'}
            body={
              allGoals.length === 0
                ? '把一段学习写成一个目标：要达成什么、什么时候之前。教练会围绕它安排每天的下一步。'
                : '换一个筛选看看，或者新建一个目标。'
            }
            actions={
              <>
                <Button variant="primary" icon={<Plus />} onClick={() => setGoalDialog({ goal: null })}>
                  新建目标
                </Button>
                {allGoals.length === 0 && (
                  <Button variant="ghost" icon={<MessageSquareText />} onClick={() => navigate('/?ask=帮我把一个学习目标拆成里程碑和每周任务')}>
                    让教练帮我拆解
                  </Button>
                )}
              </>
            }
          />
        </div>
      ) : (
        <GoalDocument
          key={selected._localId}
          goal={selected}
          tasks={tasks}
          tree={tree}
          sessionByTask={sessionByTask}
          busyTask={busyTask}
          generating={generating}
          onEditGoal={() => setGoalDialog({ goal: selected })}
          onGoalStatus={async status => {
            await updateGoal(selected._localId, { status })
            invalidateToday(qc)
            toast.success(status === 'completed' ? '目标已标记完成' : status === 'paused' ? '目标已暂停' : '目标已恢复')
          }}
          onDeleteGoal={() => setRemovingGoal(selected)}
          onAddMilestone={() => setTaskDialog({ mode: 'milestone' })}
          onAddTask={parentId => setTaskDialog({ mode: 'task', parentId: parentId ?? null })}
          onEditTask={t => setTaskDialog({ mode: t.task_type === 'milestone' ? 'milestone' : 'task', task: t })}
          onDeleteTask={t => setRemovingTask(t)}
          onToggleDone={toggleDone}
          onStartTask={t => void setStatus(t, 'in_progress')}
          onStartSession={t => void startSession(t)}
          onEndSession={t => void endSession(t)}
          onPlan={() => setPlanOpen(true)}
          onNextWeek={() => void nextWeek()}
        />
      )}

      <GoalDialog
        open={Boolean(goalDialog)}
        onOpenChange={v => !v && setGoalDialog(null)}
        goal={goalDialog?.goal}
        onSubmit={async draft => {
          if (goalDialog?.goal) {
            await updateGoal(goalDialog.goal._localId, {
              title: draft.title,
              description: draft.description ?? null,
              deadline: draft.deadline ?? null,
            })
            toast.success('目标已保存')
          } else {
            const created = await createGoal(draft)
            setFilter('all')
            select(created)
            toast.success('目标已创建', { description: '接下来加几个里程碑，或者让计划自动排任务。' })
          }
          invalidateToday(qc)
        }}
      />

      <TaskDialog
        open={Boolean(taskDialog)}
        onOpenChange={v => !v && setTaskDialog(null)}
        mode={taskDialog?.mode ?? 'task'}
        task={taskDialog?.task}
        parentId={taskDialog?.parentId}
        tasks={tasks}
        onSubmit={async draft => {
          if (!selected) return
          if (taskDialog?.task) {
            await updateGoalTask(taskDialog.task._localId, {
              title: draft.title,
              task_type: draft.task_type,
              planned_date: draft.planned_date ?? null,
              parent_task_id: draft.parent_task_id,
            })
            toast.success('已保存')
          } else {
            await createGoalTask(selected._localId, selected._serverId, {
              title: draft.title,
              task_type: draft.task_type,
              planned_date: draft.planned_date,
              parent_task_id: draft.parent_task_id,
            })
            toast.success(draft.task_type === 'milestone' ? '里程碑已添加' : '任务已添加')
          }
          invalidateToday(qc)
        }}
      />

      <PlanDialog
        open={planOpen}
        onOpenChange={setPlanOpen}
        goal={selected}
        onDone={() => {
          void syncEngine.syncAll()
          invalidateToday(qc)
        }}
      />

      <EvalDialog
        open={Boolean(evalTask)}
        onOpenChange={v => !v && setEvalTask(null)}
        task={evalTask}
        onEvaluated={async (_r, passed) => {
          if (!evalTask) return
          await updateGoalTask(evalTask._localId, {
            status: passed ? 'completed' : 'in_progress',
            completed_at: passed ? new Date().toISOString() : null,
          })
          invalidateToday(qc)
        }}
        onSkip={async () => {
          if (evalTask) await setStatus(evalTask, 'completed')
        }}
      />

      <Confirm
        open={Boolean(removingGoal)}
        onOpenChange={v => !v && setRemovingGoal(null)}
        tone="danger"
        title={`删除目标「${removingGoal?.title ?? ''}」？`}
        description="目标下的里程碑和任务会一起删除。学习记录、笔记和复习不受影响。"
        confirmLabel="删除目标"
        onConfirm={async () => {
          if (!removingGoal) return
          try {
            await deleteGoal(removingGoal._localId)
            invalidateToday(qc)
            toast.success('目标已删除')
          } catch (error) {
            toast.error(getApiErrorMessage(error, '删除失败'))
            throw error
          }
        }}
      />

      <Confirm
        open={Boolean(removingTask)}
        onOpenChange={v => !v && setRemovingTask(null)}
        tone="danger"
        title={removingTask?.task_type === 'milestone' ? '删除这个里程碑？' : '删除这个任务？'}
        description={removingTask ? `「${removingTask.title}」会被删除。` : undefined}
        confirmLabel="删除"
        onConfirm={async () => {
          if (!removingTask) return
          try {
            await deleteGoalTask(removingTask._localId)
            invalidateToday(qc)
            toast.success('已删除')
          } catch (error) {
            toast.error(getApiErrorMessage(error, '删除失败'))
            throw error
          }
        }}
      />
    </div>
  )
}

/* ============================================================================
   Rail — every goal with its progress at a glance
   ========================================================================== */
function GoalRail({
  goals,
  total,
  filter,
  onFilter,
  selected,
  onSelect,
  tasksByGoal,
  loading,
  onCreate,
}: {
  goals: OfflineGoalItem[]
  total: number
  filter: Filter
  onFilter: (f: Filter) => void
  selected: OfflineGoalItem | null
  onSelect: (g: OfflineGoalItem) => void
  tasksByGoal: Map<string, OfflineGoalTaskItem[]>
  loading: boolean
  onCreate: () => void
}) {
  return (
    <nav className={s.rail} aria-label="目标列表">
      <div className={s.railHead}>
        <h2 className={s.railTitle}>目标</h2>
        <span className={s.railCount}>{total}</span>
        <span className={s.railHeadEnd}>
          <IconButton label="新建目标" size="sm" onClick={onCreate}>
            <Plus />
          </IconButton>
        </span>
      </div>
      <Segmented
        ariaLabel="按状态筛选"
        size="sm"
        block
        value={filter}
        onChange={onFilter}
        options={[
          { value: 'all', label: '全部' },
          { value: 'active', label: '进行中' },
          { value: 'paused', label: '暂停' },
          { value: 'completed', label: '完成' },
        ]}
      />
      {loading ? (
        <div className={s.railSkel}>
          {[0, 1, 2].map(i => (
            <Skeleton key={i} height={44} radius={10} />
          ))}
        </div>
      ) : goals.length === 0 ? (
        <p className={s.railEmpty}>{total === 0 ? '还没有目标。' : '没有符合筛选的目标。'}</p>
      ) : (
        <ul className={s.goalList}>
          {goals.map(g => {
            const p = progressOf(tasksByGoal.get(g._localId) ?? [])
            const due = g.status === 'active' ? deadlineLabel(g.deadline) : null
            const current = selected?._localId === g._localId
            return (
              <li key={g._localId}>
                <button
                  type="button"
                  className={s.goalRow}
                  aria-current={current || undefined}
                  data-status={g.status}
                  onClick={() => onSelect(g)}
                >
                  <ProgressRing
                    value={g.status === 'completed' ? 1 : p.ratio}
                    size={32}
                    stroke={3}
                    color={g.status === 'completed' ? 'var(--mx-success)' : g.status === 'paused' ? 'var(--mx-text-4)' : undefined}
                    label={`进度 ${Math.round(p.ratio * 100)}%`}
                  >
                    {g.status === 'completed' ? (
                      <span className={s.ringGlyph}>
                        <Check aria-hidden />
                      </span>
                    ) : g.status === 'paused' ? (
                      <span className={s.ringPaused}>
                        <Pause aria-hidden />
                      </span>
                    ) : null}
                  </ProgressRing>
                  <span className={s.goalRowText}>
                    <span className={s.goalRowTitle}>{g.title}</span>
                    <span className={s.goalRowMeta}>
                      {g.status !== 'active' ? (
                        <span>{STATUS_LABEL[g.status] ?? g.status}</span>
                      ) : p.total > 0 ? (
                        <span>
                          {p.done}/{p.total}
                        </span>
                      ) : (
                        <span>未拆解</span>
                      )}
                      {due && <span data-tone={due.tone}>· {due.text}</span>}
                      {g._syncStatus !== 'synced' && (
                        <span title="尚未同步">
                          · <CloudOff aria-label="尚未同步" style={{ width: 11, height: 11, display: 'inline' }} />
                        </span>
                      )}
                    </span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </nav>
  )
}

/* ============================================================================
   Document — the selected goal read as a plan
   ========================================================================== */
interface DocHandlers {
  onEditGoal: () => void
  onGoalStatus: (status: 'active' | 'completed' | 'paused') => Promise<void>
  onDeleteGoal: () => void
  onAddMilestone: () => void
  onAddTask: (parentId?: number | null) => void
  onEditTask: (t: OfflineGoalTaskItem) => void
  onDeleteTask: (t: OfflineGoalTaskItem) => void
  onToggleDone: (t: OfflineGoalTaskItem) => void
  onStartTask: (t: OfflineGoalTaskItem) => void
  onStartSession: (t: OfflineGoalTaskItem) => void
  onEndSession: (t: OfflineGoalTaskItem) => void
  onPlan: () => void
  onNextWeek: () => void
}

function GoalDocument({
  goal,
  tasks,
  tree,
  sessionByTask,
  busyTask,
  generating,
  ...h
}: DocHandlers & {
  goal: OfflineGoalItem
  tasks: OfflineGoalTaskItem[]
  tree: TaskNode[]
  sessionByTask: Map<number, StudySessionItem>
  busyTask: Record<string, boolean>
  generating: boolean
}) {
  const navigate = useNavigate()
  const progress = progressOf(tasks)
  const due = goal.status === 'active' ? deadlineLabel(goal.deadline) : null
  const ordered = useMemo(() => flattenTree(tree).filter(t => t.task_type !== 'milestone'), [tree])
  const next = ordered.find(t => t.status !== 'completed')
  const overdue = ordered.filter(t => t.status !== 'completed' && dueLabel(t.planned_date)?.tone === 'overdue').length
  const milestones = tree.filter(n => n.task.task_type === 'milestone')
  const loose = tree.filter(n => n.task.task_type !== 'milestone')

  const goalMenu: MenuEntry[] = [
    { key: 'edit', label: '编辑目标', icon: <Pencil />, onSelect: h.onEditGoal },
    { key: 'plan', label: '制定学习计划', icon: <CalendarDays />, onSelect: h.onPlan },
    ...(goal.material_id
      ? [{ key: 'week', label: '生成下周任务', icon: <CalendarPlus />, onSelect: h.onNextWeek, disabled: generating } as MenuEntry]
      : []),
    { key: 'sep1', type: 'separator' },
    goal.status === 'active'
      ? { key: 'pause', label: '暂停目标', icon: <Pause />, onSelect: () => void h.onGoalStatus('paused') }
      : { key: 'resume', label: '恢复为进行中', icon: <Play />, onSelect: () => void h.onGoalStatus('active') },
    ...(goal.status !== 'completed'
      ? [{ key: 'done', label: '标记目标完成', icon: <CheckCheck />, onSelect: () => void h.onGoalStatus('completed') } as MenuEntry]
      : []),
    { key: 'sep2', type: 'separator' },
    { key: 'delete', label: '删除目标', icon: <Trash2 />, tone: 'danger', onSelect: h.onDeleteGoal },
  ]

  const rowProps = { sessionByTask, busyTask, ...h }

  return (
    <article className={s.doc} aria-labelledby="goal-title">
      <div className={s.docMeta}>
        <span>
          <Target aria-hidden />
          {STATUS_LABEL[goal.status] ?? goal.status}
        </span>
        {goal.deadline && (
          <span data-tone={due?.tone}>
            <CalendarDays aria-hidden />
            {goal.deadline.slice(0, 10)} 截止{due ? ` · ${due.text}` : ''}
          </span>
        )}
        {goal.material_title && (
          <button type="button" className={s.materialLink} onClick={() => navigate(goal.material_id ? `/materials?id=${goal.material_id}` : '/materials')}>
            <BookOpen aria-hidden />
            <span>{goal.material_title}</span>
          </button>
        )}
        {goal._syncStatus !== 'synced' && (
          <span>
            <CloudOff aria-hidden />
            待同步
          </span>
        )}
      </div>
      <h1 id="goal-title" className={s.docTitle}>
        {goal.title}
      </h1>
      {goal.description && <p className={s.docDesc}>{goal.description}</p>}

      {progress.total > 0 && (
        <div className={s.progress}>
          {ordered.length > 0 && ordered.length <= 48 ? (
            <div className={s.ticks} role="img" aria-label={`已完成 ${progress.done} / ${progress.total}`}>
              {ordered.map((t, i) => (
                <span
                  key={t._localId}
                  className={s.tick}
                  data-status={t.status}
                  data-overdue={(t.status !== 'completed' && dueLabel(t.planned_date)?.tone === 'overdue') || undefined}
                  style={{ '--i': i } as CSSProperties}
                  title={t.title}
                />
              ))}
            </div>
          ) : (
            <div className={s.bar} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress.ratio * 100)}>
              <div className={s.barFill} style={{ transform: `scaleX(${progress.ratio})` }} />
            </div>
          )}
          <div className={s.progressCaption}>
            <span>
              完成 <strong>{progress.done}</strong> / {progress.total}
            </span>
            {overdue > 0 && <span style={{ color: 'var(--mx-warning)' }}>{overdue} 项已逾期</span>}
            {next && goal.status === 'active' && (
              <span className={s.nextUp}>
                下一项 <span>{next.title}</span>
              </span>
            )}
          </div>
        </div>
      )}

      <div className={s.docActions} style={progress.total === 0 ? { marginTop: '1.25rem' } : undefined}>
        <Button variant="primary" size="sm" icon={<Plus />} onClick={() => h.onAddTask(null)}>
          添加任务
        </Button>
        <Button variant="secondary" size="sm" icon={<Flag />} onClick={h.onAddMilestone}>
          里程碑
        </Button>
        {goal.material_id ? (
          <Button variant="ghost" size="sm" icon={<CalendarPlus />} loading={generating} onClick={h.onNextWeek}>
            生成下周
          </Button>
        ) : (
          <Button variant="ghost" size="sm" icon={<CalendarDays />} onClick={h.onPlan}>
            批量排任务
          </Button>
        )}
        <span className={s.spacer} />
        {goal.status === 'active' && next && (
          <Button variant="ghost" size="sm" icon={<Timer />} onClick={() => navigate(`/pomodoro?quick=25`)}>
            专注做下一项
          </Button>
        )}
        <Menu
          items={goalMenu}
          trigger={
            <IconButton label="目标操作" size="sm">
              <MoreHorizontal />
            </IconButton>
          }
        />
      </div>

      {tree.length === 0 ? (
        <div className={s.docEmpty}>
          <Empty
            align="start"
            icon={<ListTree />}
            title="先把目标拆开"
            body={
              goal.material_id
                ? '已经绑定了资料，可以按章节自动排出本周任务；也可以先手动加里程碑。'
                : '先写两三个里程碑（阶段），再在每个阶段下加具体任务。'
            }
            actions={
              <>
                {goal.material_id ? (
                  <Button size="sm" variant="primary" icon={<CalendarDays />} onClick={h.onPlan}>
                    按资料排计划
                  </Button>
                ) : (
                  <Button size="sm" variant="primary" icon={<Flag />} onClick={h.onAddMilestone}>
                    添加里程碑
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<MessageSquareText />}
                  onClick={() => navigate(`/?${new URLSearchParams({ ask: '帮我把这个目标拆成里程碑和本周任务', context: goal.title })}`)}
                >
                  让教练拆解
                </Button>
              </>
            }
          />
        </div>
      ) : (
        <div className={s.outline}>
          {milestones.map(node => (
            <Milestone key={node.task._localId} node={node} {...rowProps} />
          ))}
          {loose.length > 0 && (
            <section aria-label="其他任务">
              {milestones.length > 0 && <h2 className={s.groupLabel}>其他任务</h2>}
              <ul className={s.taskList}>
                {loose.map(node => (
                  <TaskItem key={node.task._localId} node={node} {...rowProps} />
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </article>
  )
}

type RowProps = Pick<
  DocHandlers,
  'onAddTask' | 'onEditTask' | 'onDeleteTask' | 'onToggleDone' | 'onStartTask' | 'onStartSession' | 'onEndSession'
> & {
  sessionByTask: Map<number, StudySessionItem>
  busyTask: Record<string, boolean>
}

function Milestone({ node, ...rp }: RowProps & { node: TaskNode }) {
  const m = node.task
  const all = flattenTree(node.children)
  const p = progressOf(all)
  const due = dueLabel(m.planned_date, undefined, m.status === 'completed')
  const done = m.status === 'completed' || (p.total > 0 && p.done === p.total)
  return (
    <section className={s.milestone} data-status={done ? 'completed' : m.status} aria-label={`里程碑：${m.title}`}>
      <div className={s.msHead}>
        {done ? <CircleCheck className={s.msIcon} aria-hidden /> : <Flag className={s.msIcon} aria-hidden />}
        <h2 className={s.msTitle} title={m.title}>
          {m.title}
        </h2>
        {p.total > 0 && (
          <span className={s.msCount}>
            {p.done}/{p.total}
          </span>
        )}
        {due && (
          <span className={s.msDue} data-tone={due.tone}>
            {due.text}
          </span>
        )}
        <span className={s.msActions}>
          <IconButton label="在这个里程碑下添加任务" size="sm" disabled={m._serverId == null} onClick={() => rp.onAddTask(m._serverId)}>
            <Plus />
          </IconButton>
          <Menu
            items={[
              { key: 'edit', label: '编辑里程碑', icon: <Pencil />, onSelect: () => rp.onEditTask(m) },
              m.status === 'completed'
                ? { key: 'undo', label: '标记为未完成', icon: <Undo2 />, onSelect: () => rp.onToggleDone(m) }
                : { key: 'done', label: '标记里程碑完成', icon: <CheckCheck />, onSelect: () => rp.onToggleDone(m) },
              { key: 'sep', type: 'separator' },
              { key: 'delete', label: '删除', icon: <Trash2 />, tone: 'danger', onSelect: () => rp.onDeleteTask(m) },
            ]}
            trigger={
              <IconButton label="里程碑操作" size="sm">
                <MoreHorizontal />
              </IconButton>
            }
          />
        </span>
      </div>
      {node.children.length === 0 ? (
        <p className={s.msEmpty}>
          这个阶段还没有任务。
          {m._serverId != null && (
            <button type="button" className={s.inlineLink} onClick={() => rp.onAddTask(m._serverId)}>
              加一个
            </button>
          )}
        </p>
      ) : (
        <ul className={s.taskList}>
          {node.children.map(child => (
            <TaskItem key={child.task._localId} node={child} {...rp} />
          ))}
        </ul>
      )}
    </section>
  )
}

function TaskItem({ node, sessionByTask, busyTask, ...h }: RowProps & { node: TaskNode }) {
  const t = node.task
  const done = t.status === 'completed'
  const session = t._serverId != null ? sessionByTask.get(t._serverId) : undefined
  const mins = session ? minutesSince(session.started_at) : null
  const due = dueLabel(t.planned_date, undefined, done)
  const busy = busyTask[t._localId]
  const isMilestone = t.task_type === 'milestone'

  const menu: MenuEntry[] = [
    ...(!done && t.status !== 'in_progress' ? [{ key: 'start', label: '标记为进行中', icon: <Play />, onSelect: () => h.onStartTask(t) } as MenuEntry] : []),
    ...(t._serverId != null && !isMilestone ? [{ key: 'sub', label: '添加子任务', icon: <Plus />, onSelect: () => h.onAddTask(t._serverId) } as MenuEntry] : []),
    { key: 'edit', label: '编辑', icon: <Pencil />, onSelect: () => h.onEditTask(t) },
    { key: 'sep', type: 'separator' },
    { key: 'delete', label: '删除', icon: <Trash2 />, tone: 'danger', onSelect: () => h.onDeleteTask(t) },
  ]

  return (
    <li className={s.task} data-status={t.status} data-session={session ? true : undefined}>
      <div className={s.taskRow}>
        <button
          type="button"
          className={s.check}
          disabled={busy}
          aria-label={done ? `标记为未完成：${t.title}` : `完成：${t.title}`}
          aria-pressed={done}
          onClick={() => h.onToggleDone(t)}
        >
          <Check aria-hidden />
        </button>
        <div className={s.taskBody}>
          <span className={s.taskTitle} title={t.title}>
            {t.title}
          </span>
          <span className={s.taskMeta}>
            <span>{taskTypeLabel(t.task_type)}</span>
            {due && <span data-tone={due.tone}>{due.text}</span>}
            {t.status === 'in_progress' && !session && <span data-tone="today">进行中</span>}
            {t.chapter_title && <span className={s.chapter}>{t.chapter_title}</span>}
            {t._syncStatus !== 'synced' && (
              <span className={s.unsynced}>
                <CloudOff aria-hidden />
                待同步
              </span>
            )}
          </span>
        </div>
        {session ? (
          <span className={s.live} aria-label={`学习中 ${mins ?? 0} 分钟`}>
            <i aria-hidden />
            学习中 {mins ?? 0} 分钟
          </span>
        ) : (
          <span />
        )}
        <span className={s.taskActions}>
          {!done &&
            !isMilestone &&
            (session ? (
              <Button size="sm" variant="secondary" icon={<Square />} loading={busy} onClick={() => h.onEndSession(t)}>
                结束
              </Button>
            ) : (
              <IconButton label="开始学习计时" size="sm" disabled={busy || t._serverId == null} onClick={() => h.onStartSession(t)}>
                <Play />
              </IconButton>
            ))}
          <Menu
            items={menu}
            trigger={
              <IconButton label="任务操作" size="sm">
                <MoreHorizontal />
              </IconButton>
            }
          />
        </span>
      </div>
      {node.children.length > 0 && (
        <ul className={s.subList}>
          {node.children.map(child => (
            <TaskItem key={child.task._localId} node={child} sessionByTask={sessionByTask} busyTask={busyTask} {...h} />
          ))}
        </ul>
      )}
    </li>
  )
}

