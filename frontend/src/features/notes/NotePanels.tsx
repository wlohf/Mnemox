import { useState, type RefObject } from 'react'
import { useNavigate } from 'react-router-dom'
import { BookOpenCheck, Copy, FolderSync, ListPlus, MessageSquareText, Sparkles, Upload, X } from 'lucide-react'
import { Badge, Button, Dialog, Field, IconButton, Input, Notice, Segmented, Textarea, toast } from '../../ui'
import { Prose } from '../../ui/Prose'
import {
  askAgentAboutNote,
  assistNoteWithAI,
  draftNoteReviewPrompt,
  draftTaskFromNoteSelection,
  type AskAgentFromNoteResult,
  type NoteAIAssistAction,
  type NoteActionDraftResult,
} from '../../services/noteApi'
import {
  importObsidianNote,
  resolveObsidianVaultConflict,
  syncObsidianVault,
  type ObsidianVaultSyncResult,
} from '../../services/obsidianImportApi'
import type { OfflineNoteItem } from '../../hooks/useOfflineNotes'
import type { MarkdownLiveEditorHandle } from '../../components/MarkdownLiveEditor'
import { syncEngine } from '../../sync/SyncEngine'
import { useShell } from '../../app/shell/shellStore'
import s from './notes.module.css'

const AI_ACTIONS: Array<{ value: NoteAIAssistAction; label: string; desc: string }> = [
  { value: 'continue', label: '续写', desc: '补充例子、解释或小结' },
  { value: 'review', label: '查漏', desc: '找出遗漏的重点并出几道复习题' },
  { value: 'restructure', label: '整理结构', desc: '改写成层次更清晰的笔记' },
  { value: 'summarize', label: '摘要', desc: '提炼摘要、关键词和三句话总结' },
]

export function NoteContextPanel({
  note,
  dirty,
  editorRef,
  onApply,
}: {
  note: OfflineNoteItem | null
  dirty: boolean
  editorRef: RefObject<MarkdownLiveEditorHandle | null>
  onApply: (mode: 'append' | 'replace', text: string) => void
}) {
  const navigate = useNavigate()
  const setAsideOpen = useShell(st => st.setAsideOpen)
  const [aiAction, setAiAction] = useState<NoteAIAssistAction>('continue')
  const [instruction, setInstruction] = useState('')
  const [suggestion, setSuggestion] = useState('')
  const [busy, setBusy] = useState<'ai' | 'review' | 'task' | 'ask' | null>(null)
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<NoteActionDraftResult | AskAgentFromNoteResult | null>(null)

  const serverId = note?._serverId ?? null
  const ready = Boolean(note && serverId && note._syncStatus === 'synced' && !dirty)
  const selection = () => (editorRef.current?.getSelectedText() || '').trim().slice(0, 3000)

  const runAI = async () => {
    if (!serverId) return
    setBusy('ai')
    const r = await assistNoteWithAI(serverId, { action: aiAction, instruction: instruction.trim() || undefined, selected_text: selection() || undefined })
    setBusy(null)
    if (!r || !r.ok) {
      toast.error(r?.message || 'AI 辅助暂不可用，请检查模型设置')
      return
    }
    setSuggestion(r.suggestion)
  }

  const runAction = async (kind: 'review' | 'task' | 'ask') => {
    if (!serverId) return
    const sel = selection()
    if (kind === 'task' && !sel) {
      toast.warning('先在笔记里选中一段内容')
      return
    }
    setBusy(kind)
    const r =
      kind === 'review'
        ? await draftNoteReviewPrompt(serverId)
        : kind === 'task'
          ? await draftTaskFromNoteSelection(serverId, { selected_text: sel })
          : await askAgentAboutNote(serverId, { question: question.trim() || undefined, selected_text: sel || undefined })
    setBusy(null)
    if (!r) {
      toast.error('没有得到结果，请稍后重试')
      return
    }
    setResult(r)
  }

  return (
    <>
      <div className={s.panelHead}>
        <span className={s.panelTitle}>笔记助手</span>
        <span className={s.barSpacer} />
        <IconButton label="关闭" size="sm" onClick={() => setAsideOpen(false)}>
          <X />
        </IconButton>
      </div>
      <div className={s.panelBody}>
        {!note ? (
          <p className={s.panelHint}>选择一篇笔记后，可以让 AI 帮你续写、查漏，或者把一段内容变成任务。</p>
        ) : !ready ? (
          <Notice tone="evidence">
            {dirty ? '有未保存的修改。先保存，AI 才能基于最新内容工作。' : '这篇笔记还在同步。同步完成后就能使用 AI 与教练动作。'}
          </Notice>
        ) : null}

        <section className={s.panelGroup}>
          <h3 className={s.panelGroupTitle}>AI 辅助</h3>
          <Segmented
            size="sm"
            block
            ariaLabel="AI 动作"
            value={aiAction}
            onChange={setAiAction}
            options={AI_ACTIONS.map(a => ({ value: a.value, label: a.label }))}
          />
          <p className={s.panelHint}>{AI_ACTIONS.find(a => a.value === aiAction)?.desc}。选中文字时只处理选中的部分。</p>
          <Textarea autoGrow maxHeight={140} rows={2} value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="补充要求（可选），比如：用更口语的方式" aria-label="补充要求" />
          <Button variant="primary" icon={<Sparkles />} loading={busy === 'ai'} disabled={!ready} onClick={() => void runAI()}>
            生成建议
          </Button>
          {suggestion && (
            <>
              <div className={s.suggestion}>
                <Prose>{suggestion}</Prose>
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <Button size="sm" onClick={() => onApply('append', suggestion)}>
                  追加到末尾
                </Button>
                <Button size="sm" variant="ghost" onClick={() => onApply('replace', suggestion)}>
                  替换全文
                </Button>
                <IconButton label="复制" size="sm" onClick={() => void navigator.clipboard.writeText(suggestion).then(() => toast.success('已复制'))}>
                  <Copy />
                </IconButton>
              </div>
              <p className={s.panelHint}>应用后不会自动保存，确认无误再保存。</p>
            </>
          )}
        </section>

        <section className={s.panelGroup}>
          <h3 className={s.panelGroupTitle}>交给教练</h3>
          <div className={s.agentActions}>
            <Button className={s.actionBtn} icon={<BookOpenCheck />} loading={busy === 'review'} disabled={!ready} onClick={() => void runAction('review')}>
              生成复习提示草案
            </Button>
            <Button className={s.actionBtn} icon={<ListPlus />} loading={busy === 'task'} disabled={!ready} onClick={() => void runAction('task')}>
              把选中内容变成任务
            </Button>
          </div>
          <Textarea autoGrow maxHeight={140} rows={2} value={question} onChange={e => setQuestion(e.target.value)} placeholder="问教练：下一步该复习什么？" aria-label="问教练" />
          <Button icon={<MessageSquareText />} loading={busy === 'ask'} disabled={!ready} onClick={() => void runAction('ask')}>
            问教练这篇笔记
          </Button>
        </section>
      </div>

      <Dialog
        open={!!result}
        onOpenChange={v => !v && setResult(null)}
        width={36}
        title={(result && 'title' in result && result.title) || (result && 'answer' in result && result.answer ? '教练的回答' : '草案')}
        description={result?.message || (result && 'summary' in result ? result.summary : undefined)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setResult(null)}>
              关闭
            </Button>
            {result?.route && (
              <Button variant="primary" onClick={() => { const r = result.route!; setResult(null); navigate(r) }}>
                前往查看
              </Button>
            )}
          </>
        }
      >
        {result && 'answer' in result && result.answer ? (
          <Prose>{result.answer}</Prose>
        ) : result && 'draft' in result && result.draft ? (
          <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '6px 16px', margin: 0, fontSize: 'var(--mx-type-meta)' }}>
            {Object.entries(result.draft)
              .filter(([, v]) => v !== null && v !== undefined && typeof v !== 'object')
              .map(([k, v]) => (
                <div key={k} style={{ display: 'contents' }}>
                  <dt style={{ color: 'var(--mx-text-3)' }}>{k}</dt>
                  <dd style={{ margin: 0 }}>{String(v)}</dd>
                </div>
              ))}
          </dl>
        ) : null}
        {result?.requires_confirmation && (
          <p className={s.panelHint} style={{ marginTop: 12 }}>
            这是草案，还没有写入。前往对应页面确认后才会生效。
          </p>
        )}
      </Dialog>
    </>
  )
}

/* ---------------------------------------------------------------------------
   Obsidian import
--------------------------------------------------------------------------- */
export function ImportDialog({
  open,
  onOpenChange,
  onImported,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onImported: (notes: Array<{ title: string; content: string }>, warnings: number) => Promise<void>
}) {
  const [files, setFiles] = useState<File[]>([])
  const [attachments, setAttachments] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const run = async () => {
    if (files.length === 0) return
    setBusy(true)
    const out: Array<{ title: string; content: string }> = []
    let warnings = 0
    try {
      for (const f of files) {
        const r = await importObsidianNote(f, attachments)
        if (!r) continue
        warnings += r.warnings.length
        out.push({ title: r.title, content: r.content })
      }
      if (out.length === 0) {
        toast.error('没有导入成功的文件')
        return
      }
      await onImported(out, warnings)
      setFiles([])
      setAttachments([])
      onOpenChange(false)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      width={32}
      title="导入 Markdown / Obsidian 笔记"
      description="可以一次选多个 .md 文件。笔记里引用的图片请一起作为附件选择。"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button variant="primary" icon={<Upload />} loading={busy} disabled={files.length === 0} onClick={() => void run()}>
            导入 {files.length || ''} 篇
          </Button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Markdown 文件" hint={files.length ? files.map(f => f.name).join('、') : '支持 .md / .markdown'}>
          <input type="file" accept=".md,.markdown,text/markdown" multiple onChange={e => setFiles(Array.from(e.target.files ?? []))} aria-label="选择 Markdown 文件" />
        </Field>
        <Field label="附件（图片）" optional hint={attachments.length ? `${attachments.length} 个附件` : undefined}>
          <input type="file" accept="image/*" multiple onChange={e => setAttachments(Array.from(e.target.files ?? []))} aria-label="选择附件" />
        </Field>
      </div>
    </Dialog>
  )
}

/* ---------------------------------------------------------------------------
   Vault sync
--------------------------------------------------------------------------- */
export function VaultDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<ObsidianVaultSyncResult | null>(null)
  const [resolving, setResolving] = useState<number | null>(null)
  const run = async () => {
    if (!path.trim()) return
    setBusy(true)
    // Flush local edits first so a pending update never bypasses conflict review.
    await syncEngine.syncAll()
    const r = await syncObsidianVault(path.trim())
    setBusy(false)
    if (!r) {
      toast.error('同步失败，请检查路径和后端连接')
      return
    }
    setRes(r)
    await syncEngine.syncAll()
    toast.success(`Vault 同步完成：新增 ${r.created}，更新 ${r.updated}`)
  }
  const resolve = async (id: number, strategy: 'keep_local' | 'use_vault') => {
    setResolving(id)
    const r = await resolveObsidianVaultConflict(id, strategy)
    setResolving(null)
    if (!r) {
      toast.error('处理失败，请稍后重试')
      return
    }
    setRes(prev => (prev ? { ...prev, conflicted: Math.max(0, prev.conflicted - 1), conflicts: prev.conflicts.filter(c => c.note_id !== id) } : prev))
    await syncEngine.syncAll()
    toast.success(strategy === 'keep_local' ? '已保留 Mnemox 里的内容' : '已采用 Vault 版本')
  }
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      width={38}
      title="同步 Obsidian Vault"
      description="从本机的 Vault 目录拉取笔记。同一篇在两边都改过时，会列出来让你决定。"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
          <Button variant="primary" icon={<FolderSync />} loading={busy} disabled={!path.trim()} onClick={() => void run()}>
            开始同步
          </Button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Vault 路径" htmlFor="vault-path" hint="本机上的绝对路径，例如 D:\Notes\MyVault">
          <Input id="vault-path" value={path} onChange={e => setPath(e.target.value)} placeholder="D:\Notes\MyVault" />
        </Field>
        {res && (
          <>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              <Badge>扫描 {res.scanned}</Badge>
              <Badge tone="success">新增 {res.created}</Badge>
              <Badge tone="ink">更新 {res.updated}</Badge>
              <Badge>跳过 {res.skipped}</Badge>
              {res.failed > 0 && <Badge tone="danger">失败 {res.failed}</Badge>}
              {res.conflicted > 0 && <Badge tone="warning">冲突 {res.conflicted}</Badge>}
            </div>
            {res.conflicts.map(c => (
              <Notice
                key={c.note_id}
                tone="warning"
                title={c.title}
                actions={
                  <>
                    <Button size="sm" loading={resolving === c.note_id} onClick={() => void resolve(c.note_id, 'keep_local')}>
                      保留本地
                    </Button>
                    <Button size="sm" variant="ghost" disabled={resolving === c.note_id} onClick={() => void resolve(c.note_id, 'use_vault')}>
                      采用 Vault
                    </Button>
                  </>
                }
              >
                {c.source_path}
              </Notice>
            ))}
            {res.failures.slice(0, 5).map(f => (
              <Notice key={f.source_path} tone="danger">
                {f.source_path}：{f.reason}
              </Notice>
            ))}
          </>
        )}
      </div>
    </Dialog>
  )
}
