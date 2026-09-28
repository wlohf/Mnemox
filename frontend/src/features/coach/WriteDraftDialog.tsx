import { Plus, ShieldCheck, Trash2 } from 'lucide-react'
import { Badge, Button, Dialog, Field, IconButton, Input, Select, Textarea } from '../../ui'
import type { AgentWriteDraftResponse } from '../../services/agentApi'
import s from './coach.module.css'

type Item = { title?: string; task_type?: string; planned_date?: string; duplicate?: boolean; [k: string]: unknown }

const TASK_TYPES = [
  { value: 'learn', label: '学习' },
  { value: 'review', label: '复习' },
  { value: 'practice', label: '练习' },
  { value: 'summarize', label: '总结' },
]
const NOTE_TYPES = [
  { value: 'general', label: '普通' },
  { value: 'idea', label: '灵感' },
  { value: 'method', label: '方法' },
  { value: 'summary', label: '总结' },
  { value: 'question', label: '问题' },
  { value: 'resource', label: '资料' },
]

const TITLE: Record<string, string> = {
  create_note: '确认创建笔记',
  add_daily_plan_items: '确认加入当天计划',
  create_goal_tasks: '确认创建目标与任务',
}

export function WriteDraftDialog({
  draft,
  busy,
  onChange,
  onConfirm,
  onCancel,
}: {
  draft: AgentWriteDraftResponse | null
  busy: boolean
  onChange: (next: AgentWriteDraftResponse) => void
  onConfirm: () => void
  onCancel: () => void
}) {
  if (!draft) return null
  const d = draft.draft as Record<string, unknown>
  const patch = (p: Record<string, unknown>) => onChange({ ...draft, draft: { ...draft.draft, ...p } })
  const listField = draft.intent === 'add_daily_plan_items' ? 'items' : 'tasks'
  const list = (Array.isArray(d[listField]) ? d[listField] : []) as Item[]
  const setItem = (i: number, p: Partial<Item>) => {
    const next = [...list]
    next[i] = { ...next[i], ...p, duplicate: false }
    patch({ [listField]: next })
  }
  const removeItem = (i: number) => patch({ [listField]: list.filter((_, j) => j !== i) })
  const addItem = () =>
    patch({ [listField]: [...list, { title: '', task_type: 'learn', planned_date: typeof d.date === 'string' ? d.date : undefined }] })

  const invalid =
    draft.intent === 'create_note'
      ? !String(d.content ?? '').trim()
      : !list.some(it => String(it.title ?? '').trim())

  return (
    <Dialog
      open
      onOpenChange={v => !v && !busy && onCancel()}
      width={42}
      title={TITLE[draft.intent] ?? '确认写入'}
      description={draft.summary || '教练已经起草好了，请核对后再写入。你可以直接修改草案。'}
      footerStart={
        <span className={s.writeGuard}>
          <ShieldCheck aria-hidden />
          只有用户确认后才允许写入。
        </span>
      }
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            取消
          </Button>
          <Button variant="primary" loading={busy} disabled={invalid} onClick={onConfirm}>
            确认写入
          </Button>
        </>
      }
    >
      {(draft.duplicate_warnings ?? []).length > 0 && (
        <div className={s.draftWarnings}>
          {draft.duplicate_warnings!.map(w => (
            <Badge key={w} tone={w.includes('跳过') ? 'warning' : 'ink'}>
              {w}
            </Badge>
          ))}
        </div>
      )}

      {draft.intent === 'create_note' ? (
        <div className={s.draftFields}>
          <div className={s.draftRow}>
            <Field label="标题" htmlFor="wd-title">
              <Input id="wd-title" value={String(d.title ?? '')} placeholder="对话笔记" onChange={e => patch({ title: e.target.value })} />
            </Field>
            <Field label="类型">
              <Select
                ariaLabel="笔记类型"
                value={String(d.note_type ?? 'general')}
                onValueChange={v => patch({ note_type: v })}
                options={NOTE_TYPES}
              />
            </Field>
          </div>
          <Field label="标签" hint="用逗号分隔，最多 6 个" optional htmlFor="wd-tags">
            <Input
              id="wd-tags"
              value={((d.tags as string[] | undefined) ?? []).join('，')}
              onChange={e =>
                patch({
                  tags: e.target.value
                    .split(/[,，\s]+/)
                    .map(t => t.trim())
                    .filter(Boolean)
                    .slice(0, 6),
                })
              }
            />
          </Field>
          <Field label="内容" htmlFor="wd-content" error={invalid ? '笔记内容不能为空' : undefined}>
            <Textarea id="wd-content" reading autoGrow maxHeight={320} value={String(d.content ?? '')} onChange={e => patch({ content: e.target.value })} />
          </Field>
        </div>
      ) : (
        <div className={s.draftFields}>
          {draft.intent === 'add_daily_plan_items' ? (
            <Field label="日期" htmlFor="wd-date" aside={d.existing_plan_id ? <Badge tone="ink">追加到已有计划</Badge> : undefined}>
              <Input id="wd-date" type="date" value={String(d.date ?? '')} onChange={e => patch({ date: e.target.value })} />
            </Field>
          ) : (
            <Field label="目标" htmlFor="wd-goal" aside={d.existing_goal_id ? <Badge tone="ink">复用已有目标</Badge> : undefined}>
              <Input id="wd-goal" value={String(d.goal_title ?? '')} placeholder="学习目标" onChange={e => patch({ goal_title: e.target.value })} />
            </Field>
          )}
          <Field label={draft.intent === 'add_daily_plan_items' ? '计划项' : '任务'} error={invalid ? '至少保留一项' : undefined}>
            <ul className={s.itemList}>
              {list.map((it, i) => (
                <li key={i} className={s.item} data-duplicate={it.duplicate || undefined}>
                  <Input
                    size="sm"
                    value={String(it.title ?? '')}
                    placeholder="标题"
                    aria-label={`第 ${i + 1} 项标题`}
                    onChange={e => setItem(i, { title: e.target.value })}
                  />
                  <Select size="sm" ariaLabel="类型" value={it.task_type || 'learn'} onValueChange={v => setItem(i, { task_type: v })} options={TASK_TYPES} />
                  <Input
                    size="sm"
                    type="date"
                    aria-label="日期"
                    value={String(it.planned_date ?? d.date ?? '')}
                    onChange={e => setItem(i, { planned_date: e.target.value })}
                  />
                  <IconButton label="删除这一项" size="sm" onClick={() => removeItem(i)}>
                    <Trash2 />
                  </IconButton>
                </li>
              ))}
            </ul>
          </Field>
          <Button variant="ghost" size="sm" icon={<Plus />} onClick={addItem} style={{ alignSelf: 'flex-start' }}>
            添加一项
          </Button>
        </div>
      )}
    </Dialog>
  )
}
