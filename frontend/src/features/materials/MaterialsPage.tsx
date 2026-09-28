import { useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { FileSearch, FileUp, Library, MessageSquareText, Search, TextSearch, Upload, X } from 'lucide-react'
import { Button, Empty, IconButton, Input, Notice, Select, Skeleton } from '../../ui'
import type { MaterialItem } from '../../services/materialApi'
import { usePageChrome } from '../../app/shell/shellStore'
import { shortDate } from '../../lib/dates'
import {
  ACCEPT_ATTR,
  KIND_META,
  displayTitle,
  filterMaterials,
  kindOf,
  readinessOf,
  snippetAround,
  sortMaterials,
  splitHighlight,
  type FileKind,
  type SortKey,
} from './materialModel'
import { MATERIAL_LIMIT, useContentSearch, useMaterialsLibrary, type UploadJob } from './useMaterials'
import { MaterialReader } from './MaterialReader'
import s from './materials.module.css'

type ProjectFilter = 'all' | 'none' | number

export function MaterialsPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const lib = useMaterialsLibrary()
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<'title' | 'content'>('title')
  const [kind, setKind] = useState<FileKind | 'all'>('all')
  const [project, setProject] = useState<ProjectFilter>('all')
  const [sort, setSort] = useState<SortKey>('recent')
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const dragDepth = useRef(0)

  const items = lib.list.data ?? []
  const semantic = Boolean(lib.rag.data?.embedding_enabled || lib.rag.data?.rag_online)
  const projects = lib.projects.data ?? []
  const selectedId = Number(params.get('id')) || null
  const selected = items.find(m => m.id === selectedId) ?? null

  const select = (id: number | null) => {
    const next = new URLSearchParams(params)
    if (id == null) next.delete('id')
    else next.set('id', String(id))
    setParams(next, { replace: id != null && selectedId != null })
  }

  // Desktop: open the newest material by default so the reader is never blank.
  useEffect(() => {
    if (selectedId == null && items.length > 0 && window.matchMedia('(min-width: 821px)').matches) {
      const next = new URLSearchParams(params)
      next.set('id', String(sortMaterials(items, 'recent')[0].id))
      setParams(next, { replace: true })
    }
  }, [items.length, selectedId])

  // /materials?upload=1 (from 今天 / onboarding) opens the file picker.
  useEffect(() => {
    if (params.get('upload') !== '1') return
    const next = new URLSearchParams(params)
    next.delete('upload')
    setParams(next, { replace: true })
    requestAnimationFrame(() => fileRef.current?.click())
  }, [])

  const shown = useMemo(
    () => sortMaterials(filterMaterials(items, { query: mode === 'title' ? query : '', kind, projectId: project }), sort),
    [items, query, mode, kind, project, sort],
  )
  const search = useContentSearch(query, mode === 'content')

  const kinds = useMemo(() => {
    const present = new Set(items.map(m => kindOf(m)))
    return (Object.keys(KIND_META) as FileKind[]).filter(k => present.has(k))
  }, [items])

  usePageChrome({
    title: '资料库',
    bare: true,
    actions: (
      <Button size="sm" variant="secondary" icon={<Upload />} onClick={() => fileRef.current?.click()}>
        上传资料
      </Button>
    ),
  })

  const handleFiles = async (files: FileList | File[] | null) => {
    if (!files || files.length === 0) return
    const landed = await lib.upload(Array.from(files))
    if (landed.length > 0) select(landed[0])
  }

  const onDragEnter = (e: DragEvent) => {
    if (!e.dataTransfer.types.includes('Files')) return
    e.preventDefault()
    dragDepth.current += 1
    setDragging(true)
  }
  const onDragLeave = () => {
    dragDepth.current = Math.max(0, dragDepth.current - 1)
    if (dragDepth.current === 0) setDragging(false)
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    dragDepth.current = 0
    setDragging(false)
    void handleFiles(e.dataTransfer.files)
  }

  const filtered = query.trim().length > 0 || kind !== 'all' || project !== 'all'

  return (
    <div className={s.root} data-open={selected ? true : undefined}>
      <input
        ref={fileRef}
        type="file"
        multiple
        accept={ACCEPT_ATTR}
        hidden
        onChange={e => {
          void handleFiles(e.target.files)
          e.target.value = ''
        }}
      />

      <aside
        className={s.shelf}
        aria-label="资料列表"
        style={{ position: 'relative' }}
        onDragEnter={onDragEnter}
        onDragOver={e => e.dataTransfer.types.includes('Files') && e.preventDefault()}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        <div className={s.shelfHead}>
          <div className={s.shelfTitleRow}>
            <h1 className={s.shelfTitle}>资料库</h1>
            <span className={s.shelfCount}>{items.length}</span>
            <span className={s.shelfTitleEnd}>
              <IconButton label={mode === 'title' ? '改为搜正文' : '改为搜标题'} size="sm" active={mode === 'content'} onClick={() => setMode(m => (m === 'title' ? 'content' : 'title'))}>
                {mode === 'content' ? <TextSearch /> : <FileSearch />}
              </IconButton>
            </span>
          </div>
          <Input
            size="sm"
            prefix={<Search />}
            placeholder={mode === 'content' ? '在所有资料的正文里搜索' : '按标题筛选'}
            aria-label={mode === 'content' ? '搜索资料正文' : '按标题筛选资料'}
            value={query}
            onChange={e => setQuery(e.target.value)}
            suffix={
              query ? (
                <IconButton label="清除" size="sm" noTooltip onClick={() => setQuery('')}>
                  <X />
                </IconButton>
              ) : undefined
            }
          />
          {mode === 'title' ? (
            items.length > 0 && (
              <div className={s.filters}>
                <Select
                  size="sm"
                  ariaLabel="文件类型"
                  value={kind}
                  onValueChange={v => setKind(v as FileKind | 'all')}
                  options={[{ value: 'all', label: '全部类型' }, ...kinds.map(k => ({ value: k, label: KIND_META[k].label }))]}
                />
                <Select
                  size="sm"
                  ariaLabel="项目"
                  value={String(project)}
                  onValueChange={v => setProject(v === 'all' || v === 'none' ? v : Number(v))}
                  options={[
                    { value: 'all', label: '全部项目' },
                    ...projects.filter(p => !p.is_archived).map(p => ({ value: String(p.id), label: p.name })),
                    { value: 'none', label: '未归入项目' },
                  ]}
                />
                <Select
                  size="sm"
                  ariaLabel="排序"
                  value={sort}
                  onValueChange={v => setSort(v as SortKey)}
                  options={[
                    { value: 'recent', label: '最近加入' },
                    { value: 'title', label: '按标题' },
                  ]}
                />
              </div>
            )
          ) : (
            <div className={s.modeRow}>
              <span>按意思和关键词检索正文。</span>
              <button type="button" onClick={() => setMode('title')}>
                回到列表
              </button>
            </div>
          )}
        </div>

        <div className={s.shelfScroll}>
          {lib.uploads.length > 0 && <Uploads jobs={lib.uploads} onDismiss={lib.dismissUpload} />}

          {mode === 'content' ? (
            <ContentResults query={query} search={search} onOpen={id => select(id)} />
          ) : lib.list.isLoading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '4px 8px' }} aria-busy="true" aria-label="正在加载资料">
              {[0, 1, 2, 3].map(i => (
                <div key={i} style={{ display: 'grid', gridTemplateColumns: '36px 1fr', gap: 12 }}>
                  <Skeleton width={36} height={44} radius={5} />
                  <div>
                    <Skeleton width="80%" height={14} />
                    <Skeleton width="45%" height={11} style={{ marginTop: 8 }} />
                  </div>
                </div>
              ))}
            </div>
          ) : lib.list.isError ? (
            <div style={{ padding: '0 8px' }}>
              <Notice tone="danger" title="资料没能加载" actions={<Button size="sm" onClick={() => void lib.list.refetch()}>重试</Button>}>
                确认本地学习服务已经启动。
              </Notice>
            </div>
          ) : items.length === 0 ? (
            <Empty
              icon={<Library />}
              title="资料库还是空的"
              body="上传课本、讲义或自己的笔记。教练回答时会引用其中的原文，还能按章节帮你排学习计划。"
              actions={
                <Button variant="primary" icon={<FileUp />} onClick={() => fileRef.current?.click()}>
                  上传第一份资料
                </Button>
              }
            />
          ) : shown.length === 0 ? (
            <Empty
              icon={<Search />}
              title="没有符合条件的资料"
              body={query ? '标题里没有这个词。想找正文里的内容，可以切换到正文搜索。' : '换一个筛选条件看看。'}
              actions={
                <>
                  {query && (
                    <Button size="sm" variant="secondary" icon={<TextSearch />} onClick={() => setMode('content')}>
                      搜正文
                    </Button>
                  )}
                  {filtered && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setQuery('')
                        setKind('all')
                        setProject('all')
                      }}
                    >
                      清除筛选
                    </Button>
                  )}
                </>
              }
            />
          ) : (
            <ul className={s.shelfList}>
              {shown.map(m => (
                <li key={m.id}>
                  <Book material={m} semantic={semantic} current={m.id === selected?.id} onOpen={() => select(m.id)} />
                </li>
              ))}
            </ul>
          )}
          {items.length >= MATERIAL_LIMIT && mode === 'title' && <p className={s.shelfNote}>只显示最近加入的 {MATERIAL_LIMIT} 份资料。</p>}
          {items.length > 0 && mode === 'title' && <p className={s.shelfNote}>可以把文件直接拖到这里上传。支持 PDF、Word、Markdown、TXT。</p>}
        </div>

        {dragging && (
          <div className={s.drop} aria-hidden>
            <span>
              <FileUp />
              松开即可上传
            </span>
          </div>
        )}
      </aside>

      {selected ? (
        <MaterialReader
          key={selected.id}
          material={selected}
          projects={projects}
          semanticAvailable={semantic}
          onBack={() => select(null)}
          onRemove={async m => {
            await lib.remove(m)
            select(null)
          }}
          onRetryIndex={lib.retryIndex}
          onSetProjects={lib.setProjects}
          onStartLearning={lib.startLearning}
        />
      ) : (
        <section className={s.reader}>
          <div className={s.blank}>
            {items.length > 0 ? (
              <Empty icon={<Library />} title="选一份资料开始读" body="读的时候可以随时问教练，或者让它按这份资料出题、排计划。" />
            ) : (
              <Empty
                icon={<MessageSquareText />}
                title="资料是教练回答的依据"
                body="有了资料，教练的每个回答都能标出出处，你可以随时点开核对原文。"
                actions={
                  <Button variant="ghost" onClick={() => navigate('/')}>
                    先去和教练聊聊
                  </Button>
                }
              />
            )}
          </div>
        </section>
      )}
    </div>
  )
}

function Book({ material, semantic, current, onOpen }: { material: MaterialItem; semantic: boolean; current: boolean; onOpen: () => void }) {
  const kind = kindOf(material)
  const ready = readinessOf(material, semantic)
  return (
    <button type="button" className={s.book} aria-current={current || undefined} onClick={onOpen}>
      <span className={s.spine} data-kind={kind} aria-hidden>
        {KIND_META[kind].short}
      </span>
      <span className={s.bookText}>
        <span className={s.bookTitle}>{displayTitle(material.title)}</span>
        <span className={s.bookMeta}>
          <span className={s.ready} data-tone={ready.tone}>
            <i aria-hidden />
            {ready.label}
          </span>
          <span>{shortDate(material.created_at)}</span>
        </span>
      </span>
    </button>
  )
}

function Uploads({ jobs, onDismiss }: { jobs: UploadJob[]; onDismiss: (id: string) => void }) {
  return (
    <ul className={s.shelfList} style={{ marginBottom: 8 }} aria-live="polite">
      {jobs.map(j => (
        <li key={j.id} className={s.uploading}>
          <span className={s.spine} data-kind="other" aria-hidden>
            {j.state === 'failed' ? '!' : '···'}
          </span>
          <span style={{ minWidth: 0, display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', alignItems: 'center', gap: 6 }}>
            <span style={{ minWidth: 0 }}>
              <span className={s.uploadName} style={{ display: 'block' }}>
                {j.name}
              </span>
              <span className={s.uploadState} style={j.state === 'failed' ? { color: 'var(--mx-danger)' } : undefined}>
                {j.state === 'failed' ? j.error : '正在上传并读取文字…'}
              </span>
            </span>
            {j.state === 'failed' && (
              <IconButton label="移除这条" size="sm" onClick={() => onDismiss(j.id)}>
                <X />
              </IconButton>
            )}
          </span>
        </li>
      ))}
    </ul>
  )
}

function ContentResults({
  query,
  search,
  onOpen,
}: {
  query: string
  search: ReturnType<typeof useContentSearch>
  onOpen: (id: number) => void
}) {
  const q = query.trim()
  if (q.length < 2) {
    return <p className={s.shelfNote}>输入至少两个字，在所有资料的正文里查找。结果按相关程度排列。</p>
  }
  if (search.isLoading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '0 4px' }} aria-busy="true">
        {[0, 1, 2].map(i => (
          <Skeleton key={i} height={72} radius={10} />
        ))}
      </div>
    )
  }
  if (search.isError) {
    return (
      <div style={{ padding: '0 8px' }}>
        <Notice tone="warning" title="正文搜索暂时不可用" actions={<Button size="sm" onClick={() => void search.refetch()}>重试</Button>}>
          可以先按标题筛选。
        </Notice>
      </div>
    )
  }
  const hits = search.data ?? []
  if (hits.length === 0) {
    return <Empty icon={<TextSearch />} title="正文里没有找到" body={`没有资料提到「${q}」。换个说法试试。`} />
  }
  return (
    <ul className={s.hits}>
      {hits.map((h, i) => (
        <li key={`${h.material_id}-${i}`}>
          <button type="button" className={s.hit} onClick={() => onOpen(h.material_id)}>
            <span className={s.hitTitle}>
              <TextSearch aria-hidden />
              {displayTitle(h.title || `资料 #${h.material_id}`)}
            </span>
            <p className={s.hitText}>
              {splitHighlight(snippetAround(h.text, q), q).map((part, j) => (part.hit ? <mark key={j}>{part.text}</mark> : <span key={j}>{part.text}</span>))}
            </p>
          </button>
        </li>
      ))}
    </ul>
  )
}
