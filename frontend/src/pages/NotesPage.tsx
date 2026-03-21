import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layout, Card, Row, Col, Input, List, Button, Space, Tag, Modal, message, Select, Upload } from 'antd'
import { ArrowLeftOutlined, PlusOutlined, SaveOutlined, DeleteOutlined, PictureOutlined, ImportOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeHighlight from 'rehype-highlight'
import rehypeKatex from 'rehype-katex'
import 'highlight.js/styles/github-dark.css'
import 'katex/dist/katex.min.css'
import { useOfflineNotes, type OfflineNoteItem } from '../hooks/useOfflineNotes'
import { uploadImage } from '../services/imageApi'
import { importObsidianNote } from '../services/obsidianImportApi'

const { Header, Content } = Layout
const { TextArea } = Input

export function NotesPage() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [filterTag, setFilterTag] = useState<string | undefined>(undefined)
  const { notes, createNote, updateNote, deleteNote } = useOfflineNotes({ q: q.trim() || undefined, tag: filterTag })

  const [active, setActive] = useState<OfflineNoteItem | null>(null)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [tagsText, setTagsText] = useState('')
  const [saving, setSaving] = useState(false)

  // Image upload state
  const [uploading, setUploading] = useState(false)
  const selectionRef = useRef<{ start: number; end: number }>({ start: 0, end: 0 })
  const textAreaRef = useRef<HTMLTextAreaElement | null>(null)

  // Obsidian import modal state
  const [importOpen, setImportOpen] = useState(false)
  const [importMdFile, setImportMdFile] = useState<File | null>(null)
  const [importAttachments, setImportAttachments] = useState<File[]>([])
  const [importing, setImporting] = useState(false)

  // Auto-select first note when notes change and no active note
  useEffect(() => {
    if (notes.length > 0 && !active) {
      openNote(notes[0])
    } else if (notes.length === 0) {
      setActive(null)
      setTitle('')
      setContent('')
      setTagsText('')
    } else if (active) {
      // Refresh active note data if it still exists
      const latest = notes.find((n) => n._localId === active._localId)
      if (!latest) {
        // Active note was deleted
        if (notes.length > 0) {
          openNote(notes[0])
        } else {
          setActive(null)
          setTitle('')
          setContent('')
          setTagsText('')
        }
      }
    }
  }, [notes.length])

  const openNote = (n: OfflineNoteItem) => {
    setActive(n)
    setTitle(n.title || '')
    setContent(n.content || '')
    setTagsText((n.tags || []).join(', '))
  }

  const extractTags = (n: OfflineNoteItem): string[] => n.tags || []

  // Insert text at cursor position in the content
  const insertAtCursor = (text: string) => {
    const { start, end } = selectionRef.current
    const before = content.slice(0, start)
    const after = content.slice(end)
    const newContent = before + text + after
    setContent(newContent)
    const newPos = start + text.length
    selectionRef.current = { start: newPos, end: newPos }
  }

  // Handle image file upload and insert markdown
  const handleImageUpload = async (file: File) => {
    setUploading(true)
    const result = await uploadImage(file)
    setUploading(false)
    if (!result) {
      message.error('图片上传失败')
      return
    }
    insertAtCursor(result.markdown + '\n')
    message.success('图片已插入')
  }

  // Paste handler
  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items
    if (!items) return
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault()
        const file = item.getAsFile()
        if (file) void handleImageUpload(file)
        return
      }
    }
  }

  // Drag-drop handler
  const handleDrop = (e: React.DragEvent) => {
    const files = e.dataTransfer?.files
    if (!files) return
    for (const file of files) {
      if (file.type.startsWith('image/')) {
        e.preventDefault()
        void handleImageUpload(file)
        return
      }
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    if (e.dataTransfer?.types?.includes('Files')) {
      e.preventDefault()
    }
  }

  const handleSelect = (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget
    selectionRef.current = { start: el.selectionStart, end: el.selectionEnd }
  }

  // Obsidian import handler (still uses online API for the import itself)
  const handleObsidianImport = async () => {
    if (!importMdFile) {
      message.warning('请选择 Markdown 文件')
      return
    }
    setImporting(true)
    const result = await importObsidianNote(importMdFile, importAttachments)
    setImporting(false)
    if (!result) {
      message.error('导入失败')
      return
    }
    if (result.warnings.length > 0) {
      message.warning(`导入完成，但有 ${result.warnings.length} 个警告`)
    }
    // Create via offline hook
    const created = await createNote({
      title: result.title,
      content: result.content,
      note_type: 'general',
      tags: [],
    })
    message.success(`已导入笔记，上传了 ${result.images_uploaded} 张图片`)
    setImportOpen(false)
    setImportMdFile(null)
    setImportAttachments([])
    openNote(created)
  }

  const handleCreate = async () => {
    const created = await createNote({
      title: '新笔记',
      content: '',
      note_type: 'general',
      tags: [],
    })
    message.success('已创建笔记')
    openNote(created)
  }

  const handleSave = async () => {
    if (!active) {
      message.warning('请先选择笔记')
      return
    }
    const tags = tagsText
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 12)
    setSaving(true)
    const saved = await updateNote(active._localId, { title, content, tags })
    setSaving(false)
    if (!saved) {
      message.error('保存失败')
      return
    }
    message.success('已保存')
    setActive(saved)
  }

  const handleDelete = () => {
    if (!active) return
    Modal.confirm({
      title: '删除笔记',
      content: '确定删除这条笔记吗？',
      okType: 'danger',
      onOk: async () => {
        const ok = await deleteNote(active._localId)
        if (!ok) {
          message.error('删除失败')
          return
        }
        message.success('已删除')
        setActive(null)
      },
    })
  }

  return (
    <Layout style={{ minHeight: '100vh', background: '#f7f8fa' }}>
      <Header style={{ background: '#fff', borderBottom: '1px solid #f0f0f0', paddingInline: 16 }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', height: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回学习页</Button>
            <span style={{ fontSize: 16, fontWeight: 600 }}>笔记系统</span>
          </Space>
          <Space>
            <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入 Obsidian</Button>
            <Button icon={<PlusOutlined />} onClick={handleCreate}>新建笔记</Button>
            <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存</Button>
            <Button danger icon={<DeleteOutlined />} onClick={handleDelete} disabled={!active}>删除</Button>
          </Space>
        </div>
      </Header>
      <Content style={{ padding: 16 }}>
        <div style={{ maxWidth: 1280, margin: '0 auto' }}>
          <Row gutter={[16, 16]}>
            <Col xs={24} lg={8}>
              <Card
                size="small"
                title="笔记列表"
                extra={<Tag color="blue">{notes.length}</Tag>}
              >
                <Space direction="vertical" style={{ marginBottom: 10, width: '100%' }}>
                  <Input.Search
                    allowClear
                    placeholder="搜索标题或正文"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    onSearch={(v) => setQ(v.trim())}
                  />
                  <Select
                    allowClear
                    placeholder="按标签筛选"
                    value={filterTag}
                    onChange={(v) => setFilterTag(v)}
                    options={Array.from(new Set(notes.flatMap((n) => n.tags || []))).map((t) => ({ label: t, value: t }))}
                  />
                </Space>
                <List
                  dataSource={notes}
                  locale={{ emptyText: '暂无笔记' }}
                  renderItem={(n) => (
                    <List.Item
                      style={{ cursor: 'pointer', background: active?._localId === n._localId ? '#e6f7ff' : 'transparent', borderRadius: 6, paddingInline: 8 }}
                      onClick={() => openNote(n)}
                    >
                      <List.Item.Meta
                        title={
                          <Space size={4}>
                            <span style={{ fontSize: 13 }}>{n.title || '无标题'}</span>
                            {n._syncStatus !== 'synced' && (
                              <Tag color="orange" style={{ fontSize: 10 }}>未同步</Tag>
                            )}
                          </Space>
                        }
                        description={
                          <Space size={4} wrap>
                            <span style={{ fontSize: 11, color: '#999' }}>
                              {n.updated_at ? dayjs(n.updated_at).format('YYYY-MM-DD HH:mm') : '-'}
                            </span>
                            {extractTags(n).map((t) => (
                              <Tag key={`${n._localId}-${t}`} style={{ fontSize: 10 }}>{t}</Tag>
                            ))}
                          </Space>
                        }
                      />
                    </List.Item>
                  )}
                />
              </Card>
            </Col>

            <Col xs={24} lg={16}>
              <Card size="small" title={active ? '编辑笔记' : '笔记内容'}>
                <Input
                  placeholder="笔记标题"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  style={{ marginBottom: 10 }}
                />
                <Input
                  placeholder="标签（逗号分隔）"
                  value={tagsText}
                  onChange={(e) => setTagsText(e.target.value)}
                  style={{ marginBottom: 10 }}
                />
                <Row gutter={12}>
                  <Col xs={24} xl={12}>
                    <div style={{ fontSize: 12, color: '#666', marginBottom: 6, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>编辑区</span>
                      <Space size={4}>
                        {uploading && <span style={{ color: '#1890ff' }}>上传中...</span>}
                        <Upload
                          accept="image/*"
                          showUploadList={false}
                          beforeUpload={(file) => {
                            void handleImageUpload(file)
                            return false
                          }}
                        >
                          <Button size="small" icon={<PictureOutlined />}>插入图片</Button>
                        </Upload>
                      </Space>
                    </div>
                    <div
                      onPaste={handlePaste}
                      onDrop={handleDrop}
                      onDragOver={handleDragOver}
                    >
                      <TextArea
                        ref={(el) => { textAreaRef.current = el?.resizableTextArea?.textArea ?? null }}
                        value={content}
                        onChange={(e) => setContent(e.target.value)}
                        onSelect={handleSelect}
                        onClick={handleSelect}
                        onKeyUp={handleSelect}
                        autoSize={{ minRows: 20, maxRows: 26 }}
                        placeholder="支持 Markdown，可粘贴或拖入图片..."
                      />
                    </div>
                  </Col>
                  <Col xs={24} xl={12}>
                    <div style={{ fontSize: 12, color: '#666', marginBottom: 6 }}>预览区</div>
                    <div style={{ minHeight: 360, maxHeight: 620, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 8, padding: 12, background: '#fff' }}>
                      {content.trim() ? (
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm, remarkMath]}
                          rehypePlugins={[rehypeHighlight, rehypeKatex]}
                          components={{
                            img: ({ node, ...props }) => (
                              <img
                                {...props}
                                style={{ maxWidth: '100%', borderRadius: 6, cursor: 'pointer' }}
                                onClick={() => props.src && window.open(props.src, '_blank')}
                              />
                            ),
                          }}
                        >
                          {content}
                        </ReactMarkdown>
                      ) : (
                        <span style={{ color: '#999' }}>暂无内容预览</span>
                      )}
                    </div>
                  </Col>
                </Row>
              </Card>
            </Col>
          </Row>
        </div>
      </Content>

      {/* Obsidian Import Modal */}
      <Modal
        title="导入 Obsidian 笔记"
        open={importOpen}
        onCancel={() => { setImportOpen(false); setImportMdFile(null); setImportAttachments([]) }}
        onOk={handleObsidianImport}
        confirmLoading={importing}
        okText="导入"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <div style={{ marginBottom: 6, fontWeight: 500 }}>Markdown 文件</div>
            <Upload
              accept=".md,.markdown"
              maxCount={1}
              beforeUpload={(file) => {
                setImportMdFile(file)
                return false
              }}
              onRemove={() => setImportMdFile(null)}
              fileList={importMdFile ? [{ uid: '-1', name: importMdFile.name, status: 'done' as const }] : []}
            >
              <Button>选择 .md 文件</Button>
            </Upload>
          </div>
          <div>
            <div style={{ marginBottom: 6, fontWeight: 500 }}>附件图片（可选）</div>
            <Upload
              accept="image/*"
              multiple
              beforeUpload={(_file, fileList) => {
                setImportAttachments((prev) => [...prev, ...fileList.filter((f) => !prev.some((p) => p.name === f.name && p.size === f.size))])
                return false
              }}
              onRemove={(file) => {
                setImportAttachments((prev) => prev.filter((f) => f.name !== file.name || f.size !== file.size))
              }}
              fileList={importAttachments.map((f, i) => ({ uid: String(i), name: f.name, status: 'done' as const }))}
            >
              <Button>选择附件图片</Button>
            </Upload>
            <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
              上传笔记中引用的图片文件（如 ![[image.png]] 引用的图片）
            </div>
          </div>
        </Space>
      </Modal>
    </Layout>
  )
}
