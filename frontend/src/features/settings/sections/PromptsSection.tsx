import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCcw } from 'lucide-react'
import { Badge, Button, Confirm, Empty, Skeleton, Textarea, toast } from '../../../ui'
import { listPrompts, resetPrompt, updatePrompt } from '../../../services/promptApi'
import { settingsStyles as s } from '../SettingsDialog'

export const PROMPT_MODES: Record<string, { desc: string; variables?: string[] }> = {
  coach: { desc: '主对话的教练人格，所有对话都会带上它。' },
  feynman: { desc: '你用自己的话解释一个知识点时，教练如何评估。', variables: ['{knowledge_point}', '{user_explanation}'] },
  socratic: { desc: '苏格拉底式追问，引导你往深处想。', variables: ['{topic}', '{user_response}'] },
  review: { desc: '复习时如何提问，检验你对知识点的记忆。', variables: ['{knowledge_points}'] },
  quiz: { desc: '根据学习资料出练习题。', variables: ['{material_content}', '{num_questions}'] },
  error: { desc: '分析一道错题为什么错。', variables: ['{question}', '{correct_answer}', '{user_answer}'] },
  summary: { desc: '帮你提炼今天学了什么。', variables: ['{session_content}'] },
  explain: { desc: '用大白话讲清一个复杂概念。', variables: ['{content}'] },
  distracted_care: { desc: '专注因为状态不好中断时，教练用什么语气回应。' },
  okr: { desc: '把学习目标拆解成可执行的任务。', variables: ['{goal_description}', '{material_info}', '{deadline}'] },
}

export function PromptsSection({ initialKey }: { initialKey?: string }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['prompts'], queryFn: listPrompts })
  const templates = q.data?.templates ?? []
  const [key, setKey] = useState<string>(initialKey ?? '')
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [pendingKey, setPendingKey] = useState<string | null>(null)
  const current = templates.find(t => t.mode_key === key) ?? templates[0]

  useEffect(() => {
    if (!current) return
    if (!key) setKey(current.mode_key)
    setText(current.content)
  }, [current?.mode_key, current?.content])

  if (q.isLoading) return <Skeleton height={320} radius={12} />
  if (!current) return <Empty title="提示词没能加载" body="请确认本地服务已启动后重新打开设置。" />

  const dirty = text !== current.content
  const info = PROMPT_MODES[current.mode_key] ?? { desc: '' }

  const save = async () => {
    setSaving(true)
    const ok = await updatePrompt(current.mode_key, text)
    setSaving(false)
    if (!ok) {
      toast.error('保存失败')
      return
    }
    toast.success(`「${current.name}」已保存`)
    await qc.invalidateQueries({ queryKey: ['prompts'] })
  }

  return (
    <div className={s.prompts}>
      <div className={s.promptList} role="listbox" aria-label="学习场景">
        {templates.map(t => (
          <button
            key={t.mode_key}
            type="button"
            role="option"
            aria-selected={t.mode_key === current.mode_key}
            className={s.promptItem}
            onClick={() => (dirty ? setPendingKey(t.mode_key) : setKey(t.mode_key))}
          >
            {t.name}
            {t.is_custom && <i aria-label="已自定义" />}
          </button>
        ))}
      </div>
      <div className={s.stack}>
        <div className={s.actions}>
          <strong style={{ fontSize: 'var(--mx-type-ui)' }}>{current.name}</strong>
          {current.is_custom ? <Badge tone="ink">已自定义</Badge> : <Badge>系统默认</Badge>}
          {dirty && <Badge tone="warning">未保存</Badge>}
        </div>
        <p className={s.groupDesc} style={{ margin: 0 }}>
          {info.desc}
        </p>
        {info.variables && info.variables.length > 0 && (
          <div className={s.vars}>
            <span style={{ color: 'var(--mx-text-3)', fontSize: 'var(--mx-type-caption)' }}>可用变量</span>
            {info.variables.map(v => (
              <code key={v}>{v}</code>
            ))}
          </div>
        )}
        <Textarea className={s.promptEditor} value={text} onChange={e => setText(e.target.value)} rows={14} aria-label={`${current.name}提示词`} />
        <div className={s.actions}>
          <Button variant="primary" loading={saving} disabled={!dirty} onClick={() => void save()}>
            保存
          </Button>
          {dirty && (
            <Button variant="ghost" onClick={() => setText(current.content)}>
              撤销修改
            </Button>
          )}
          <span style={{ flex: 1 }} />
          {current.is_custom && (
            <Button variant="ghost" icon={<RotateCcw />} onClick={() => setResetting(true)}>
              恢复默认
            </Button>
          )}
        </div>
        <span style={{ color: 'var(--mx-text-3)', fontSize: 'var(--mx-type-caption)' }}>
          {current.updated_at ? `上次修改：${new Date(current.updated_at).toLocaleString('zh-CN', { hour12: false })}` : '使用系统默认提示词'}
        </span>
      </div>
      <Confirm
        open={resetting}
        onOpenChange={setResetting}
        title={`把「${current.name}」恢复为默认？`}
        description="你的自定义版本会被删除。"
        confirmLabel="恢复默认"
        onConfirm={async () => {
          const ok = await resetPrompt(current.mode_key)
          if (!ok) {
            toast.error('恢复失败')
            throw new Error('reset failed')
          }
          toast.success('已恢复默认')
          await qc.invalidateQueries({ queryKey: ['prompts'] })
        }}
      />
      <Confirm
        open={pendingKey !== null}
        onOpenChange={v => !v && setPendingKey(null)}
        title="放弃未保存的修改？"
        description="切换到其他场景会丢掉当前编辑的内容。"
        confirmLabel="放弃并切换"
        onConfirm={() => {
          if (pendingKey) setKey(pendingKey)
          setPendingKey(null)
        }}
      />
    </div>
  )
}
