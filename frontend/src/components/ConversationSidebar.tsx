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
import { getApiErrorMessage } from '../services/apiClient'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import utc from 'dayjs/plugin/utc'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.extend(utc)
dayjs.locale('zh-cn')

const TIMEZONE_SUFFIX_RE = /(Z|[+-]\d{2}:?\d{2})$/i

function parseServerTime(value: string) {
  if (!value) return dayjs()
  return TIMEZONE_SUFFIX_RE.test(value) ? dayjs(value) : dayjs.utc(value).local()
}

interface ConversationSidebarProps {
  onOpenProjectSettings: (projectId?: number) => void
  onOpenProjectMaterials: () => void
  onConversationOpened?: (conversationId: number) => void
  collapsed?: boolean
  onExpandSidebar?: (target?: 'default' | 'search' | 'categories' | 'history') => void
  expandTarget?: 'default' | 'search' | 'categories' | 'history' | null
  onExpandTargetHandled?: () => void
}

export function ConversationSidebar({
  onOpenProjectSettings,
  onOpenProjectMaterials,
  onConversationOpened,
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
    try {
      await moveConversation(draggingConversationId, projectId)
    } catch (error) {
      message.error(getApiErrorMessage(error, '移动对话失败'))
    } finally {
      setDraggingConversationId(null)
      setDropTargetKey(null)
    }
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
    try {
      const conversation = await createNewConversation(activeProjectId)
      onConversationOpened?.(conversation.id)
    } catch (error) {
      message.error(getApiErrorMessage(error, '创建对话失败，请检查后端服务'))
    }
  }

  const handleSearch = (value: string) => {
    searchConversations(value)
    setDisplayLimit(9) // 搜索时重置展示数量
  }

  const handleRename = async (id: number) => {
    if (renameValue.trim()) {
      try {
        await renameConversation(id, renameValue.trim())
      } catch (error) {
        message.error(getApiErrorMessage(error, '重命名对话失败'))
      }
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
      onOk: async () => {
        try {
          await deleteConversation(id)
        } catch (error) {
          message.error(getApiErrorMessage(error, '删除对话失败'))
        }
      },
    })
  }

  const handleProjectFilter = async (projectId: number | null) => {
    setActiveProjectId(projectId)
    try {
      if (projectId !== null) {
        await loadConversations(projectId)
      } else {
        await loadConversations()
      }
    } catch (error) {
      message.error(getApiErrorMessage(error, '加载对话列表失败'))
    }
  }

  const handleOpenConversation = async (id: number) => {
    if (renameId === id || loadingConversationId === id) return
    setLoadingConversationId(id)
    try {
      const ok = await setActiveConversation(id)
      if (!ok) {
        message.error('加载历史对话失败，请稍后重试')
        return
      }
      onConversationOpened?.(id)
    } catch (error) {
      message.error(getApiErrorMessage(error, '加载历史对话失败，请稍后重试'))
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
        className={`mnemox-conversation-item${isActive ? ' is-active' : ''}${isHovered ? ' is-hovered' : ''}`}
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
          <div className="mnemox-conversation-row">
            <div className="mnemox-conversation-main">
              <div className="mnemox-conversation-title">
                {conv.is_pinned && <PushpinFilled className="mnemox-conversation-pin" />}
                <MessageOutlined className="mnemox-conversation-icon" />
                {highlightTitle(conv.title)}
              </div>
              <div className="mnemox-conversation-time">
                {loadingConversationId === conv.id ? '加载中...' : parseServerTime(conv.updated_at).fromNow()}
              </div>
              {searchQuery.trim() && conv.matched_preview && (
                <div className="mnemox-conversation-preview">
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
                  className="mnemox-conversation-more"
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
      const t = parseServerTime(c.updated_at)
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
            <div key={s.key} className="mnemox-conversation-section">
              <div className="mnemox-conversation-section-title">
                {s.label}
              </div>
              {s.data.map(renderConversationItem)}
            </div>
          )
        })}
        {hasMore && (
          <button
            type="button"
            className="mnemox-sidebar-more"
            onClick={() => setDisplayLimit((prev) => prev + 9)}
          >
            展开更多（剩余 {list.length - displayLimit} 条）
          </button>
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
      <div className="mnemox-sidebar-empty">
        <div className="mnemox-sidebar-empty-icon">
          <MessageOutlined />
        </div>
        <div className="mnemox-sidebar-empty-title">还没有学习记录</div>
        <div className="mnemox-sidebar-empty-copy">
          新建一次对话，Mnemox 会把上下文和资料自动串起来。
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleNewChat}>
          开始学习
        </Button>
      </div>
    )
  }

  const renderCollapsedRail = () => {
    return (
      <div className="mnemox-sidebar-rail">
        <div className="mnemox-sidebar-rail-mark">
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
            className="mnemox-sidebar-rail-button is-primary"
          />
        </Tooltip>

        <Tooltip title="搜索" placement="right" mouseEnterDelay={0.25}>
          <Button
            type="text"
            shape="circle"
            icon={<SearchOutlined />}
            onClick={() => onExpandSidebar?.('search')}
            className="mnemox-sidebar-rail-button"
          />
        </Tooltip>

        <Tooltip title="学习分类" placement="right" mouseEnterDelay={0.25}>
          <Button
            type="text"
            shape="circle"
            icon={<AppstoreOutlined />}
            onClick={() => onExpandSidebar?.('categories')}
            className="mnemox-sidebar-rail-button"
          />
        </Tooltip>

        <Tooltip title="历史记录" placement="right" mouseEnterDelay={0.25}>
          <Button
            type="text"
            shape="circle"
            icon={<HistoryOutlined />}
            onClick={() => onExpandSidebar?.('history')}
            className="mnemox-sidebar-rail-button"
          />
        </Tooltip>
      </div>
    )
  }

  if (collapsed) {
    return renderCollapsedRail()
  }

  return (
    <div className="mnemox-sidebar-shell">
      <div className="mnemox-sidebar-action">
        <Button
          type="primary"
          icon={<PlusOutlined />}
          block
          onClick={handleNewChat}
          className="mnemox-new-chat-button"
        >
          新对话
        </Button>
      </div>

      <div ref={searchSectionRef} className="mnemox-sidebar-search">
        <Input
          id="conversation-search"
          name="conversation-search"
          aria-label="搜索对话"
          ref={searchInputRef}
          placeholder="搜索对话..."
          prefix={<SearchOutlined style={{ color: 'var(--text-tertiary)' }} />}
          size="small"
          allowClear
          value={searchQuery}
          onChange={(e) => handleSearch(e.target.value)}
          className="mnemox-sidebar-search-input"
          styles={{ input: { background: 'transparent', color: 'var(--text-primary)' } }}
        />
      </div>

      <div ref={categorySectionRef} className="mnemox-sidebar-projects">
        <Tag
          className={`mnemox-project-chip${activeProjectId === null ? ' is-active' : ''}${dropTargetKey === getDropKey(null) ? ' is-drop-target' : ''}`}
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
              className={`mnemox-project-chip${isActive ? ' is-active' : ''}${isDrop ? ' is-drop-target' : ''}`}
              style={{
                background: isActive ? p.color : undefined,
                borderColor: isActive || isDrop ? p.color : undefined,
                color: isActive ? '#fff' : undefined,
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
                <span className="mnemox-project-dot" style={{ background: p.color }} />
              )}
              {p.name}
            </Tag>
          )
        })}
        <Tag
          className="mnemox-project-chip is-add"
          onClick={() => onOpenProjectSettings()}
        >
          <PlusOutlined /> 项目
        </Tag>
      </div>

      {draggingConversationId !== null && (
        <div className="mnemox-sidebar-drag-hint">
          拖拽到上方项目标签即可移动该对话
        </div>
      )}

      {activeProjectId !== null && (
        <div className="mnemox-sidebar-materials-action">
          <Button
            size="small"
            icon={<FileOutlined />}
            onClick={onOpenProjectMaterials}
            className="mnemox-sidebar-secondary-button"
          >
            打开项目资料库
          </Button>
        </div>
      )}

      <div ref={historySectionRef} className="mnemox-sidebar-history">
        {conversations.length === 0 ? (
          renderEmptyState()
        ) : (
          renderTimeGroupedList(conversations)
        )}
      </div>
    </div>
  )
}
