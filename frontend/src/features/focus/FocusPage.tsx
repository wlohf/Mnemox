import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Coffee, FolderPlus, ImageMinus, ImagePlus, Lightbulb, Pause, Pencil, Play, Plus, RotateCcw, Square, Trash2 } from 'lucide-react'
import {
  Button,
  Chip,
  Confirm,
  Dialog,
  Field,
  IconButton,
  Input,
  Notice,
  RadioCards,
  Segmented,
  Select,
  toast,
} from '../../ui'
import { usePomodoroStore, type DateRange } from '../../stores/pomodoroStore'
import { getCurrentQuote } from '../../services/motivationApi'
import { uploadBackgroundImageStrict } from '../../services/imageApi'
import { getApiErrorMessage, withAuthQuery } from '../../services/apiClient'
import { evaluateCoach } from '../../services/coachApi'
import { usePageChrome } from '../../app/shell/shellStore'
import { qk } from '../../app/queryClient'
import s from './focus.module.css'

/* Reusable focus tasks live in localStorage (legacy keys preserved). */
const TASK_KEY = 'mnemox_pomodoro_focus_tasks'
const SET_KEY = 'mnemox_pomodoro_task_sets'
const DEFAULT_SET = 'default'

const SWATCHES = [
  'oklch(0.52 0.09 164)',
  'oklch(0.43 0.105 258)',
  'oklch(0.56 0.14 55)',
  'oklch(0.525 0.175 27)',
  'oklch(0.55 0.1 300)',
  'oklch(0.6 0.08 220)',
  'oklch(0.45 0.03 264)',
]

interface TaskSet {
  id: string
  name: string
  color: string
  createdAt: string
}
interface FocusTask {
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

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}
const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
const clampMinutes = (n: number) => Math.max(1, Math.min(120, Math.floor(Number(n) || 25)))
const norm = (t: string) => t.trim().toLowerCase()

function clock(seconds: number) {
  const m = Math.floor(seconds / 60)
  const sec = Math.floor(seconds % 60)
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

type StopReason = 'early_done' | 'interrupted' | 'distracted'
const STOP_REASONS: Array<{ value: StopReason; title: string; description: string }> = [
  { value: 'early_done', title: '提前完成了', description: '任务做完了，状态不错。会被记为一次高效专注。' },
  { value: 'interrupted', title: '临时有事，被打断了', description: '外部原因，不计入你的专注评估。' },
  { value: 'distracted', title: '状态不好，没学进去', description: '走神了。教练会帮你看看怎么调整下一轮。' },
]
const STOP_TOAST: Record<StopReason, string> = {
  early_done: '提前完成，已记为高效专注',
  interrupted: '已记录为临时中断，不影响评估',
  distracted: '没关系，先休息一下。教练会参考这次状态',
}

export function FocusPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const coachAttemptId = params.get('coach_attempt')?.trim() || null
  const coachMinutesRaw = Number(params.get('coach_minutes') || params.get('quick'))
  const suggestedMinutes = Number.isFinite(coachMinutesRaw) && coachMinutesRaw > 0 ? clampMinutes(coachMinutesRaw) : null

  const st = usePomodoroStore()
  const { isRunning, isPaused, remainingTime, duration, currentTask, timerMode, breakDuration, records, backgroundImage } = st

  const [taskName, setTaskName] = useState('')
  const [minutes, setMinutes] = useState(suggestedMinutes ?? st.focusDuration ?? 25)
  const [stopOpen, setStopOpen] = useState(false)
  const [stopReason, setStopReason] = useState<StopReason>('early_done')
  const [range, setRange] = useState<DateRange>('week')
  const [sets, setSets] = useState<TaskSet[]>(() => {
    const list = readJson<TaskSet[]>(SET_KEY, [])
    return list.some(x => x.id === DEFAULT_SET) ? list : [{ id: DEFAULT_SET, name: '待办', color: SWATCHES[0], createdAt: new Date(0).toISOString() }, ...list]
  })
  const [tasks, setTasks] = useState<FocusTask[]>(() => readJson<FocusTask[]>(TASK_KEY, []))
  const [activeSet, setActiveSet] = useState<string>('all')
  const [editing, setEditing] = useState<FocusTask | 'new' | null>(null)
  const [form, setForm] = useState({ title: '', minutes: 25, setId: DEFAULT_SET, color: SWATCHES[0] })
  const [setDialog, setSetDialog] = useState(false)
  const [newSet, setNewSet] = useState('')
  const [deleting, setDeleting] = useState<FocusTask | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const quote = useQuery({ queryKey: qk.motivation, queryFn: () => getCurrentQuote(), staleTime: 30 * 60_000 })

  usePageChrome({ title: '专注' })

  useEffect(() => {
    void st.loadBackgroundImagePreference()
  }, [])
  useEffect(() => {
    if (suggestedMinutes && !isRunning && !isPaused) setMinutes(suggestedMinutes)
  }, [isPaused, isRunning, suggestedMinutes])
  useEffect(() => localStorage.setItem(SET_KEY, JSON.stringify(sets)), [sets])
  useEffect(() => localStorage.setItem(TASK_KEY, JSON.stringify(tasks)), [tasks])

  const active = isRunning || isPaused
  const isBreak = timerMode === 'break'
  const total = Math.max(1, duration * 60)
  const progress = active ? 1 - remainingTime / total : 0
  const shown = active ? remainingTime : minutes * 60
  const ringColor = isBreak ? 'var(--mx-success)' : 'var(--mx-ink)'
  const photo = backgroundImage ? withAuthQuery(backgroundImage) : null

  const guard = () => {
    if (active) {
      toast.warning('已有一段专注正在进行')
      return false
    }
    return true
  }

  const start = (title?: string, mins?: number) => {
    if (!guard()) return
    const name = (title ?? taskName).trim() || '专注学习'
    const m = clampMinutes(mins ?? minutes)
    st.startTimer(name, m, undefined, coachAttemptId)
    const now = new Date().toISOString()
    setTasks(prev => prev.map(t => (norm(t.title) === norm(name) ? { ...t, lastStartedAt: now, updatedAt: now, completed: false, completedAt: null } : t)))
    if (coachAttemptId) navigate('/pomodoro', { replace: true })
  }

  const confirmStop = () => {
    const { currentBackendId, startedAt, pausedTotalMs } = usePomodoroStore.getState()
    const elapsedMs = startedAt ? Math.max(0, Date.now() - startedAt - pausedTotalMs) : 0
    const actualMinutes = Math.max(0.1, Math.round((elapsedMs / 60000) * 10) / 10)
    const name = currentTask
    st.completeTimer(undefined, { startBreak: false, completed: false, stopReason })
    if (currentBackendId && stopReason !== 'early_done') {
      void evaluateCoach({
        event: {
          event_type: stopReason === 'interrupted' ? 'pomodoro.interrupted' : 'pomodoro.distracted',
          source: 'pomodoro',
          payload: { pomodoro_id: currentBackendId, task_name: name, actual_minutes: actualMinutes, stop_reason: stopReason },
          severity: 'info',
          dedupe_key: `pomodoro-stop:${currentBackendId}:${stopReason}`,
        },
        include_memories: true,
      })
    }
    setStopOpen(false)
    toast.info(STOP_TOAST[stopReason])
  }

  const stop = () => {
    if (isBreak) {
      st.resetTimer()
      toast.success('休息结束')
      return
    }
    setStopReason('early_done')
    setStopOpen(true)
  }

  /* -------- tasks -------- */
  const visibleTasks = useMemo(() => {
    const list = activeSet === 'all' ? tasks : tasks.filter(t => t.setId === activeSet)
    return [...list].sort((a, b) => Number(a.completed) - Number(b.completed) || (b.lastStartedAt || b.updatedAt).localeCompare(a.lastStartedAt || a.updatedAt))
  }, [activeSet, tasks])
  const statsByName = useMemo(() => {
    const map = new Map<string, { count: number; minutes: number }>()
    for (const r of records) {
      const k = norm(r.taskName)
      const e = map.get(k) ?? { count: 0, minutes: 0 }
      map.set(k, { count: e.count + 1, minutes: e.minutes + r.duration })
    }
    return map
  }, [records])

  const openEditor = (task: FocusTask | 'new') => {
    if (task === 'new') setForm({ title: taskName, minutes, setId: activeSet === 'all' ? DEFAULT_SET : activeSet, color: SWATCHES[tasks.length % SWATCHES.length] })
    else setForm({ title: task.title, minutes: task.minutes, setId: task.setId, color: task.color })
    setEditing(task)
  }
  const saveTask = () => {
    const title = form.title.trim()
    if (!title) {
      toast.warning('请输入任务名称')
      return
    }
    const now = new Date().toISOString()
    const m = clampMinutes(form.minutes)
    if (editing && editing !== 'new') {
      setTasks(prev => prev.map(t => (t.id === editing.id ? { ...t, title, minutes: m, setId: form.setId, color: form.color, updatedAt: now } : t)))
    } else {
      setTasks(prev => [{ id: uid(), title, minutes: m, setId: form.setId, color: form.color, completed: false, createdAt: now, updatedAt: now }, ...prev])
    }
    setEditing(null)
  }
  const addSet = () => {
    const name = newSet.trim()
    if (!name) return
    if (sets.some(x => x.name === name)) {
      toast.warning('这个清单已经存在')
      return
    }
    const set = { id: uid(), name, color: SWATCHES[sets.length % SWATCHES.length], createdAt: new Date().toISOString() }
    setSets(prev => [...prev, set])
    setActiveSet(set.id)
    setNewSet('')
    setSetDialog(false)
  }

  /* -------- stats -------- */
  const stats = st.getStats()
  const cumulative = st.getCumulativeStats()
  const distribution = st.getTaskDistribution(range).slice(0, 5)
  const maxDay = Math.max(1, ...stats.weeklyData.map(d => d.minutes))
  const todayIso = new Date().toISOString().slice(0, 10)

  const uploadPhoto = async (file: File) => {
    if (!file.type.startsWith('image/')) {
      toast.warning('请选择图片文件')
      return
    }
    setUploading(true)
    try {
      const result = await uploadBackgroundImageStrict(file)
      st.setBackgroundImage(result.raw_url)
      toast.success('专注背景已更新')
    } catch (e) {
      toast.error(getApiErrorMessage(e, '背景图上传失败'))
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className={s.page}>
      <section
        className={s.stage}
        data-photo={photo ? true : undefined}
        data-running={isRunning || undefined}
        style={{ '--ring-color': ringColor } as CSSProperties}
        aria-label="专注计时"
      >
        {photo && <div className={s.stagePhoto} style={{ backgroundImage: `url("${photo}")` }} aria-hidden />}
        <div className={s.stageTools}>
          <input ref={fileRef} type="file" accept="image/*" hidden onChange={e => { const f = e.target.files?.[0]; if (f) void uploadPhoto(f); e.target.value = '' }} />
          <IconButton label={uploading ? '正在上传…' : '更换专注背景'} size="sm" disabled={uploading} onClick={() => fileRef.current?.click()}>
            <ImagePlus />
          </IconButton>
          {photo && (
            <IconButton label="恢复默认背景" size="sm" onClick={() => st.setBackgroundImage(null)}>
              <ImageMinus />
            </IconButton>
          )}
        </div>

        {quote.data?.content && <p className={s.quote}>{quote.data.content}</p>}

        <div className={s.ringWrap}>
          <svg viewBox="0 0 200 200" className={s.ring} aria-hidden>
            <circle cx="100" cy="100" r="92" className={s.ringTicks} />
            <circle cx="100" cy="100" r="84" className={s.ringTrack} />
            <circle
              cx="100"
              cy="100"
              r="84"
              className={s.ringValue}
              strokeDasharray={2 * Math.PI * 84}
              strokeDashoffset={2 * Math.PI * 84 * (1 - progress)}
            />
          </svg>
          <div className={s.clock} role="timer" aria-live="off" aria-label={`剩余 ${clock(shown)}`}>
            <span className={s.time}>{clock(shown)}</span>
            <span className={s.mode}>
              <i className={s.modeDot} />
              {isBreak ? '休息' : isPaused ? '已暂停' : isRunning ? '专注中' : '准备开始'}
            </span>
          </div>
        </div>

        {active ? (
          <p className={s.task}>{isBreak ? '起来走走，喝口水' : currentTask}</p>
        ) : (
          <div className={s.setup}>
            <Input
              wrapperClassName={s.taskInput}
              size="lg"
              placeholder="临时专注任务"
              aria-label="这次专注做什么"
              value={taskName}
              onChange={e => setTaskName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && start()}
            />
            <div className={s.presets} role="radiogroup" aria-label="专注时长">
              {[15, 25, 45, 60].map(m => (
                <Chip key={m} selected={minutes === m} onClick={() => setMinutes(m)}>
                  {m} 分钟
                </Chip>
              ))}
            </div>
          </div>
        )}

        <div className={s.controls}>
          {!active ? (
            <>
              <Button variant="primary" size="lg" icon={<Play />} className={s.big} onClick={() => start()}>
                开始专注
              </Button>
              <Button variant="secondary" size="lg" icon={<Coffee />} onClick={() => guard() && st.startBreakTimer(breakDuration)}>
                休息 {breakDuration} 分钟
              </Button>
            </>
          ) : (
            <>
              {isRunning ? (
                <Button variant="secondary" size="lg" icon={<Pause />} className={s.big} onClick={st.pauseTimer}>
                  暂停
                </Button>
              ) : (
                <Button variant="primary" size="lg" icon={<Play />} className={s.big} onClick={st.resumeTimer}>
                  继续
                </Button>
              )}
              <Button variant="ghost" size="lg" icon={<Square />} onClick={stop}>
                {isBreak ? '结束休息' : '结束'}
              </Button>
              {isPaused && !isBreak && (
                <Button variant="ghost" size="lg" icon={<RotateCcw />} onClick={() => st.resetTimer()}>
                  放弃这一轮
                </Button>
              )}
            </>
          )}
        </div>

        {coachAttemptId && !active && (
          <Notice tone="ink" icon={<Lightbulb />} className={s.coachNote}>
            这一轮来自教练的建议{suggestedMinutes ? `，建议 ${suggestedMinutes} 分钟` : ''}。结束后结果会自动反馈给教练。
          </Notice>
        )}
      </section>

      <aside className={s.side}>
        <section className={s.panel} aria-labelledby="focus-tasks">
          <div className={s.panelHead}>
            <h2 id="focus-tasks" className={s.panelTitle}>
              专注清单
            </h2>
            <span className={s.panelEnd}>
              <IconButton label="新建清单" size="sm" onClick={() => setSetDialog(true)}>
                <FolderPlus />
              </IconButton>
              <IconButton label="新建任务" size="sm" onClick={() => openEditor('new')}>
                <Plus />
              </IconButton>
            </span>
          </div>
          <div className={s.sets}>
            <Chip selected={activeSet === 'all'} onClick={() => setActiveSet('all')}>
              全部
            </Chip>
            {sets.map(x => (
              <Chip key={x.id} selected={activeSet === x.id} onClick={() => setActiveSet(x.id)}>
                {x.name}
              </Chip>
            ))}
          </div>
          {visibleTasks.length === 0 ? (
            <p className={s.panelEmpty}>把常做的事存成清单，下次一键开始。比如「背 30 个单词 · 25 分钟」。</p>
          ) : (
            <ul className={s.tasks}>
              {visibleTasks.map(t => {
                const stt = statsByName.get(norm(t.title))
                return (
                  <li key={t.id} className={s.taskRow} data-done={t.completed || undefined}>
                    <span className={s.taskSwatch} style={{ '--swatch': t.color } as CSSProperties} aria-hidden />
                    <span className={s.taskRowBody}>
                      <span className={s.taskRowTitle}>{t.title}</span>
                      <span className={s.taskRowMeta}>
                        {t.minutes} 分钟{stt ? ` · 已专注 ${stt.count} 次 · ${Math.round(stt.minutes)} 分钟` : ''}
                      </span>
                    </span>
                    <span className={s.taskRowActions}>
                      <IconButton label={`开始：${t.title}`} size="sm" disabled={active} onClick={() => start(t.title, t.minutes)}>
                        <Play />
                      </IconButton>
                      <IconButton label="编辑" size="sm" onClick={() => openEditor(t)}>
                        <Pencil />
                      </IconButton>
                      <IconButton label="删除" size="sm" onClick={() => setDeleting(t)}>
                        <Trash2 />
                      </IconButton>
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        <section className={s.panel} aria-labelledby="focus-stats">
          <div className={s.panelHead}>
            <h2 id="focus-stats" className={s.panelTitle}>
              专注记录
            </h2>
            <span className={s.panelEnd}>
              <Segmented
                size="sm"
                ariaLabel="统计范围"
                value={range}
                onChange={setRange}
                options={[
                  { value: 'day', label: '今天' },
                  { value: 'week', label: '本周' },
                  { value: 'all', label: '全部' },
                ]}
              />
            </span>
          </div>
          <div className={s.statsBody}>
            <div className={s.statLine}>
              <span className={s.statCell}>
                <b>{stats.todayCount}</b>
                <span>今天 · 个</span>
              </span>
              <span className={s.statCell}>
                <b>{Math.round(stats.weekMinutes)}</b>
                <span>本周 · 分钟</span>
              </span>
              <span className={s.statCell}>
                <b>{cumulative.totalHours}</b>
                <span>累计 · 小时</span>
              </span>
            </div>
            <div className={s.bars} role="img" aria-label="本周每天专注分钟">
              {stats.weeklyData.map((d, i) => (
                <span key={d.date} className={s.barCol}>
                  <span
                    className={s.bar}
                    data-on={d.minutes > 0 || undefined}
                    data-today={d.date === todayIso || undefined}
                    title={`${d.date} · ${Math.round(d.minutes)} 分钟`}
                    style={{ height: `${Math.max(4, (d.minutes / maxDay) * 100)}%`, '--i': i } as CSSProperties}
                  />
                  <span className={s.barLabel}>{'日一二三四五六'[new Date(`${d.date}T00:00:00`).getDay()]}</span>
                </span>
              ))}
            </div>
            {distribution.length > 0 && (
              <ul className={s.dist}>
                {distribution.map(d => (
                  <li key={d.taskName} className={s.distRow}>
                    <span className={s.distName}>{d.taskName}</span>
                    <span className={s.distVal}>
                      {Math.round(d.minutes)} 分钟 · {d.percentage}%
                    </span>
                    <span className={s.distTrack}>
                      <span className={s.distFill} style={{ width: `${d.percentage}%`, display: 'block' }} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </aside>

      <Dialog
        open={stopOpen}
        onOpenChange={setStopOpen}
        width={28}
        title="这一轮为什么停下？"
        description="如实选一个就好，它只用来理解你的专注节奏，不是在打分。"
        footer={
          <>
            <Button variant="ghost" onClick={() => setStopOpen(false)}>
              继续专注
            </Button>
            <Button variant="primary" onClick={confirmStop}>
              结束这一轮
            </Button>
          </>
        }
      >
        <RadioCards ariaLabel="停止原因" value={stopReason} onValueChange={setStopReason} options={STOP_REASONS} />
      </Dialog>

      <Dialog
        open={editing !== null}
        onOpenChange={v => !v && setEditing(null)}
        width={28}
        title={editing === 'new' ? '新建专注任务' : '编辑专注任务'}
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              取消
            </Button>
            <Button variant="primary" onClick={saveTask}>
              保存
            </Button>
          </>
        }
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Field label="任务名称" htmlFor="ft-title">
            <Input id="ft-title" value={form.title} placeholder="例如：英语单词、计算机网络" onChange={e => setForm({ ...form, title: e.target.value })} autoFocus />
          </Field>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Field label="时长（分钟）" htmlFor="ft-min">
              <Input id="ft-min" type="number" min={1} max={120} value={form.minutes} onChange={e => setForm({ ...form, minutes: Number(e.target.value) })} />
            </Field>
            <Field label="清单">
              <Select ariaLabel="所属清单" value={form.setId} onValueChange={v => setForm({ ...form, setId: v })} options={sets.map(x => ({ value: x.id, label: x.name }))} />
            </Field>
          </div>
          <Field label="颜色">
            <div className={s.swatches} role="radiogroup" aria-label="颜色">
              {SWATCHES.map(c => (
                <button
                  key={c}
                  type="button"
                  role="radio"
                  aria-checked={form.color === c}
                  aria-label={`颜色 ${SWATCHES.indexOf(c) + 1}`}
                  className={s.swatch}
                  style={{ '--swatch': c } as CSSProperties}
                  onClick={() => setForm({ ...form, color: c })}
                />
              ))}
            </div>
          </Field>
        </div>
      </Dialog>

      <Dialog
        open={setDialog}
        onOpenChange={setSetDialog}
        width={24}
        title="新建清单"
        footer={
          <>
            <Button variant="ghost" onClick={() => setSetDialog(false)}>
              取消
            </Button>
            <Button variant="primary" onClick={addSet} disabled={!newSet.trim()}>
              创建
            </Button>
          </>
        }
      >
        <Field label="清单名称" htmlFor="ft-set">
          <Input id="ft-set" autoFocus value={newSet} placeholder="例如：期末复习、英语学习" onChange={e => setNewSet(e.target.value)} onKeyDown={e => e.key === 'Enter' && addSet()} />
        </Field>
      </Dialog>

      <Confirm
        open={!!deleting}
        onOpenChange={v => !v && setDeleting(null)}
        tone="danger"
        title="删除这个专注任务？"
        description={`「${deleting?.title ?? ''}」会从清单里移除，已有的专注记录不会删除。`}
        confirmLabel="删除"
        onConfirm={() => {
          if (deleting) setTasks(prev => prev.filter(t => t.id !== deleting.id))
        }}
      />
    </div>
  )
}
