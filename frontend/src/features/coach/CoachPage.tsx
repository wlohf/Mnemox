import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { BookOpenCheck, Brain, CalendarPlus, Lightbulb, ListTree, MessagesSquare, PanelLeft } from 'lucide-react'
import { Button, Dialog, Field, IconButton, Input, Skeleton, Textarea, toast } from '../../ui'
import { parseConversationRouteId } from '../../services/conversationRoute'
import { createNote } from '../../services/noteApi'
import { usePageChrome } from '../../app/shell/shellStore'
import { useAuthStore } from '../../stores/authStore'
import { ConversationList } from './ConversationList'
import { CoachTurn, UserTurn } from './Turns'
import { Composer, type ComposerHandle } from './Composer'
import { WriteDraftDialog } from './WriteDraftDialog'
import { useChatController } from './useChatController'
import s from './coach.module.css'

const STARTERS = [
  { icon: <Lightbulb />, title: '费曼解释', body: '我来讲一个概念，你扮演初学者追问我。', prompt: '我想用费曼法讲一个概念，请你扮演完全不懂的初学者，先听我讲，再追问我讲不清的地方。概念是：' },
  { icon: <BookOpenCheck />, title: '复习昨天', body: '根据我的错题和复习记录，先考我三题。', prompt: '根据我最近的错题和到期复习，先出 3 道主动回忆题考我，不要直接给答案。' },
  { icon: <CalendarPlus />, title: '排今天的计划', body: '按我的目标和高效时段，拆成今天能完成的任务。', prompt: '帮我把今天的计划排一下：结合我的目标、到期复习和高效时段，拆成 3 个今天能完成的任务，加入今天计划。' },
  { icon: <ListTree />, title: '理清一章资料', body: '给我当前资料的章节结构和先后顺序。', prompt: '帮我梳理当前资料的章节结构：哪些概念是先修，哪些最容易出错，我应该按什么顺序学？' },
]

interface QuoteDraft {
  title: string
  content: string
  saving: boolean
}

export function CoachPage() {
  const params = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const routeId = parseConversationRouteId(params.conversationId)
  const chat = useChatController(routeId)
  const user = useAuthStore(st => st.user)
  const composerRef = useRef<ComposerHandle | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const pinnedToBottom = useRef(true)
  const [projectId, setProjectId] = useState<number | null>(() => {
    const raw = localStorage.getItem('chat_activeProjectId')
    return raw ? Number(raw) || null : null
  })
  const [listHidden, setListHidden] = useState(() => localStorage.getItem('mx_chat_list_hidden') === 'true')
  const [context, setContext] = useState<string | null>(null)
  const [quote, setQuote] = useState<QuoteDraft | null>(null)

  useEffect(() => {
    if (params.conversationId !== undefined && routeId === null) navigate('/', { replace: true })
  }, [navigate, params.conversationId, routeId])

  useEffect(() => {
    if (projectId === null) localStorage.removeItem('chat_activeProjectId')
    else localStorage.setItem('chat_activeProjectId', String(projectId))
  }, [projectId])
  useEffect(() => localStorage.setItem('mx_chat_list_hidden', String(listHidden)), [listHidden])

  // Handoff from 今天 / command palette: /?ask=…&context=…
  useEffect(() => {
    const ask = searchParams.get('ask')
    if (!ask) return
    const ctx = searchParams.get('context')
    setContext(ctx)
    const next = new URLSearchParams(searchParams)
    next.delete('ask')
    next.delete('context')
    setSearchParams(next, { replace: true })
    const text = ctx ? `关于「${ctx}」：${ask}` : ask
    void chat.send(text, { projectId })
  }, [])

  usePageChrome({
    title: '教练对话',
    bare: true,
    actions: (
      <IconButton label={listHidden ? '显示对话列表' : '隐藏对话列表'} onClick={() => setListHidden(v => !v)} className="mx-hide-compact">
        <PanelLeft />
      </IconButton>
    ),
  })

  // Stick to bottom while streaming unless the learner scrolled up.
  useEffect(() => {
    const el = scrollRef.current
    if (!el || !pinnedToBottom.current) return
    el.scrollTop = el.scrollHeight
  }, [chat.messages.length, chat.streaming])

  const lastAssistant = useMemo(() => {
    for (let i = chat.messages.length - 1; i >= 0; i--) if (chat.messages[i].role === 'assistant') return i
    return -1
  }, [chat.messages])

  const empty = chat.messages.length === 0 && !chat.busy && !chat.loadingConversation

  const saveQuote = async () => {
    if (!quote) return
    if (!quote.title.trim() || !quote.content.trim()) {
      toast.warning('标题和内容都不能为空')
      return
    }
    setQuote({ ...quote, saving: true })
    const created = await createNote({ title: quote.title.trim(), content: quote.content.trim(), note_type: 'summary', tags: ['对话摘录'] })
    if (created) {
      toast.success('已摘录到笔记', { actions: [{ label: '打开笔记', onClick: () => navigate('/notes') }] })
      setQuote(null)
    } else {
      toast.error('创建笔记失败，请稍后重试')
      setQuote(q => (q ? { ...q, saving: false } : q))
    }
  }

  return (
    <div className={s.root} data-list={listHidden ? 'hidden' : undefined}>
      <ConversationList
        activeId={routeId}
        projectId={projectId}
        onProjectChange={setProjectId}
        onNew={() => {
          navigate('/')
          composerRef.current?.focus()
        }}
      />

      <section className={s.thread} aria-label="对话">
        <div
          ref={scrollRef}
          className={s.scroller}
          onScroll={e => {
            const el = e.currentTarget
            pinnedToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96
          }}
        >
          {chat.loadingConversation ? (
            <div className={s.stream} aria-busy="true">
              <Skeleton width="40%" height={40} radius={14} style={{ marginLeft: 'auto' }} />
              <Skeleton height={16} style={{ marginTop: 28 }} />
              <Skeleton height={16} width="88%" style={{ marginTop: 10 }} />
              <Skeleton height={16} width="72%" style={{ marginTop: 10 }} />
            </div>
          ) : empty ? (
            <div className={s.hero}>
              <p className={s.heroKicker}>教练对话</p>
              <h1 className={s.heroTitle}>{user?.username ? `${user.username}，今天想弄明白什么？` : '今天想弄明白什么？'}</h1>
              <p className={s.heroLead}>
                教练读得到你的资料、笔记、错题和复习记录。它会先追问你，再给出带来源的解释；要写入的内容都会先给你看草案。
              </p>
              <div className={s.starters}>
                {STARTERS.map(st => (
                  <button key={st.title} type="button" className={s.starter} onClick={() => composerRef.current?.fill(st.prompt)}>
                    {st.icon}
                    <span>
                      <span className={s.starterTitle}>{st.title}</span>
                      <span className={s.starterBody}>{st.body}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className={s.stream} aria-live="polite" aria-busy={chat.busy}>
              {chat.messages.map((m, i) =>
                m.role === 'user' ? (
                  <UserTurn key={i} message={m} disabled={chat.busy} onEdit={next => void chat.editAndResend(i, next)} />
                ) : (
                  <CoachTurn
                    key={i}
                    content={m.content}
                    last={i === lastAssistant && !chat.busy}
                    context={i === lastAssistant && !chat.busy ? chat.turn : undefined}
                    onRegenerate={chat.busy ? undefined : () => void chat.regenerate(i)}
                    onBranch={chat.busy ? undefined : () => void chat.branchAt(i)}
                    onQuote={() => setQuote({ title: `对话摘录 ${new Date().toLocaleDateString('zh-CN')}`, content: m.content, saving: false })}
                  />
                ),
              )}
              {chat.busy && <CoachTurn content={chat.streaming} streaming />}
            </div>
          )}
        </div>

        <Composer
          ref={composerRef}
          busy={chat.busy || chat.writeBusy}
          streaming={chat.busy}
          onStop={chat.stop}
          context={context ? { label: context, onRemove: () => setContext(null) } : null}
          onSubmit={v =>
            chat.send(context && chat.messages.length === 0 ? `关于「${context}」：${v.text}` : v.text, {
              images: v.images,
              providerName: v.providerName,
              model: v.model,
              webSearch: v.webSearch,
              projectId,
            })
          }
        />
      </section>

      <WriteDraftDialog
        draft={chat.writeDraft}
        busy={chat.writeBusy}
        onChange={chat.setWriteDraft}
        onCancel={chat.cancelWrite}
        onConfirm={() => chat.writeDraft && void chat.confirmWrite(chat.writeDraft, projectId)}
      />

      <Dialog
        open={!!quote}
        onOpenChange={v => !v && !quote?.saving && setQuote(null)}
        width={38}
        title="摘录到笔记"
        description="把这段回答保存成一条笔记，之后教练回答时也能引用它。"
        footer={
          <>
            <Button variant="ghost" onClick={() => setQuote(null)} disabled={quote?.saving}>
              取消
            </Button>
            <Button variant="primary" loading={quote?.saving} onClick={() => void saveQuote()} icon={<Brain />}>
              保存为笔记
            </Button>
          </>
        }
      >
        {quote && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Field label="标题" htmlFor="quote-title">
              <Input id="quote-title" value={quote.title} onChange={e => setQuote({ ...quote, title: e.target.value })} />
            </Field>
            <Field label="内容" htmlFor="quote-content">
              <Textarea id="quote-content" reading autoGrow maxHeight={360} value={quote.content} onChange={e => setQuote({ ...quote, content: e.target.value })} />
            </Field>
          </div>
        )}
      </Dialog>
    </div>
  )
}

export const CoachPageIcon = MessagesSquare
