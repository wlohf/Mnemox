import { memo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Brain, Check, Copy, FileText, GitBranch, Globe, Library, NotebookPen, Pencil, RefreshCw, X } from 'lucide-react'
import { BrandMark, Button, IconButton, Textarea, toast } from '../../ui'
import { Prose } from '../../ui/Prose'
import type { ChatMessage } from '../../services/chatApi'
import type { TurnContext } from './useChatController'
import s from './coach.module.css'

function imageSrc(img: string) {
  return img.startsWith('data:') ? img : `data:image/png;base64,${img}`
}

export const UserTurn = memo(function UserTurn({
  message,
  onEdit,
  disabled,
}: {
  message: ChatMessage
  onEdit?: (next: string) => void
  disabled?: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(message.content)
  const submit = () => {
    const next = draft.trim()
    setEditing(false)
    if (next && next !== message.content) onEdit?.(next)
  }
  if (editing) {
    return (
      <div className={s.turnUser}>
        <div className={s.editBox}>
          <Textarea
            autoGrow
            autoFocus
            value={draft}
            onChange={e => setDraft(e.target.value)}
            aria-label="编辑消息"
            onKeyDown={e => {
              if (e.key === 'Escape') {
                e.preventDefault()
                setDraft(message.content)
                setEditing(false)
              }
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit()
            }}
          />
          <div className={s.editActions}>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              取消
            </Button>
            <Button size="sm" variant="primary" onClick={submit}>
              从这里重新提问
            </Button>
          </div>
        </div>
      </div>
    )
  }
  return (
    <div className={s.turnUser}>
      <div className={s.userCard}>
        {message.image_data && message.image_data.length > 0 && (
          <div className={s.userImages}>
            {message.image_data.map((img, i) => (
              <img key={i} src={imageSrc(img)} alt={`附图 ${i + 1}`} />
            ))}
          </div>
        )}
        {message.content}
        {onEdit && !disabled && (
          <span className={s.userTools}>
            <IconButton
              label="编辑并从这里重新提问"
              size="sm"
              onClick={() => {
                setDraft(message.content)
                setEditing(true)
              }}
            >
              <Pencil />
            </IconButton>
          </span>
        )}
      </div>
    </div>
  )
})

export const CoachTurn = memo(function CoachTurn({
  content,
  streaming,
  last,
  context,
  onRegenerate,
  onBranch,
  onQuote,
}: {
  content: string
  streaming?: boolean
  last?: boolean
  context?: TurnContext
  onRegenerate?: () => void
  onBranch?: () => void
  onQuote?: () => void
}) {
  const [copied, setCopied] = useState(false)
  return (
    <div className={s.turnCoach} data-last={last || undefined}>
      <span className={s.seal} aria-hidden>
        <BrandMark size={15} />
      </span>
      <div className={s.coachBody}>
        {content ? (
          <Prose streaming={streaming}>{content}</Prose>
        ) : (
          <span className={s.thinking} role="status">
            <span className={s.thinkingDots} aria-hidden>
              <i />
              <i />
              <i />
            </span>
            正在查阅你的学习记录…
          </span>
        )}
        {context && !streaming && <Consulted context={context} />}
        {!streaming && content && (
          <div className={s.coachTools}>
            <IconButton
              label={copied ? '已复制' : '复制'}
              size="sm"
              onClick={() => {
                void navigator.clipboard?.writeText(content).then(() => {
                  setCopied(true)
                  window.setTimeout(() => setCopied(false), 1400)
                })
              }}
            >
              {copied ? <Check /> : <Copy />}
            </IconButton>
            {onQuote && (
              <IconButton label="摘录到笔记" size="sm" onClick={onQuote}>
                <NotebookPen />
              </IconButton>
            )}
            {onRegenerate && (
              <IconButton label="重新生成" size="sm" onClick={onRegenerate}>
                <RefreshCw />
              </IconButton>
            )}
            {onBranch && (
              <IconButton label="从这里创建分支" size="sm" onClick={onBranch}>
                <GitBranch />
              </IconButton>
            )}
          </div>
        )}
      </div>
    </div>
  )
})

function Consulted({ context }: { context: TurnContext }) {
  const navigate = useNavigate()
  const total = context.memories.length + context.notes.length + context.web.length + context.materials.length
  if (total === 0 && !context.notice) return null
  return (
    <div className={s.consulted}>
      <span className={s.consultedLabel}>参考了</span>
      {context.materials.map(m => (
        <button key={`m${m.id}`} type="button" className={s.srcChip} onClick={() => navigate(`/materials?id=${m.id}`)} title={m.title}>
          <Library aria-hidden />
          <span>{m.title}</span>
        </button>
      ))}
      {context.notes.slice(0, 4).map(n => (
        <button key={`n${n.id}`} type="button" className={s.srcChip} onClick={() => navigate('/notes')} title={n.excerpt}>
          <FileText aria-hidden />
          <span>{n.title}</span>
        </button>
      ))}
      {context.memories.slice(0, 3).map(m => (
        <button key={`r${m.id}`} type="button" className={s.srcChip} data-kind="memory" onClick={() => navigate('/memory')} title={m.value}>
          <Brain aria-hidden />
          <span>{m.value}</span>
        </button>
      ))}
      {context.web.slice(0, 4).map(w => (
        <a key={w.url} className={s.srcChip} href={w.url} target="_blank" rel="noreferrer noopener" title={w.snippet || w.title}>
          <Globe aria-hidden />
          <span>{w.source_domain || w.title}</span>
        </a>
      ))}
      {context.notice && <span>{context.notice}</span>}
    </div>
  )
}

export function StreamError({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div className={s.turnCoach}>
      <span className={s.seal} aria-hidden>
        <X />
      </span>
      <div className={s.coachBody} role="alert">
        <p style={{ margin: 0, color: 'var(--mx-danger)' }}>{message}</p>
        <Button size="sm" variant="ghost" onClick={onDismiss} style={{ marginTop: 8 }}>
          知道了
        </Button>
      </div>
    </div>
  )
}

export function copyToast() {
  toast.success('已复制')
}
