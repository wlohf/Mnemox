import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeHighlight from 'rehype-highlight'
import rehypeKatex from 'rehype-katex'
import { useNavigate } from 'react-router-dom'
import { Layout, Card, Row, Col, Input, List, Button, Space, Tag, Modal, message, Select, Upload, Typography, Tabs } from 'antd'
import { ArrowLeftOutlined, PlusOutlined, SaveOutlined, DeleteOutlined, PictureOutlined, ImportOutlined, RobotOutlined, CopyOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useOfflineNotes, type OfflineNoteItem } from '../hooks/useOfflineNotes'
import { uploadImage } from '../services/imageApi'
import { importObsidianNote } from '../services/obsidianImportApi'
import { assistNoteWithAI, type NoteAIAssistAction } from '../services/noteApi'
import { MarkdownLiveEditor, type MarkdownLiveEditorHandle, type MarkdownLiveEditorImageResult } from '../components/MarkdownLiveEditor'
import '../components/ChatMessageBubble.css'

const { Header, Content } = Layout
const { Text } = Typography

const NOTE_AI_ACTIONS: Array<{ key: NoteAIAssistAction; label: string; description: string }> = [
  { key: 'continue', label: '续写', description: '根据当前内容继续补充例子、解释或小结' },
  { key: 'review', label: '检查遗漏', description: '检查是否遗漏重点并给出复习问题' },
  { key: 'restructure', label: '整理结构', description: '重组为更清晰的 Markdown 笔记' },
  { key: 'summarize', label: '摘要', description: '提炼摘要、关键词和三句话总结' },
]

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
  const editorRef = useRef<MarkdownLiveEditorHandle | null>(null)

  // AI assist state
  const [aiOpen, setAiOpen] = useState(false)
  const [aiAction, setAiAction] = useState<NoteAIAssistAction>('continue')
  const [aiInstruction, setAiInstruction] = useState('')
  const [aiSelectedText, setAiSelectedText] = useState('')
  const [aiSuggestion, setAiSuggestion] = useState('')
  const [aiPreviewMode, setAiPreviewMode] = useState<'preview' | 'edit'>('preview')
  const [aiLoading, setAiLoading] = useState(false)

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

  const doUploadImage = async (file: File) => {
    setUploading(true)
    const result = await uploadImage(file)
    setUploading(false)
    if (!result) {
      message.error('图片上传失败')
      return null
    }
    return result
  }

  const handleEditorImageUpload = async (file: File): Promise<MarkdownLiveEditorImageResult | null> => {
    const result = await doUploadImage(file)
    if (!result) return null
    return {
      url: result.url,
      markdown: result.markdown,
      alt: result.original_name || result.filename,
    }
  }

  const handleImageUpload = async (file: File) => {
    const result = await doUploadImage(file)
    if (!result) return
    const markdown = result.markdown || `![${result.original_name || 'image'}](${result.url})`
    const insertText = markdown.endsWith('\n') ? markdown : `${markdown}\n`
    if (!editorRef.current) {
      setContent((prev) => `${prev}${insertText}`)
      message.success('图片已插入')
      return
    }
    editorRef.current.insertText(insertText)
    message.success('图片已插入')
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

  const openAIAssist = () => {
    if (!active) {
      message.warning('请先选择笔记')
      return
    }
    if (!active._serverId || active._syncStatus !== 'synced') {
      message.warning('请先保存并同步笔记后再使用 AI 辅助')
      return
    }
    const latestEditorContent = editorRef.current?.getMarkdown() ?? content
    if (latestEditorContent !== active.content) {
      message.warning('当前编辑区有未保存修改，请先保存后再使用 AI 辅助，避免 AI 读取到旧内容')
      return
    }
    setAiSelectedText((editorRef.current?.getSelectedText() || '').trim().slice(0, 3000))
    setAiOpen(true)
    setAiSuggestion('')
    setAiPreviewMode('preview')
  }

  const refreshAISelectedText = () => {
    const selectedText = (editorRef.current?.getSelectedText() || aiSelectedText).trim().slice(0, 3000)
    setAiSelectedText(selectedText)
    return selectedText
  }

  const handleAIGenerate = async () => {
    if (!active?._serverId) {
      message.warning('请先保存并同步笔记后再使用 AI 辅助')
      return
    }
    if (!content.trim()) {
      message.warning('当前笔记内容为空，先写一点内容再让 AI 辅助吧')
      return
    }
    const latestEditorContent = editorRef.current?.getMarkdown() ?? content
    if (latestEditorContent !== active.content) {
      message.warning('当前编辑区有未保存修改，请先保存后再生成 AI 建议')
      return
    }
    const selectedText = refreshAISelectedText()
    setAiLoading(true)
    const result = await assistNoteWithAI(active._serverId, {
      action: aiAction,
      instruction: aiInstruction.trim() || undefined,
      selected_text: selectedText || undefined,
    })
    setAiLoading(false)
    if (!result || !result.ok) {
      message.error(result?.message || 'AI 辅助暂不可用，请检查 AI 设置或稍后重试')
      return
    }
    setAiSuggestion(result.suggestion)
    setAiPreviewMode('preview')
    message.success(result.message || '已生成 AI 建议')
  }

  const appendAISuggestion = () => {
    if (!aiSuggestion.trim()) return
    const next = `${content.trimEnd()}\n\n${aiSuggestion.trim()}\n`
    setContent(next)
    message.success('已追加到笔记末尾，请确认后保存')
  }

  const replaceWithAISuggestion = () => {
    if (!aiSuggestion.trim()) return
    Modal.confirm({
      title: '替换当前笔记内容？',
      content: 'AI 建议会替换编辑区全文，但不会自动保存；确认无误后请点击保存。',
      okText: '替换',
      cancelText: '取消',
      onOk: () => {
        setContent(aiSuggestion.trim())
        message.success('已替换编辑区内容，请确认后保存')
      },
    })
  }

  const copyAISuggestion = async () => {
    if (!aiSuggestion.trim()) return
    try {
      await navigator.clipboard.writeText(aiSuggestion)
      message.success('已复制 AI 建议')
    } catch {
      message.error('复制失败，请手动复制')
    }
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
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-base)' }}>
      <Header style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-light)', paddingInline: 16 }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', height: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回学习页</Button>
            <span style={{ fontSize: 16, fontWeight: 600 }}>笔记系统</span>
          </Space>
          <Space>
            <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入 Obsidian</Button>
            <Button icon={<PlusOutlined />} onClick={handleCreate}>新建笔记</Button>
            <Button icon={<RobotOutlined />} onClick={openAIAssist} disabled={!active}>AI 辅助</Button>
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
              <Card size="small" title={active ? '笔记内容' : '笔记内容'}>
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
                <div style={{ fontSize: 12, color: '#666', marginBottom: 6, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>实时渲染编辑区</span>
                  <Space size={4}>
                    {uploading && <span style={{ color: '#1890ff' }}>上传中...</span>}
                    <Button size="small" icon={<RobotOutlined />} onClick={openAIAssist} disabled={!active}>AI 辅助</Button>
                    <Upload
                      accept="image/png,image/jpeg,image/gif,image/webp,image/bmp"
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
                <MarkdownLiveEditor
                  ref={editorRef}
                  value={content}
                  onChange={setContent}
                  height="620px"
                  onUploadImage={handleEditorImageUpload}
                  placeholder="支持 Markdown；可直接输入、粘贴图片、拖拽图片或点击工具栏图片按钮..."
                />
              </Card>
            </Col>
          </Row>
        </div>
      </Content>

      {/* AI Assist Modal */}
      <Modal
        title="AI 辅助笔记"
        open={aiOpen}
        onCancel={() => setAiOpen(false)}
        footer={null}
        width={860}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Text type="secondary">
            AI 只生成建议，不会自动覆盖笔记。确认满意后可以追加、替换编辑区或复制。
            {aiSelectedText ? ` 已检测到选中文本（${aiSelectedText.length} 字），本次会优先围绕选中部分处理。` : ' 如需局部处理，可先在编辑器中选中文本再打开 AI 辅助。'}
          </Text>
          <Select
            value={aiAction}
            onChange={(v) => {
              setAiAction(v)
              setAiSuggestion('')
              setAiPreviewMode('preview')
              refreshAISelectedText()
            }}
            options={NOTE_AI_ACTIONS.map((item) => ({
              value: item.key,
              label: `${item.label} · ${item.description}`,
            }))}
            style={{ width: '100%' }}
          />
          <Input.TextArea
            value={aiInstruction}
            onChange={(e) => setAiInstruction(e.target.value)}
            placeholder="补充要求（可选）：例如更偏考试重点、保持口语化、围绕某一段展开..."
            autoSize={{ minRows: 2, maxRows: 4 }}
            maxLength={500}
            showCount
          />
          <Space>
            <Button type="primary" icon={<RobotOutlined />} loading={aiLoading} onClick={handleAIGenerate}>
              生成建议
            </Button>
            <Button icon={<CopyOutlined />} onClick={copyAISuggestion} disabled={!aiSuggestion.trim()}>
              复制
            </Button>
            <Button onClick={appendAISuggestion} disabled={!aiSuggestion.trim()}>
              追加到文末
            </Button>
            <Button danger onClick={replaceWithAISuggestion} disabled={!aiSuggestion.trim()}>
              替换编辑区全文
            </Button>
          </Space>
          <Tabs
            activeKey={aiPreviewMode}
            onChange={(key) => setAiPreviewMode(key as 'preview' | 'edit')}
            items={[
              {
                key: 'preview',
                label: '预览',
                children: (
                  <div className="chat-markdown" style={{ minHeight: 260, maxHeight: 520, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 8, padding: 16 }}>
                    {aiSuggestion.trim() ? (
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm, remarkMath]}
                        rehypePlugins={[rehypeHighlight, rehypeKatex]}
                        skipHtml
                      >
                        {aiSuggestion}
                      </ReactMarkdown>
                    ) : (
                      <Text type="secondary">AI 建议会显示在这里。生成后可切换到“编辑原文”进行微调。</Text>
                    )}
                  </div>
                ),
              },
              {
                key: 'edit',
                label: '编辑原文',
                children: (
                  <Input.TextArea
                    value={aiSuggestion}
                    onChange={(e) => setAiSuggestion(e.target.value)}
                    placeholder="AI 建议会显示在这里，你可以先编辑再追加/替换/复制。"
                    autoSize={{ minRows: 12, maxRows: 22 }}
                  />
                ),
              },
            ]}
          />
        </Space>
      </Modal>

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
              accept="image/png,image/jpeg,image/gif,image/webp,image/bmp"
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
