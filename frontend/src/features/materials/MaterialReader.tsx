import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  BookOpenText,
  CalendarDays,
  CircleAlert,
  CircleCheck,
  FileText,
  FolderKanban,
  GraduationCap,
  Info,
  MessageSquareText,
  MoreHorizontal,
  NotebookPen,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import { Button, Checkbox, Confirm, Dialog, Empty, IconButton, MasteryPips, Menu, Notice, Skeleton, toast } from '../../ui'
import { Prose } from '../../ui/Prose'
import type { MaterialChapter, MaterialItem } from '../../services/materialApi'
import type { ChatProject } from '../../services/conversationApi'
import { getApiErrorMessage } from '../../services/apiClient'
import { shortDate } from '../../lib/dates'
import { KIND_META, displayTitle, formatCount, headingId, kindOf, outlineOf, readinessOf, readingMinutes, stripLeadingTitle, textLength } from './materialModel'
import { useMaterialDetail } from './useMaterials'
import s from './materials.module.css'

/** Longest text rendered at once; beyond this the reader offers to show more. */
const RENDER_CHUNK = 60_000

interface ReaderProps {
  material: MaterialItem
  projects: ChatProject[]
  /** Whether an embedding model is configured, so a semantic index can be built. */
  semanticAvailable: boolean
  onBack: () => void
  onRemove: (m: MaterialItem) => Promise<void>
  onRetryIndex: (m: MaterialItem) => Promise<void>
  onSetProjects: (m: MaterialItem, ids: number[]) => Promise<void>
  onStartLearning: (m: MaterialItem) => Promise<{ auto_created_tasks: number; is_textbook: boolean; chapter_count: number }>
}

export function MaterialReader({ material, projects, semanticAvailable, onBack, onRemove, onRetryIndex, onSetProjects, onStartLearning }: ReaderProps) {
  const navigate = useNavigate()
  const { detail, chapters } = useMaterialDetail(material.id)
  const [removing, setRemoving] = useState(false)
  const [projectsOpen, setProjectsOpen] = useState(false)
  const [learning, setLearning] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [limit, setLimit] = useState(RENDER_CHUNK)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const kind = kindOf(material)
  const title = displayTitle(material.title)
  const raw = detail.data?.content ?? ''
  // The page title already names the material; skip a first heading that repeats it.
  const content = useMemo(() => (kind === 'md' ? stripLeadingTitle(raw, material.title) : raw), [kind, raw, material.title])
  const ready = readinessOf(detail.data ?? material, semanticAvailable)
  const isMarkdown = kind === 'md'
  const outline = useMemo(() => (isMarkdown ? outlineOf(content) : []), [content, isMarkdown])
  const shown = content.length > limit ? content.slice(0, limit) : content
  const projectById = useMemo(() => new Map(projects.map(p => [p.id, p])), [projects])
  const myProjects = (material.project_ids ?? []).map(id => projectById.get(id)).filter((p): p is ChatProject => Boolean(p))

  useEffect(() => {
    setLimit(RENDER_CHUNK)
    scrollRef.current?.scrollTo({ top: 0 })
  }, [material.id])

  const ask = (question: string) =>
    navigate(`/?${new URLSearchParams({ ask: question, context: title })}`)

  const learn = async () => {
    setLearning(true)
    try {
      const r = await onStartLearning(material)
      if (r.auto_created_tasks > 0) {
        toast.success(`已排出 ${r.auto_created_tasks} 个学习任务`, {
          description: r.is_textbook ? `按 ${r.chapter_count} 个章节拆好了，放进了目标里。` : '已放进目标里。',
          actions: [{ label: '去看看', onClick: () => navigate('/goals') }],
        })
      } else {
        toast.info('已为这份资料建好学习目标', {
          description: r.is_textbook ? '章节都已经有任务了。' : '它不像教材，没有按章节拆任务。可以在目标里手动添加。',
          actions: [{ label: '打开目标', onClick: () => navigate('/goals') }],
        })
      }
    } catch (error) {
      toast.error(getApiErrorMessage(error, '没能开始学习，请稍后重试'))
    } finally {
      setLearning(false)
    }
  }

  const menu = [
    { key: 'projects', label: '归入项目…', icon: <FolderKanban />, onSelect: () => setProjectsOpen(true) },
    { key: 'note', label: '写一篇读书笔记', icon: <NotebookPen />, onSelect: () => navigate('/notes?new=1') },
    ...(ready.canRetry
      ? [
          {
            key: 'retry',
            label: '重建检索索引',
            icon: <RefreshCw />,
            disabled: retrying,
            onSelect: async () => {
              setRetrying(true)
              try {
                await onRetryIndex(material)
              } finally {
                setRetrying(false)
              }
            },
          },
        ]
      : []),
    { key: 'sep', type: 'separator' as const },
    { key: 'delete', label: '删除资料', icon: <Trash2 />, tone: 'danger' as const, onSelect: () => setRemoving(true) },
  ]

  return (
    <section className={s.reader} aria-label={`阅读：${title}`}>
      <div className={s.readerBar}>
        <span className="mx-show-compact">
          <IconButton label="返回资料列表" onClick={onBack}>
            <ArrowLeft />
          </IconButton>
        </span>
        <span className={s.spacer} />
        <Button size="sm" variant="ghost" icon={<MessageSquareText />} onClick={() => ask('请先帮我梳理这份资料的主线：它在解决什么问题、核心概念有哪些、我应该按什么顺序读？')}>
          问教练
        </Button>
        <Menu
          items={menu}
          trigger={
            <IconButton label="资料操作">
              <MoreHorizontal />
            </IconButton>
          }
        />
      </div>

      <div className={s.readerScroll} ref={scrollRef}>
        <div className={s.readerBody} data-no-outline={outline.length < 2 || undefined}>
          <article>
            <header className={s.head} key={material.id}>
              <div className={s.kicker}>
                <span>
                  <FileText aria-hidden />
                  {KIND_META[kind].label}
                </span>
                <span>{shortDate(material.created_at)} 加入</span>
                {content && (
                  <span>
                    约 {formatCount(textLength(content))} 字 · 读完约 {readingMinutes(content)} 分钟
                  </span>
                )}
              </div>
              <h1 className={s.title}>{title}</h1>

              <div className={s.status} data-tone={ready.tone} role="status">
                <StatusIcon tone={ready.tone} />
                <span className={s.statusText}>
                  <strong>{ready.label}</strong>
                  {ready.detail}
                </span>
                {ready.canRetry && (
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<RefreshCw />}
                    loading={retrying}
                    onClick={async () => {
                      setRetrying(true)
                      try {
                        await onRetryIndex(material)
                      } finally {
                        setRetrying(false)
                      }
                    }}
                  >
                    重试
                  </Button>
                )}
              </div>

              <div className={s.actions}>
                <Button variant="primary" icon={<GraduationCap />} loading={learning} onClick={() => void learn()}>
                  开始学这份资料
                </Button>
                <Button variant="secondary" icon={<CalendarDays />} onClick={() => ask('按这份资料帮我排一个 7 天的学习计划，每天一个最小可完成的任务，先给我草案。')}>
                  排学习计划
                </Button>
                <Button variant="ghost" icon={<BookOpenText />} onClick={() => ask('根据这份资料出 5 道主动回忆题考我，一题一题来，先别给答案。')}>
                  出题考我
                </Button>
              </div>

              {(myProjects.length > 0 || projects.length > 0) && (
                <div className={s.projects}>
                  <span>项目</span>
                  {myProjects.length === 0 ? (
                    <button type="button" className={s.projectChip} onClick={() => setProjectsOpen(true)}>
                      未归入项目
                    </button>
                  ) : (
                    myProjects.map(p => (
                      <button key={p.id} type="button" className={s.projectChip} onClick={() => setProjectsOpen(true)} style={{ '--dot': p.color } as CSSProperties}>
                        <i aria-hidden />
                        {p.name}
                      </button>
                    ))
                  )}
                </div>
              )}
            </header>

            {detail.isLoading ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }} aria-busy="true" aria-label="正在加载正文">
                {[92, 100, 86, 97, 64].map((w, i) => (
                  <Skeleton key={i} width={`${w}%`} height={15} />
                ))}
              </div>
            ) : detail.isError ? (
              <Notice tone="danger" title="正文没能加载" actions={<Button size="sm" onClick={() => void detail.refetch()}>重试</Button>}>
                {getApiErrorMessage(detail.error, '确认本地学习服务已经启动。')}
              </Notice>
            ) : !content.trim() ? (
              <Empty
                align="start"
                icon={<FileText />}
                title="这份资料没有可显示的文字"
                body={material.content_status === 'failed' ? '上传时没能从文件里读出文字，可能是扫描件或图片。' : '文件里没有找到正文。'}
              />
            ) : (
              <MaterialText content={shown} markdown={isMarkdown} outlineCount={outline.length} />
            )}

            {content.length > limit && (
              <div className={s.truncated}>
                <p>
                  还有约 {formatCount(textLength(content.slice(limit)))} 字没有显示。
                </p>
                <Button size="sm" variant="secondary" onClick={() => setLimit(l => l + RENDER_CHUNK)}>
                  继续显示
                </Button>
              </div>
            )}
          </article>

          {outline.length >= 2 && <Outline items={outline} scrollRoot={scrollRef} chapters={chapters.data} />}
        </div>
      </div>

      <ProjectsDialog
        open={projectsOpen}
        onOpenChange={setProjectsOpen}
        material={material}
        projects={projects}
        onSave={async ids => {
          try {
            await onSetProjects(material, ids)
            toast.success('项目已更新', { description: '项目里的对话会自动参考这份资料。' })
            setProjectsOpen(false)
          } catch (error) {
            toast.error(getApiErrorMessage(error, '更新项目失败'))
          }
        }}
      />

      <Confirm
        open={removing}
        onOpenChange={setRemoving}
        tone="danger"
        title={`删除「${title}」？`}
        description="资料原文、检索索引，以及由它生成的章节和学习目标（含其中的任务）都会一起删除，无法恢复。你的笔记会保留。"
        confirmLabel="删除资料"
        onConfirm={async () => {
          try {
            await onRemove(material)
            toast.success('资料已删除')
          } catch (error) {
            toast.error(getApiErrorMessage(error, '删除失败'))
            throw error
          }
        }}
      />
    </section>
  )
}

function StatusIcon({ tone }: { tone: string }) {
  if (tone === 'success') return <CircleCheck className={s.statusIcon} aria-hidden />
  if (tone === 'danger' || tone === 'warning') return <CircleAlert className={s.statusIcon} aria-hidden />
  return <Info className={s.statusIcon} aria-hidden />
}

/* ============================================================================
   Text — markdown gets headings with ids for the outline; everything else
   reads as plain serif text.
   ========================================================================== */
function MaterialText({ content, markdown, outlineCount }: { content: string; markdown: boolean; outlineCount: number }) {
  const ref = useRef<HTMLDivElement | null>(null)

  // Give rendered headings the same ids the outline computes.
  useEffect(() => {
    if (!markdown || outlineCount < 2 || !ref.current) return
    const hs = ref.current.querySelectorAll<HTMLElement>('h1, h2, h3, h4')
    hs.forEach((h, i) => {
      h.id = headingId(h.textContent ?? '', i)
    })
  }, [content, markdown, outlineCount])

  if (!markdown) return <p className={s.plain}>{content}</p>
  return (
    <div ref={ref} className={s.text}>
      <Prose>{content}</Prose>
    </div>
  )
}

/* ============================================================================
   Outline — follows the reader with scroll-spy
   ========================================================================== */
function Outline({
  items,
  scrollRoot,
  chapters,
}: {
  items: ReturnType<typeof outlineOf>
  scrollRoot: React.RefObject<HTMLDivElement | null>
  chapters?: MaterialChapter[]
}) {
  const [active, setActive] = useState(0)
  const minLevel = Math.min(...items.map(i => i.level))

  useEffect(() => {
    const root = scrollRoot.current
    if (!root) return
    const onScroll = () => {
      const hs = root.querySelectorAll<HTMLElement>('h1[id], h2[id], h3[id], h4[id]')
      let current = 0
      const top = root.getBoundingClientRect().top + 80
      hs.forEach((h, i) => {
        if (h.getBoundingClientRect().top <= top) current = i
      })
      setActive(current)
    }
    root.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => root.removeEventListener('scroll', onScroll)
  }, [scrollRoot, items])

  const jump = (i: number) => {
    const root = scrollRoot.current
    const target = root?.querySelectorAll<HTMLElement>('h1[id], h2[id], h3[id], h4[id]')[i]
    target?.scrollIntoView({ block: 'start' })
  }

  const withMastery = (chapters ?? []).filter(c => typeof c.mastery_level === 'number')

  return (
    <nav className={s.outline} aria-label="目录">
      <p className={s.outlineTitle}>目录</p>
      <ol className={s.outlineList}>
        {items.map((it, i) => (
          <li key={`${it.line}-${i}`}>
            <button
              type="button"
              className={s.outlineItem}
              data-active={i === active || undefined}
              style={{ '--indent': it.level - minLevel } as CSSProperties}
              onClick={() => jump(i)}
            >
              {it.text}
            </button>
          </li>
        ))}
      </ol>
      {withMastery.length > 0 && (
        <>
          <p className={s.outlineTitle} style={{ marginTop: '1.5rem' }}>
            章节掌握度
          </p>
          <ul className={s.chapters}>
            {withMastery.map(c => (
              <li key={c.id} className={s.chapter}>
                <span title={c.title}>{c.title}</span>
                <MasteryPips level={Math.round(((c.mastery_level ?? 0) / 100) * 5)} />
              </li>
            ))}
          </ul>
        </>
      )}
    </nav>
  )
}

/* ============================================================================
   Projects — which chat projects should always consult this material
   ========================================================================== */
function ProjectsDialog({
  open,
  onOpenChange,
  material,
  projects,
  onSave,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  material: MaterialItem
  projects: ChatProject[]
  onSave: (ids: number[]) => Promise<void>
}) {
  const [picked, setPicked] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (open) setPicked(material.project_ids ?? [])
  }, [open, material.project_ids])

  const visible = projects.filter(p => !p.is_archived || picked.includes(p.id))
  let body: ReactNode
  if (visible.length === 0) {
    body = <Empty align="start" icon={<FolderKanban />} title="还没有项目" body="在教练对话里新建项目后，就能把资料归进去。" />
  } else {
    body = (
      <ul className={s.projectList}>
        {visible.map(p => (
          <li key={p.id} className={s.projectRow}>
            <span className={s.projectDot} style={{ '--dot': p.color } as CSSProperties} aria-hidden />
            <Checkbox
              label={p.name}
              checked={picked.includes(p.id)}
              onCheckedChange={v => setPicked(prev => (v ? [...prev, p.id] : prev.filter(x => x !== p.id)))}
            />
            <span className={s.projectMeta}>{p.conversation_count} 个对话</span>
          </li>
        ))}
      </ul>
    )
  }
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="归入项目"
      description="项目里的对话会自动参考其中的资料。"
      width={28}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={visible.length === 0}
            onClick={async () => {
              setBusy(true)
              try {
                await onSave(picked)
              } finally {
                setBusy(false)
              }
            }}
          >
            保存
          </Button>
        </>
      }
    >
      {body}
    </Dialog>
  )
}
