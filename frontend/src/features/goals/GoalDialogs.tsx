import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CircleCheck, CircleDashed, ClipboardCheck, Lightbulb, Plus, Trash2 } from 'lucide-react'
import { Button, Dialog, Field, IconButton, Input, Notice, Select, Skeleton, Textarea, toast } from '../../ui'
import type { OfflineGoalItem } from '../../hooks/useOfflineGoals'
import type { OfflineGoalTaskItem } from '../../hooks/useOfflineGoalTasks'
import { listMaterials, listMaterialChapters } from '../../services/materialApi'
import { createGoalPlan, createGoalTask } from '../../services/goalApi'
import { evaluateTaskOutput, type OutputEvalResult } from '../../services/learningApi'
import { getApiErrorMessage } from '../../services/apiClient'
import { qk } from '../../app/queryClient'
import { TASK_TYPES, taskTypeLabel } from './taskTree'
import s from './goals.module.css'

const NO_MATERIAL = '__none__'
const NO_PARENT = '__root__'

/* ============================================================================
   Goal — create or edit
   ========================================================================== */
export interface GoalDraft {
  title: string
  description?: string
  deadline?: string
  material_id?: number
}

export function GoalDialog({
  open,
  onOpenChange,
  goal,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  goal?: OfflineGoalItem | null
  onSubmit: (draft: GoalDraft) => Promise<void>
}) {
  const editing = Boolean(goal)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [deadline, setDeadline] = useState('')
  const [material, setMaterial] = useState(NO_MATERIAL)
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const materials = useQuery({
    queryKey: qk.materials,
    queryFn: () => listMaterials(500),
    enabled: open && !editing,
    staleTime: 60_000,
  })

  useEffect(() => {
    if (!open) return
    setTitle(goal?.title ?? '')
    setDescription(goal?.description ?? '')
    setDeadline(goal?.deadline?.slice(0, 10) ?? '')
    setMaterial(NO_MATERIAL)
    setTouched(false)
  }, [open, goal])

  const invalid = touched && !title.trim()
  const submit = async () => {
    setTouched(true)
    if (!title.trim()) return
    setBusy(true)
    try {
      await onSubmit({
        title: title.trim(),
        description: description.trim() || undefined,
        deadline: deadline || undefined,
        material_id: material !== NO_MATERIAL ? Number(material) : undefined,
      })
      onOpenChange(false)
    } catch (error) {
      toast.error(getApiErrorMessage(error, editing ? '保存目标失败' : '创建目标失败'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={editing ? '编辑目标' : '新建目标'}
      description={editing ? undefined : '一个目标对应一段有截止日期的学习。绑定资料后，可以按章节自动排出每周任务。'}
      width={34}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button variant="primary" loading={busy} onClick={() => void submit()}>
            {editing ? '保存' : '创建目标'}
          </Button>
        </>
      }
    >
      <form
        className={s.form}
        onSubmit={e => {
          e.preventDefault()
          void submit()
        }}
      >
        <Field label="目标" htmlFor="goal-title" error={invalid ? '请写下目标是什么' : undefined}>
          <Input
            id="goal-title"
            autoFocus
            value={title}
            invalid={invalid}
            placeholder="例如：六级阅读稳定在 200 分以上"
            onChange={e => setTitle(e.target.value)}
          />
        </Field>
        <Field label="为什么 / 达成标准" htmlFor="goal-desc" optional hint="写清楚怎样算完成，教练会据此判断进度。">
          <Textarea
            id="goal-desc"
            autoGrow
            maxHeight={200}
            rows={2}
            value={description}
            placeholder="例如：能在 40 分钟内做完一套阅读，错题不超过 5 道"
            onChange={e => setDescription(e.target.value)}
          />
        </Field>
        <div className={s.formRow}>
          <Field label="截止日期" htmlFor="goal-deadline" optional>
            <Input id="goal-deadline" type="date" value={deadline} onChange={e => setDeadline(e.target.value)} />
          </Field>
          {!editing && (
            <Field label="学习资料" optional htmlFor="goal-material">
              {materials.isLoading ? (
                <Skeleton height={36} radius={7} />
              ) : (
                <Select
                  id="goal-material"
                  ariaLabel="学习资料"
                  value={material}
                  onValueChange={setMaterial}
                  options={[
                    { value: NO_MATERIAL, label: '暂不绑定' },
                    ...(materials.data ?? []).map(m => ({ value: String(m.id), label: m.title })),
                  ]}
                />
              )}
            </Field>
          )}
        </div>
        <button type="submit" hidden aria-hidden tabIndex={-1} />
      </form>
    </Dialog>
  )
}

/* ============================================================================
   Task / milestone — create or edit
   ========================================================================== */
export interface TaskDraft {
  title: string
  task_type: string
  planned_date?: string
  parent_task_id: number | null
  description?: string
}

export function TaskDialog({
  open,
  onOpenChange,
  mode,
  task,
  parentId,
  tasks,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  mode: 'task' | 'milestone'
  task?: OfflineGoalTaskItem | null
  parentId?: number | null
  tasks: OfflineGoalTaskItem[]
  onSubmit: (draft: TaskDraft) => Promise<void>
}) {
  const editing = Boolean(task)
  const isMilestone = mode === 'milestone'
  const [title, setTitle] = useState('')
  const [type, setType] = useState('learn')
  const [date, setDate] = useState('')
  const [parent, setParent] = useState(NO_PARENT)
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setTitle(task?.title ?? '')
    setType(task?.task_type && task.task_type !== 'milestone' ? task.task_type : 'learn')
    setDate(task?.planned_date?.slice(0, 10) ?? '')
    const p = task ? task.parent_task_id : parentId
    setParent(p != null ? String(p) : NO_PARENT)
    setTouched(false)
  }, [open, task, parentId])

  // Only synced tasks have the server id a parent link needs; never offer
  // the task itself or its own descendants as its parent.
  const parentOptions = useMemo(() => {
    if (isMilestone) return []
    const blocked = new Set<number>()
    if (task?._serverId != null) {
      blocked.add(task._serverId)
      let grew = true
      while (grew) {
        grew = false
        for (const t of tasks) {
          if (t._serverId != null && t.parent_task_id != null && blocked.has(t.parent_task_id) && !blocked.has(t._serverId)) {
            blocked.add(t._serverId)
            grew = true
          }
        }
      }
    }
    return tasks
      .filter(t => t._serverId != null && !blocked.has(t._serverId))
      .map(t => ({ value: String(t._serverId), label: `${taskTypeLabel(t.task_type)} · ${t.title}` }))
  }, [isMilestone, task, tasks])

  const invalid = touched && !title.trim()
  const submit = async () => {
    setTouched(true)
    if (!title.trim()) return
    setBusy(true)
    try {
      await onSubmit({
        title: title.trim(),
        task_type: isMilestone ? 'milestone' : type,
        planned_date: date || undefined,
        parent_task_id: isMilestone || parent === NO_PARENT ? null : Number(parent),
      })
      onOpenChange(false)
    } catch (error) {
      toast.error(getApiErrorMessage(error, '保存失败'))
    } finally {
      setBusy(false)
    }
  }

  const heading = isMilestone ? (editing ? '编辑里程碑' : '添加里程碑') : editing ? '编辑任务' : '添加任务'

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={heading}
      description={isMilestone && !editing ? '里程碑是目标里的一个阶段，比如「读完第 1–3 章」。任务可以挂在它下面。' : undefined}
      width={32}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button variant="primary" loading={busy} onClick={() => void submit()}>
            {editing ? '保存' : '添加'}
          </Button>
        </>
      }
    >
      <form
        className={s.form}
        onSubmit={e => {
          e.preventDefault()
          void submit()
        }}
      >
        <Field label={isMilestone ? '阶段' : '任务'} htmlFor="task-title" error={invalid ? '标题不能为空' : undefined}>
          <Input
            id="task-title"
            autoFocus
            value={title}
            invalid={invalid}
            placeholder={isMilestone ? '例如：词汇量提升到 5000' : '例如：精读 Unit 3，划出 10 个生词'}
            onChange={e => setTitle(e.target.value)}
          />
        </Field>
        {isMilestone ? (
          <Field label="目标日期" htmlFor="task-date" optional>
            <Input id="task-date" type="date" value={date} onChange={e => setDate(e.target.value)} />
          </Field>
        ) : (
          <>
            <div className={s.formRow}>
              <Field label="类型" htmlFor="task-type">
                <Select id="task-type" ariaLabel="任务类型" value={type} onValueChange={setType} options={TASK_TYPES} />
              </Field>
              <Field label="计划日期" htmlFor="task-date" optional>
                <Input id="task-date" type="date" value={date} onChange={e => setDate(e.target.value)} />
              </Field>
            </div>
            <Field label="放在" htmlFor="task-parent" hint={parentOptions.length === 0 ? '同步完成的里程碑和任务才能作为上级。' : undefined}>
              <Select
                id="task-parent"
                ariaLabel="上级"
                value={parent}
                onValueChange={setParent}
                options={[{ value: NO_PARENT, label: '直接放在目标下' }, ...parentOptions]}
              />
            </Field>
          </>
        )}
        <button type="submit" hidden aria-hidden tabIndex={-1} />
      </form>
    </Dialog>
  )
}

/* ============================================================================
   Plan — weekly auto-generation for material goals, manual batch otherwise
   ========================================================================== */
interface ManualRow {
  id: string
  title: string
  task_type: string
  planned_date: string
}

const newRow = (): ManualRow => ({
  id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  title: '',
  task_type: 'learn',
  planned_date: '',
})

export function PlanDialog({
  open,
  onOpenChange,
  goal,
  onDone,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  goal: OfflineGoalItem | null
  onDone: () => void
}) {
  const goalId = goal?._serverId ?? null
  const materialId = goal?.material_id ?? null
  const [days, setDays] = useState('14')
  const [perWeek, setPerWeek] = useState('5')
  const [chapter, setChapter] = useState(NO_PARENT)
  const [rows, setRows] = useState<ManualRow[]>([newRow()])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const chapters = useQuery({
    queryKey: ['materials', materialId, 'chapters'],
    queryFn: () => listMaterialChapters(materialId!),
    enabled: open && materialId != null,
    staleTime: 5 * 60_000,
  })

  useEffect(() => {
    if (!open) return
    setDays('14')
    setPerWeek('5')
    setChapter(NO_PARENT)
    setRows([newRow()])
    setNote('')
  }, [open])

  const daysN = Number(days)
  const perWeekN = Number(perWeek)
  const daysBad = !Number.isInteger(daysN) || daysN < 1 || daysN > 365
  const perWeekBad = !Number.isInteger(perWeekN) || perWeekN < 1 || perWeekN > 7

  const submit = async () => {
    if (!goalId) {
      toast.warning('目标还没同步到服务器，稍后再试')
      return
    }
    setBusy(true)
    try {
      if (materialId) {
        if (daysBad || perWeekBad) return
        const r = await createGoalPlan(goalId, {
          total_days: daysN,
          current_chapter_id: chapter !== NO_PARENT ? Number(chapter) : null,
          study_days_per_week: perWeekN,
        })
        toast.success('学习计划已设定', { description: `生成了 ${r.generated_tasks} 个本周任务` })
      } else {
        const filled = rows.map(r => ({ ...r, title: r.title.trim() })).filter(r => r.title)
        if (filled.length === 0) {
          toast.warning('至少写一条任务')
          return
        }
        await Promise.all(
          filled.map(r =>
            createGoalTask(goalId, {
              title: r.title,
              description: note.trim() || undefined,
              task_type: r.task_type,
              planned_date: r.planned_date || undefined,
            }),
          ),
        )
        toast.success(`已添加 ${filled.length} 条任务`)
      }
      onDone()
      onOpenChange(false)
    } catch (error) {
      toast.error(getApiErrorMessage(error, '设定学习计划失败'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="制定学习计划"
      description={
        materialId
          ? `按「${goal?.material_title ?? '绑定的资料'}」的章节，把目标拆成每周的学习任务。`
          : '这个目标没有绑定资料，可以一次写下几条任务，分别设好类型和日期。'
      }
      width={materialId ? 32 : 40}
      footerStart={
        <span className={s.planNote}>
          {materialId ? '之后每周可以一键生成下一周的任务。' : '以后绑定资料，就能按章节自动排任务。'}
        </span>
      }
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button variant="primary" loading={busy} disabled={Boolean(materialId) && (daysBad || perWeekBad)} onClick={() => void submit()}>
            {materialId ? '生成本周任务' : '添加这些任务'}
          </Button>
        </>
      }
    >
      {materialId ? (
        <div className={s.form}>
          <div className={s.formRow}>
            <Field label="计划用多少天学完" htmlFor="plan-days" error={daysBad ? '1–365 天' : undefined}>
              <Input
                id="plan-days"
                type="number"
                inputMode="numeric"
                min={1}
                max={365}
                value={days}
                invalid={daysBad}
                suffix="天"
                onChange={e => setDays(e.target.value)}
              />
            </Field>
            <Field label="每周学几天" htmlFor="plan-week" error={perWeekBad ? '1–7 天' : undefined} hint="周末会自动跳过">
              <Input
                id="plan-week"
                type="number"
                inputMode="numeric"
                min={1}
                max={7}
                value={perWeek}
                invalid={perWeekBad}
                suffix="天/周"
                onChange={e => setPerWeek(e.target.value)}
              />
            </Field>
          </div>
          <Field label="从哪一章开始" htmlFor="plan-chapter" optional>
            {chapters.isLoading ? (
              <Skeleton height={36} radius={7} />
            ) : chapters.isError ? (
              <Notice tone="warning">章节没能加载，将从第一章开始。</Notice>
            ) : (
              <Select
                id="plan-chapter"
                ariaLabel="起始章节"
                value={chapter}
                onValueChange={setChapter}
                options={[{ value: NO_PARENT, label: '从第一章开始' }, ...(chapters.data ?? []).map(c => ({ value: String(c.id), label: c.title }))]}
              />
            )}
          </Field>
        </div>
      ) : (
        <div className={s.form}>
          <ul className={s.manualList}>
            {rows.map((r, i) => (
              <li key={r.id} className={s.manualRow}>
                <Input
                  size="sm"
                  autoFocus={i === 0}
                  aria-label={`第 ${i + 1} 条任务`}
                  placeholder="例如：六级听力精听 1 套"
                  value={r.title}
                  onChange={e => setRows(prev => prev.map(x => (x.id === r.id ? { ...x, title: e.target.value } : x)))}
                />
                <Select
                  size="sm"
                  ariaLabel="类型"
                  value={r.task_type}
                  onValueChange={v => setRows(prev => prev.map(x => (x.id === r.id ? { ...x, task_type: v } : x)))}
                  options={TASK_TYPES}
                />
                <Input
                  size="sm"
                  type="date"
                  aria-label="计划日期"
                  value={r.planned_date}
                  onChange={e => setRows(prev => prev.map(x => (x.id === r.id ? { ...x, planned_date: e.target.value } : x)))}
                />
                <IconButton
                  label="删除这一条"
                  size="sm"
                  disabled={rows.length <= 1}
                  onClick={() => setRows(prev => prev.filter(x => x.id !== r.id))}
                >
                  <Trash2 />
                </IconButton>
              </li>
            ))}
          </ul>
          <Button variant="ghost" size="sm" icon={<Plus />} style={{ alignSelf: 'flex-start' }} onClick={() => setRows(prev => [...prev, newRow()])}>
            再加一条
          </Button>
          <Field label="统一备注" htmlFor="plan-note" optional>
            <Input id="plan-note" value={note} placeholder="例如：本周重点练听力细节" onChange={e => setNote(e.target.value)} />
          </Field>
        </div>
      )}
    </Dialog>
  )
}

/* ============================================================================
   Output evaluation — finishing a task means showing what you learned
   ========================================================================== */
const DEFAULT_RUBRIC = '准确性、结构清晰、覆盖关键点、可复述性'
const PASS_SCORE = 80

export function EvalDialog({
  open,
  onOpenChange,
  task,
  onEvaluated,
  onSkip,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  task: OfflineGoalTaskItem | null
  /** Called after grading; passed tells whether the task now counts as done. */
  onEvaluated: (result: OutputEvalResult, passed: boolean) => Promise<void> | void
  /** Mark done without an evaluation. */
  onSkip: () => Promise<void> | void
}) {
  const [output, setOutput] = useState('')
  const [rubric, setRubric] = useState(DEFAULT_RUBRIC)
  const [result, setResult] = useState<OutputEvalResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [skipping, setSkipping] = useState(false)

  useEffect(() => {
    if (!open) return
    setOutput('')
    setRubric(DEFAULT_RUBRIC)
    setResult(null)
  }, [open, task?._localId])

  const canEvaluate = task?._serverId != null
  const submit = async () => {
    if (!task?._serverId) return
    if (!output.trim()) {
      toast.warning('先写下这次的学习产出')
      return
    }
    setBusy(true)
    try {
      const r = await evaluateTaskOutput({
        task_id: task._serverId,
        output_text: output,
        rubric: rubric.trim() || DEFAULT_RUBRIC,
        mark_task_completed: true,
      })
      setResult(r)
      await onEvaluated(r, r.score >= PASS_SCORE)
    } catch (error) {
      toast.error(getApiErrorMessage(error, '评估失败，请稍后重试'))
    } finally {
      setBusy(false)
    }
  }

  const skip = async () => {
    setSkipping(true)
    try {
      await onSkip()
      onOpenChange(false)
    } finally {
      setSkipping(false)
    }
  }

  const passed = result ? result.score >= PASS_SCORE : false

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={result ? '评估结果' : '完成前，讲讲你学到了什么'}
      description={
        result
          ? undefined
          : '用自己的话写下这次的产出：要点、推导、例子都可以。AI 会按标准打分，80 分以上记为完成。'
      }
      width={38}
      footerStart={
        !result && (
          <Button variant="ghost" size="sm" loading={skipping} onClick={() => void skip()}>
            跳过评估，直接完成
          </Button>
        )
      }
      footer={
        result ? (
          <>
            {!passed && (
              <Button variant="ghost" onClick={() => setResult(null)}>
                改一改再评
              </Button>
            )}
            <Button variant="primary" onClick={() => onOpenChange(false)}>
              {passed ? '好' : '先继续学'}
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              取消
            </Button>
            <Button variant="primary" icon={<ClipboardCheck />} loading={busy} disabled={!canEvaluate} onClick={() => void submit()}>
              开始评估
            </Button>
          </>
        )
      }
    >
      {task && (
        <div className={s.evalTask}>
          <CircleDashed aria-hidden />
          <strong title={task.title}>{task.title}</strong>
        </div>
      )}
      {!canEvaluate && !result && (
        <Notice tone="warning" title="这个任务还没同步">
          同步完成后才能评估。也可以先跳过评估直接完成。
        </Notice>
      )}
      {result ? (
        <div aria-live="polite">
          <div className={s.grade}>
            <div className={s.score}>
              <strong>{result.score}</strong>
              <span>/ 100</span>
            </div>
            <p className={s.gradeText}>
              {passed ? '讲清楚了。任务已记为完成，这次产出也会计入资料进度。' : `离 ${PASS_SCORE} 分还差一点。任务保持进行中，补上缺口再评一次。`}
            </p>
            <span
              className={s.seal}
              style={{ ['--seal' as string]: passed ? 'var(--mx-success)' : 'var(--mx-warning)' }}
              aria-label={`结论：${result.verdict}`}
            >
              {result.verdict}
            </span>
          </div>
          <div className={s.feedback}>
            <FeedbackGroup kind="good" icon={<CircleCheck />} title="做得好的" items={result.strengths} />
            <FeedbackGroup kind="gap" icon={<CircleDashed />} title="还缺的" items={result.gaps} />
            <FeedbackGroup kind="next" icon={<Lightbulb />} title="下一步" items={result.next_actions} />
          </div>
        </div>
      ) : (
        <div className={s.form}>
          <Field label="我的产出" htmlFor="eval-output">
            <Textarea
              id="eval-output"
              reading
              autoGrow
              rows={6}
              maxHeight={360}
              value={output}
              disabled={!canEvaluate}
              placeholder="例如：费曼复盘的关键是用初学者能懂的话讲一遍。讲不顺的地方，就是理解的缺口……"
              onChange={e => setOutput(e.target.value)}
            />
          </Field>
          <Field label="评估标准" htmlFor="eval-rubric" hint="用逗号分隔几个维度">
            <Input id="eval-rubric" value={rubric} disabled={!canEvaluate} onChange={e => setRubric(e.target.value)} />
          </Field>
        </div>
      )}
    </Dialog>
  )
}

function FeedbackGroup({ kind, icon, title, items }: { kind: 'good' | 'gap' | 'next'; icon: React.ReactNode; title: string; items: string[] }) {
  if (!items?.length) return null
  return (
    <section className={s.feedbackGroup} data-kind={kind}>
      <h3>
        {icon}
        {title}
      </h3>
      <ul>
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </section>
  )
}
