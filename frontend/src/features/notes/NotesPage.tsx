import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Eye, FilePlus2, FolderSync, Import, Pencil, Save, Search, Trash2, Undo2, X } from 'lucide-react'
import { Button, Chip, Confirm, Empty, IconButton, Input, Menu, Segmented, Skeleton, toast } from '../../ui'
import { Prose } from '../../ui/Prose'
import { uploadImage } from '../../services/imageApi'
import type { MarkdownLiveEditorHandle, MarkdownLiveEditorImageResult } from '../../components/MarkdownLiveEditor'
import { usePageChrome } from '../../app/shell/shellStore'
import { excerpt, useNotesEditor, type FolderKey } from './useNotesEditor'
import { ImportDialog, NoteContextPanel, VaultDialog } from './NotePanels'
import s from './notes.module.css'

const MarkdownLiveEditor = lazy(() => import('../../components/MarkdownLiveEditor').then(m => ({ default: m.MarkdownLiveEditor })))

function when(iso: string | null | undefined) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  return sameDay
    ? `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    : `${d.getMonth() + 1}月${d.getDate()}日`
}

export function NotesPage() {
  const ed = useNotesEditor()
  const [params, setParams] = useSearchParams()
  const [mode, setMode] = useState<'write' | 'read'>('write')
  const [tagDraft, setTagDraft] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [vaultOpen, setVaultOpen] = useState(false)
  const [listOpen, setListOpen] = useState(false)
  const editorRef = useRef<MarkdownLiveEditorHandle | null>(null)

  const dirty = ed.status === 'dirty' || ed.status === 'saved' || ed.status === 'restored'

  // /notes?new=1 from the command palette
  useEffect(() => {
    if (params.get('new') !== '1') return
    const next = new URLSearchParams(params)
    next.delete('new')
    setParams(next, { replace: true })
    void ed.create()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Ctrl+S saves
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        void save()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const save = async () => {
    const saved = await ed.save()
    if (saved) toast.success('已保存')
    else if (ed.active) toast.error('保存失败')
  }

  const aside = useMemo(
    () => (
      <NoteContextPanel
        note={ed.active}
        dirty={dirty}
        editorRef={editorRef}
        onApply={(how, text) => {
          ed.setContent(prev => (how === 'append' ? `${prev.trimEnd()}\n\n${text.trim()}\n` : text.trim()))
          toast.info(how === 'append' ? '已追加到末尾，记得保存' : '已替换全文，记得保存')
        }}
      />
    ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ed.active, dirty],
  )

  usePageChrome({
    title: '笔记',
    bare: true,
    aside,
    asideLabel: '笔记助手',
    actions: (
      <Menu
        align="end"
        trigger={
          <IconButton label="导入与同步">
            <Import />
          </IconButton>
        }
        items={[
          { key: 'import', label: '导入 Markdown / Obsidian', icon: <Import />, onSelect: () => setImportOpen(true) },
          { key: 'vault', label: '同步 Obsidian Vault', icon: <FolderSync />, onSelect: () => setVaultOpen(true) },
        ]}
      />
    ),
  })

  const folders: Array<{ key: FolderKey; label: string; count: number }> = [
    { key: 'all', label: '全部笔记', count: ed.notes.length },
    { key: 'untagged', label: '未分类', count: ed.notes.filter(n => (n.tags || []).length === 0).length },
    { key: 'pending', label: '待同步', count: ed.notes.filter(n => n._syncStatus !== 'synced').length },
    ...ed.tagStats.slice(0, 12).map(t => ({ key: `tag:${t.tag}` as FolderKey, label: t.tag, count: t.count })),
  ]

  const uploadForEditor = async (file: File): Promise<MarkdownLiveEditorImageResult | null> => {
    const r = await uploadImage(file)
    if (!r) {
      toast.error('图片上传失败')
      return null
    }
    return { url: r.url, markdown: r.markdown, alt: r.original_name || r.filename }
  }

  const addTag = () => {
    const t = tagDraft.trim().replace(/^#/, '')
    if (t && !ed.tags.includes(t)) ed.setTags([...ed.tags, t].slice(0, 12))
    setTagDraft('')
  }

  const statusText =
    ed.saving
      ? '正在保存…'
      : ed.status === 'dirty'
        ? '有未保存的修改'
        : ed.status === 'saved'
          ? `草稿已暂存 ${when(ed.savedAt)}`
          : ed.status === 'restored'
            ? '已恢复上次未保存的草稿'
            : ed.active && ed.active._syncStatus !== 'synced'
              ? '等待同步'
              : '已同步'
  const statusState = ed.saving ? 'dirty' : ed.status !== 'clean' ? ed.status : ed.active && ed.active._syncStatus !== 'synced' ? 'pending' : 'clean'

  return (
    <div className={s.root} data-list={listOpen ? 'open' : undefined}>
      <nav className={s.list} aria-label="笔记列表">
        <div className={s.listHead}>
          <div className={s.listTools}>
            <Input size="sm" prefix={<Search />} placeholder="搜索标题或正文" value={ed.query} onChange={e => ed.setQuery(e.target.value)} aria-label="搜索笔记" wrapperClassName="" />
            <IconButton label="新建笔记" onClick={() => void ed.create().then(() => setListOpen(false))}>
              <FilePlus2 />
            </IconButton>
          </div>
          <div className={s.folders} aria-label="分类">
            {folders.map(f => (
              <Chip key={f.key} selected={ed.folder === f.key} onClick={() => ed.setFolder(f.key)}>
                {f.label} {f.count}
              </Chip>
            ))}
          </div>
        </div>
        <div className={s.listScroll}>
          {ed.visible.length === 0 ? (
            <Empty
              title={ed.query ? '没有找到' : '还没有笔记'}
              body={ed.query ? '换个关键词试试。' : '记下今天讲不顺的地方，教练回答时会引用它们。'}
              actions={
                !ed.query && (
                  <Button size="sm" variant="secondary" icon={<FilePlus2 />} onClick={() => void ed.create()}>
                    新建笔记
                  </Button>
                )
              }
            />
          ) : (
            ed.visible.map(n => (
              <button
                key={n._localId}
                type="button"
                className={s.item}
                aria-current={n._localId === ed.active?._localId ? 'true' : undefined}
                onClick={() => {
                  ed.open(n)
                  setListOpen(false)
                }}
              >
                <span className={s.itemTitle}>
                  {n._syncStatus !== 'synced' && <i className={s.syncDot} data-state={n._syncStatus} aria-label="未同步" />}
                  <span>{n.title || '未命名笔记'}</span>
                </span>
                <span className={s.itemExcerpt}>{excerpt(n.content)}</span>
                <span className={s.itemMeta}>
                  {when(n.updated_at)}
                  {(n.tags || []).slice(0, 2).map(t => (
                    <span key={t}>#{t}</span>
                  ))}
                </span>
              </button>
            ))
          )}
        </div>
      </nav>

      <section className={s.editor} aria-label="笔记编辑">
        {ed.active ? (
          <>
            <div className={s.editorBar}>
              <Button size="sm" variant="ghost" className="mx-show-compact" onClick={() => setListOpen(true)}>
                全部笔记
              </Button>
              <span className={s.status} data-state={statusState} role="status">
                <i aria-hidden />
                {statusText}
              </span>
              <span className={s.barSpacer} />
              <Segmented
                size="sm"
                ariaLabel="编辑或阅读"
                value={mode}
                onChange={setMode}
                options={[
                  { value: 'write', label: '编辑', icon: <Pencil /> },
                  { value: 'read', label: '阅读', icon: <Eye /> },
                ]}
              />
              {dirty && (
                <IconButton label="放弃未保存的修改" size="sm" onClick={ed.discardDraft}>
                  <Undo2 />
                </IconButton>
              )}
              <IconButton label="删除笔记" size="sm" onClick={() => setDeleting(true)}>
                <Trash2 />
              </IconButton>
              <Button size="sm" variant="primary" icon={<Save />} loading={ed.saving} disabled={!dirty} onClick={() => void save()}>
                保存
              </Button>
            </div>
            <div className={s.pageScroll}>
              <article className={s.page}>
                <input
                  className={s.titleInput}
                  value={ed.title}
                  onChange={e => ed.setTitle(e.target.value)}
                  placeholder="标题"
                  aria-label="笔记标题"
                  readOnly={mode === 'read'}
                />
                <div className={s.tagsRow}>
                  {ed.tags.map(t => (
                    <span key={t} className={s.tag}>
                      #{t}
                      {mode === 'write' && (
                        <button type="button" aria-label={`移除标签 ${t}`} onClick={() => ed.setTags(ed.tags.filter(x => x !== t))}>
                          <X />
                        </button>
                      )}
                    </span>
                  ))}
                  {mode === 'write' && (
                    <input
                      className={s.tagInput}
                      value={tagDraft}
                      onChange={e => setTagDraft(e.target.value)}
                      onKeyDown={e => {
                        if ((e.key === 'Enter' || e.key === ',' || e.key === '，') && !e.nativeEvent.isComposing) {
                          e.preventDefault()
                          addTag()
                        }
                        if (e.key === 'Backspace' && !tagDraft && ed.tags.length) ed.setTags(ed.tags.slice(0, -1))
                      }}
                      onBlur={addTag}
                      placeholder={ed.tags.length ? '+ 标签' : '添加标签，回车确认'}
                      aria-label="添加标签"
                    />
                  )}
                </div>
                {mode === 'write' ? (
                  <div className={`${s.md} mx-md`}>
                    <Suspense fallback={<Skeleton height={320} radius={10} />}>
                      <MarkdownLiveEditor
                        key={ed.active._localId}
                        ref={editorRef}
                        value={ed.content}
                        onChange={ed.setContent}
                        onUploadImage={uploadForEditor}
                        height="auto"
                        placeholder="从一个问题开始写：我今天真正理解了什么？"
                      />
                    </Suspense>
                  </div>
                ) : (
                  <div className={s.preview}>
                    {ed.content.trim() ? <Prose>{ed.content}</Prose> : <p style={{ color: 'var(--mx-text-3)' }}>这篇笔记还是空的。</p>}
                  </div>
                )}
              </article>
            </div>
          </>
        ) : (
          <Empty
            title="选择或新建一篇笔记"
            body="笔记会同步到本地数据库，离线时也能写。教练回答问题时会引用你的笔记。"
            actions={
              <Button variant="primary" icon={<FilePlus2 />} onClick={() => void ed.create()}>
                新建笔记
              </Button>
            }
          />
        )}
      </section>

      <Confirm
        open={deleting}
        onOpenChange={setDeleting}
        tone="danger"
        title="删除这篇笔记？"
        description={`「${ed.active?.title || '未命名笔记'}」会在同步后从所有设备删除。`}
        confirmLabel="删除"
        onConfirm={async () => {
          const ok = await ed.remove()
          if (!ok) {
            toast.error('删除失败')
            throw new Error('delete failed')
          }
          toast.success('已删除')
        }}
      />
      <ImportDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        onImported={async (items, warnings) => {
          let last = null
          for (const it of items) last = await ed.createNote({ title: it.title, content: it.content, note_type: 'general', tags: [] })
          if (last) ed.open(last)
          toast.success(`已导入 ${items.length} 篇笔记`, warnings ? { description: `有 ${warnings} 个提醒，比如找不到的图片附件。` } : undefined)
        }}
      />
      <VaultDialog open={vaultOpen} onOpenChange={setVaultOpen} />
    </div>
  )
}
