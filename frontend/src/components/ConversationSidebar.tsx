import { useEffect, useRef, useState } from 'react'
import { Input, Button, Dropdown, Modal, Tag, Empty, Tooltip, message } from 'antd'
import {
  PlusOutlined,
  SearchOutlined,
  PushpinOutlined,
  PushpinFilled,
  DeleteOutlined,
  EditOutlined,
  FolderOutlined,
  MessageOutlined,
  FileOutlined,
  AppstoreOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import { useChatStore } from '../stores/chatStore'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

interface ConversationSidebarProps {
  onOpenProjectSettings: (projectId?: number) => void
  onOpenProjectMaterials: () => void
  collapsed?: boolean
  onExpandSidebar?: (target?: 'default' | 'search' | 'categories' | 'history') => void
  expandTarget?: 'default' | 'search' | 'categories' | 'history' | null
  onExpandTargetHandled?: () => void
}

export function ConversationSidebar({
  onOpenProjectSettings,
  onOpenProjectMaterials,
  collapsed = false,
  onExpandSidebar,
  expandTarget = null,
  onExpandTargetHandled,
}: ConversationSidebarProps) {
  const {
    projects,
    conversations,
    activeConversationId,
    activeProjectId,
    searchQuery,
    createNewConversation,
    setActiveConversation,
    deleteConversation,
    renameConversation,
    moveConversation,
    pinConversation,
    searchConversations,
    setActiveProjectId,
    loadConversations,
  } = useChatStore()

  const [renameId, setRenameId] = useState<number | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [draggingConversationId, setDraggingConversationId] = useState<number | null>(null)
  const [dropTargetKey, setDropTargetKey] = useState<string | null>(null)
  const [displayLimit, setDisplayLimit] = useState(9)
  const [hoveredId, setHoveredId] = useState<number | null>(null)
  const [loadingConversationId, setLoadingConversationId] = useState<number | null>(null)
  const searchInputRef = useRef<any>(null)
  const searchSectionRef = useRef<HTMLDivElement | null>(null)
  const categorySectionRef = useRef<HTMLDivElement | null>(null)
  const historySectionRef = useRef<HTMLDivElement | null>(null)

  const getDropKey = (projectId: number | null) => (projectId === null ? 'drop-none' : `drop-${projectId}`)

  const handleDropToProject = async (projectId: number | null) => {
    if (draggingConversationId === null) return
    await moveConversation(draggingConversationId, projectId)
    setDraggingConversationId(null)
    setDropTargetKey(null)
  }

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        searchInputRef.current?.focus?.()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const highlightTitle = (title: string) => {
    const q = (searchQuery || '').trim()
    if (!q) return <span>{title}</span>
    const idx = title.toLowerCase().indexOf(q.toLowerCase())
    if (idx < 0) return <span>{title}</span>
    const before = title.slice(0, idx)
    const hit = title.slice(idx, idx + q.length)
    const after = title.slice(idx + q.length)
    return (
      <span>
        {before}
        <span style={{ background: '#fde68a', color: '#111827', padding: '0 2px', borderRadius: 3 }}>{hit}</span>
        {after}
      </span>
    )
  }

  const highlightText = (text: string) => {
    const q = (searchQuery || '').trim()
    if (!q || !text) return text
    const idx = text.toLowerCase().indexOf(q.toLowerCase())
    if (idx < 0) return text
    const before = text.slice(0, idx)
    const hit = text.slice(idx, idx + q.length)
    const after = text.slice(idx + q.length)
    return (
      <>
        {before}
        <span style={{ background: '#fde68a', color: '#111827', borderRadius: 3, padding: '0 2px' }}>{hit}</span>
        {after}
      </>
    )
  }

  const handleNewChat = async () => {
    await createNewConversation(activeProjectId)
  }

  const handleSearch = (value: string) => {
    searchConversations(value)
    setDisplayLimit(9) // 搜索时重置展示数量
  }

  const handleRename = async (id: number) => {
    if (renameValue.trim()) {
      await renameConversation(id, renameValue.trim())
    }
    setRenameId(null)
    setRenameValue('')
  }

  const handleDelete = (id: number) => {
    Modal.confirm({
      title: '删除对话',
      content: '确定要删除这个对话吗？所有消息将被永久删除。',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => deleteConversation(id),
    })
  }

  const handleProjectFilter = async (projectId: number | null) => {
    setActiveProjectId(projectId)
    if (projectId !== null) {
      await loadConversations(projectId)
    } else {
      await loadConversations()
    }
  }

  const handleOpenConversation = async (id: number) => {
    if (renameId === id || loadingConversationId === id) return
    setLoadingConversationId(id)
    try {
      const ok = await setActiveConversation(id)
      if (!ok) {
        message.error('加载历史对话失败，请稍后重试')
      }
    } finally {
      setLoadingConversationId(null)
    }
  }

  useEffect(() => {
    if (collapsed || !expandTarget) return

    requestAnimationFrame(() => {
      if (expandTarget === 'search') {
        searchSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        searchInputRef.current?.focus?.()
      } else if (expandTarget === 'categories') {
        categorySectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      } else {
        historySectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
      onExpandTargetHandled?.()
    })
  }, [collapsed, expandTarget, onExpandTargetHandled])

  const renderConversationItem = (conv: typeof conversations[0]) => {
    const isActive = conv.id === activeConversationId
    const isRenaming = renameId === conv.id
    const isHovered = hoveredId === conv.id

    return (
      <div
        key={conv.id}
        onClick={() => void handleOpenConversation(conv.id)}
        draggable={!isRenaming}
        onDragStart={(e) => {
          if (isRenaming) return
          setDraggingConversationId(conv.id)
          e.dataTransfer.effectAllowed = 'move'
          e.dataTransfer.setData('text/plain', String(conv.id))
        }}
        onDragEnd={() => {
          setDraggingConversationId(null)
          setDropTargetKey(null)
        }}
        onMouseEnter={() => setHoveredId(conv.id)}
        onMouseLeave={() => setHoveredId(null)}
        style={{
          padding: '10px 12px',
          cursor: 'pointer',
          background: isActive ? 'var(--gray-100)' : isHovered ? 'var(--gray-50)' : 'transparent',
          borderRadius: 'var(--radius-md)',
          marginBottom: 2,
          transition: 'all var(--duration-fast) var(--ease-out)',
        }}
      >
        {isRenaming ? (
          <Input
            size="small"
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onPressEnter={() => handleRename(conv.id)}
            onBlur={() => handleRename(conv.id)}
            autoFocus
            onClick={(e) => e.stopPropagation()}
            style={{ borderRadius: 'var(--radius-sm)' }}
          />
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontSize: 13.5,
                fontWeight: isActive ? 500 : 400,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
              }}>
                {conv.is_pinned && <PushpinFilled style={{ fontSize: 10, color: 'var(--accent-500)' }} />}
                <MessageOutlined style={{ fontSize: 11, color: 'var(--gray-400)', flexShrink: 0 }} />
                {highlightTitle(conv.title)}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 3 }}>
                {loadingConversationId === conv.id ? '加载中...' : dayjs(conv.updated_at).fromNow()}
              </div>
              {searchQuery.trim() && conv.matched_preview && (
                <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {highlightText(conv.matched_preview)}
                </div>
              )}
            </div>
            {(isHovered || isActive) && (
              <Dropdown
                trigger={['click']}
                menu={{
                  items: [
                    {
                      key: 'move-title',
                      icon: <FolderOutlined />,
                      label: '移动到项目',
                      disabled: true,
                    },
                    {
                      key: 'move-none',
                      label: '  设为通用（不归类）',
                      onClick: (e) => {
                        e.domEvent.stopPropagation()
                        moveConversation(conv.id, null)
                      },
                    },
                    ...projects.map((p) => ({
                      key: `move-${p.id}`,
                      label: (
                        <span>
                          <span
                            style={{
                              display: 'inline-block',
                              width: 8,
                              height: 8,
                              borderRadius: '50%',
                              background: p.color,
                              marginRight: 6,
                            }}
                          />
                          {p.name}
                        </span>
                      ),
                      onClick: (e: any) => {
                        e.domEvent.stopPropagation()
                        moveConversation(conv.id, p.id)
                      },
                    })),
                    { type: 'divider' as const },
                    {
                      key: 'rename',
                      icon: <EditOutlined />,
                      label: '重命名',
                      onClick: (e) => {
                        e.domEvent.stopPropagation()
                        setRenameId(conv.id)
                        setRenameValue(conv.title)
                      },
                    },
                    {
                      key: 'pin',
                      icon: conv.is_pinned ? <PushpinOutlined /> : <PushpinFilled />,
                      label: conv.is_pinned ? '取消置顶' : '置顶',
                      onClick: (e) => {
                        e.domEvent.stopPropagation()
                        pinConversation(conv.id, !conv.is_pinned)
                      },
                    },
                    { type: 'divider' },
                    {
                      key: 'delete',
                      icon: <DeleteOutlined />,
                      label: '删除',
                      danger: true,
                      onClick: (e) => {
                        e.domEvent.stopPropagation()
                        handleDelete(conv.id)
                      },
                    },
                  ],
                }}
              >
                <Button
                  type="text"
                  size="small"
                  onClick={(e) => e.stopPropagation()}
                  style={{
                    opacity: 0.6,
                    fontSize: 12,
                    width: 24,
                    height: 24,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-tertiary)',
                  }}
                >
                  ···
                </Button>
              </Dropdown>
            )}
          </div>
        )}
      </div>
    )
  }

  const splitByTime = (list: typeof conversations) => {
    const now = dayjs()
    const today: typeof conversations = []
    const week: typeof conversations = []
    const earlier: typeof conversations = []
    for (const c of list) {
      const t = dayjs(c.updated_at)
      if (t.isSame(now, 'day')) today.push(c)
      else if (t.isAfter(now.subtract(7, 'day'))) week.push(c)
      else earlier.push(c)
    }
    return { today, week, earlier }
  }

  const renderTimeGroupedList = (list: typeof conversations) => {
    const limited = list.slice(0, displayLimit)
    const hasMore = list.length > displayLimit
    const grouped = splitByTime(limited)
    const sections = [
      { key: 'today', label: '今天', data: grouped.today },
      { key: 'week', label: '近7天', data: grouped.week },
      { key: 'earlier', label: '更早', data: grouped.earlier },
    ]
    return (
      <>
        {sections.map((s) => {
          if (s.data.length === 0) return null
          return (
            <div key={s.key} style={{ marginBottom: 6 }}>
              <div style={{
                padding: '6px 14px 4px',
                fontSize: 11,
                fontWeight: 600,
                color: 'var(--text-tertiary)',
                letterSpacing: '0.5px',
                textTransform: 'uppercase',
              }}>
                {s.label}
              </div>
              {s.data.map(renderConversationItem)}
            </div>
          )
        })}
        {hasMore && (
          <div
            style={{ textAlign: 'center', padding: '6px 0 10px', cursor: 'pointer' }}
            onClick={() => setDisplayLimit((prev) => prev + 9)}
          >
            <span style={{ fontSize: 12, color: 'var(--accent-500)', userSelect: 'none' }}>
              展开更多（剩余 {list.length - displayLimit} 条）
            </span>
          </div>
        )}
      </>
    )
  }

  const renderEmptyState = () => {
    const isSearchMode = !!searchQuery.trim()
    if (isSearchMode) {
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="没有找到相关对话"
          style={{ marginTop: 40 }}
        >
          <Button size="small" onClick={() => handleSearch('')}>清空搜索</Button>
        </Empty>
      )
    }

    return (
      <div style={{
        textAlign: 'center',
        padding: '48px 20px',
      }}>
        <div style={{
          width: 48,
          height: 48,
          borderRadius: 'var(--radius-lg)',
          background: 'linear-gradient(135deg, var(--accent-100), var(--primary-100))',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          margin: '0 auto 16px',
          fontSize: 20,
        }}>
          💬
        </div>
        <div style={{ color: 'var(--text-primary)', fontSize: 14, fontWeight: 500, marginBottom: 6 }}>还没有学习记录</div>
        <div style={{ color: 'var(--text-tertiary)', fontSize: 12.5, marginBottom: 16, lineHeight: 1.5 }}>
          开始你的第一次学习对话吧
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleNewChat} style={{ borderRadius: 'var(--radius-md)' }}>
          开始学习
        </Button>
      </div>
    )
  }

  const renderCollapsedRail = () => {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '12px 0', gap: 6 }}>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 'var(--radius-lg)',
            background: 'linear-gradient(135deg, var(--accent-100), var(--primary-100))',
            color: 'var(--accent-700)',
            fontSize: 14,
            fontWeight: 700,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: 8,
          }}
        >
          学
        </div>

        <Tooltip title="新对话" placement="right" mouseEnterDelay={0.25}>
          <Button
            type="text"
            shape="circle"
            icon={<PlusOutlined />}
            onClick={() => {
              onExpandSidebar?.('default')
              void handleNewChat()
            }}
            style={{ width: 36, height: 36, color: 'var(--accent-600)' }}
          />
        </Tooltip>

        <Tooltip title="搜索" placement="right" mouseEnterDelay={0.25}>
          <Button
            type="text"
            shape="circle"
            icon={<SearchOutlined />}
            onClick={() => onExpandSidebar?.('search')}
            style={{ width: 36, height: 36, color: 'var(--text-tertiary)' }}
          />
        </Tooltip>

        <Tooltip title="学习分类" placement="right" mouseEnterDelay={0.25}>
          <Button
            type="text"
            shape="circle"
            icon={<AppstoreOutlined />}
            onClick={() => onExpandSidebar?.('categories')}
            style={{ width: 36, height: 36, color: 'var(--text-tertiary)' }}
          />
        </Tooltip>

        <Tooltip title="历史记录" placement="right" mouseEnterDelay={0.25}>
          <Button
            type="text"
            shape="circle"
            icon={<HistoryOutlined />}
            onClick={() => onExpandSidebar?.('history')}
            style={{ width: 36, height: 36, color: 'var(--text-tertiary)' }}
          />
        </Tooltip>
      </div>
    )
  }

  if (collapsed) {
    return renderCollapsedRail()
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', color: 'var(--text-primary)' }}>
      {/* New chat button */}
      <div style={{ padding: '14px 14px 10px' }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          block
          onClick={handleNewChat}
          style={{
            borderRadius: 'var(--radius-md)',
            height: 38,
            fontSize: 13.5,
            fontWeight: 500,
            background: 'var(--primary-600)',
            borderColor: 'var(--primary-600)',
          }}
        >
          新对话
        </Button>
      </div>

      {/* Search */}
      <div ref={searchSectionRef} style={{ padding: '0 14px 10px' }}>
        <Input
          ref={searchInputRef}
          placeholder="搜索对话..."
          prefix={<SearchOutlined style={{ color: 'var(--text-tertiary)' }} />}
          size="small"
          allowClear
          value={searchQuery}
          onChange={(e) => handleSearch(e.target.value)}
          style={{
            borderRadius: 'var(--radius-md)',
            background: 'var(--gray-50)',
            borderColor: 'transparent',
            height: 32,
          }}
          styles={{ input: { background: 'transparent', color: 'var(--text-primary)' } }}
        />
      </div>

      {/* Project filter tabs */}
      <div ref={categorySectionRef} style={{ padding: '0 14px 10px', display: 'flex', flexWrap: 'wrap', gap: 5 }}>
        <Tag
          style={{
            cursor: 'pointer',
            margin: 0,
            borderRadius: 'var(--radius-sm)',
            fontSize: 12,
            fontWeight: activeProjectId === null ? 600 : 400,
            background: activeProjectId === null ? 'var(--primary-600)' : (dropTargetKey === getDropKey(null) ? 'var(--accent-50)' : undefined),
            color: activeProjectId === null ? '#fff' : undefined,
            borderColor: activeProjectId === null ? 'var(--primary-600)' : (dropTargetKey === getDropKey(null) ? 'var(--accent-500)' : undefined),
          }}
          onClick={() => handleProjectFilter(null)}
          onDragOver={(e) => {
            if (draggingConversationId === null) return
            e.preventDefault()
            setDropTargetKey(getDropKey(null))
          }}
          onDragLeave={() => {
            if (dropTargetKey === getDropKey(null)) setDropTargetKey(null)
          }}
          onDrop={(e) => {
            e.preventDefault()
            void handleDropToProject(null)
          }}
        >
          全部
        </Tag>
        {projects.map((p) => {
          const isActive = activeProjectId === p.id
          const isDrop = dropTargetKey === getDropKey(p.id)
          return (
            <Tag
              key={p.id}
              style={{
                cursor: 'pointer',
                margin: 0,
                borderRadius: 'var(--radius-sm)',
                fontSize: 12,
                fontWeight: isActive ? 600 : 400,
                background: isActive ? p.color : (isDrop ? 'var(--accent-50)' : undefined),
                color: isActive ? '#fff' : undefined,
                borderColor: isActive ? p.color : (isDrop ? p.color : undefined),
              }}
              onClick={() => handleProjectFilter(p.id)}
              onDragOver={(e) => {
                if (draggingConversationId === null) return
                e.preventDefault()
                setDropTargetKey(getDropKey(p.id))
              }}
              onDragLeave={() => {
                if (dropTargetKey === getDropKey(p.id)) setDropTargetKey(null)
              }}
              onDrop={(e) => {
                e.preventDefault()
                void handleDropToProject(p.id)
              }}
            >
              {!isActive && (
                <span style={{
                  display: 'inline-block',
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: p.color,
                  marginRight: 4,
                }} />
              )}
              {p.name}
            </Tag>
          )
        })}
        <Tag
          style={{ cursor: 'pointer', borderStyle: 'dashed', margin: 0, borderRadius: 'var(--radius-sm)', fontSize: 12 }}
          onClick={() => onOpenProjectSettings()}
        >
          <PlusOutlined /> 项目
        </Tag>
      </div>

      {draggingConversationId !== null && (
        <div style={{
          padding: '4px 14px 8px',
          fontSize: 11,
          color: 'var(--accent-600)',
          background: 'var(--accent-50)',
          textAlign: 'center',
        }}>
          拖拽到上方项目标签即可移动该对话
        </div>
      )}

      {activeProjectId !== null && (
        <div style={{ padding: '0 14px 8px' }}>
          <Button
            size="small"
            icon={<FileOutlined />}
            onClick={onOpenProjectMaterials}
            style={{
              width: '100%',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-secondary)',
              borderColor: 'var(--border-color)',
            }}
          >
            打开项目资料库
          </Button>
        </div>
      )}

      {/* Conversation list */}
      <div ref={historySectionRef} style={{ flex: 1, overflow: 'auto', padding: '0 6px' }}>
        {conversations.length === 0 ? (
          renderEmptyState()
        ) : (
          renderTimeGroupedList(conversations)
        )}
      </div>
    </div>
  )
}
