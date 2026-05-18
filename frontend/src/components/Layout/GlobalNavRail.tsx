import type { ReactNode } from 'react'
import { Layout, Menu, Popover, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import {
  BookOutlined,
  BarChartOutlined,
  CalendarOutlined,
  CheckSquareOutlined,
  ClockCircleOutlined,
  CreditCardOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  MessageOutlined,
  QuestionCircleOutlined,
  RocketOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { MnemoxLogo } from '../MnemoxLogo'

const { Sider } = Layout

interface GlobalNavDestination {
  key: string
  icon: ReactNode
  label: string
  advanced?: boolean
}

interface GlobalNavGroup {
  key: string
  icon: ReactNode
  label: string
  advanced?: boolean
  children: GlobalNavDestination[]
}

export const GLOBAL_NAV_GROUPS: GlobalNavGroup[] = [
  {
    key: 'workspace',
    icon: <MessageOutlined />,
    label: '学习工作台',
    children: [
      { key: '/', icon: <MessageOutlined />, label: '学习助手' },
      { key: '/dashboard', icon: <DashboardOutlined />, label: '今日概览' },
    ],
  },
  {
    key: 'ai',
    icon: <ExperimentOutlined />,
    label: 'AI 与洞察',
    advanced: true,
    children: [
      { key: '/agent', icon: <ExperimentOutlined />, label: '自主 Agent' },
      { key: '/eda', icon: <BarChartOutlined />, label: '洞察干预' },
    ],
  },
  {
    key: 'knowledge',
    icon: <BookOutlined />,
    label: '复习资料',
    children: [
      { key: '/review', icon: <BookOutlined />, label: '复习' },
      { key: '/wrong-questions', icon: <QuestionCircleOutlined />, label: '错题本', advanced: true },
      { key: '/notes', icon: <FileTextOutlined />, label: '笔记' },
      { key: '/anki', icon: <CreditCardOutlined />, label: 'Anki卡片', advanced: true },
    ],
  },
  {
    key: 'planning',
    icon: <CalendarOutlined />,
    label: '计划任务',
    children: [
      { key: '/plans', icon: <CalendarOutlined />, label: '学习计划' },
      { key: '/goals', icon: <CheckSquareOutlined />, label: '任务目标', advanced: true },
    ],
  },
]

export function isGlobalNavPathActive(pathname: string, path: string) {
  return path === '/' ? pathname === '/' : pathname.startsWith(path)
}

export function isGlobalNavGroupActive(pathname: string, group: GlobalNavGroup) {
  return group.children.some((item) => isGlobalNavPathActive(pathname, item.key))
}

interface GlobalNavRailProps {
  pathname: string
  isRunning: boolean
  isPaused: boolean
  remainingTimeLabel: string
  onNavigate: (path: string) => void
  onOpenPomodoro: () => void
  onOpenOnboarding: () => void
  onOpenSettings: () => void
  beginnerMode: boolean
  onToggleBeginnerMode: () => void
}

export function GlobalNavRail({
  pathname,
  isRunning,
  isPaused,
  remainingTimeLabel,
  onNavigate,
  onOpenPomodoro,
  onOpenOnboarding,
  onOpenSettings,
  beginnerMode,
  onToggleBeginnerMode,
}: GlobalNavRailProps) {
  const timerTitle = isRunning
    ? `番茄钟 ${remainingTimeLabel}`
    : isPaused
      ? `已暂停 ${remainingTimeLabel}`
      : '专注番茄钟'
  const settingsMenuItems: MenuProps['items'] = [
    { key: 'settings', icon: <SettingOutlined />, label: '设置' },
    { key: 'onboarding', icon: <RocketOutlined />, label: '新手引导 / Demo' },
    {
      key: 'learner-mode',
      icon: <DashboardOutlined />,
      label: beginnerMode ? '显示高级功能' : '切回精简学习模式',
    },
  ]
  const visibleGroups = GLOBAL_NAV_GROUPS
    .filter((group) => !beginnerMode || !group.advanced)
    .map((group) => ({
      ...group,
      children: group.children.filter((item) => !beginnerMode || !item.advanced),
    }))
    .filter((group) => group.children.length > 0)

  return (
    <Sider
      className="mnemox-global-nav-rail"
      width={64}
      style={{
        background: 'var(--bg-surface)',
        borderRight: '1px solid var(--border-light)',
        position: 'fixed',
        left: 0,
        top: 0,
        bottom: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '16px 0',
        zIndex: 100,
      }}
    >
      <div className="mnemox-global-nav-logo">
        <MnemoxLogo size={40} />
      </div>

      <div className="mnemox-global-nav-stack">
        {visibleGroups.map((group) => {
          const isActive = isGlobalNavGroupActive(pathname, group)
          const menuItems: MenuProps['items'] = group.children.map((item) => ({
            key: item.key,
            icon: item.icon,
            label: item.label,
          }))
          const selectedKeys = group.children
            .filter((item) => isGlobalNavPathActive(pathname, item.key))
            .map((item) => item.key)
          return (
            <Popover
              key={group.key}
              placement="rightTop"
              trigger="click"
              arrow={false}
              overlayClassName="mnemox-nav-popover"
              content={(
                <Menu
                  className="mnemox-nav-popover-menu"
                  items={menuItems}
                  selectable
                  selectedKeys={selectedKeys}
                  onClick={({ key }) => onNavigate(String(key))}
                />
              )}
            >
              <button
                type="button"
                className={`mnemox-nav-item${isActive ? ' is-active' : ''}`}
                aria-label={group.label}
                title={group.label}
              >
                {group.icon}
              </button>
            </Popover>
          )
        })}
      </div>

      <div className="mnemox-global-nav-utility">
        <Tooltip title={timerTitle} placement="right">
          <button
            type="button"
            onClick={onOpenPomodoro}
            className={`mnemox-nav-item mnemox-utility-item${isRunning ? ' is-timer-running' : isPaused ? ' is-timer-paused' : ''}`}
            aria-label={timerTitle}
            style={{
              color: isRunning ? 'var(--error)' : isPaused ? 'var(--warning)' : 'var(--brand-400)',
              background: isRunning ? 'rgba(251, 113, 133, 0.1)' : isPaused ? 'rgba(251, 191, 36, 0.1)' : 'rgba(99, 102, 241, 0.1)',
              border: isRunning || isPaused ? `1px solid ${isRunning ? 'var(--error)' : 'var(--warning)'}` : 'none',
            }}
          >
            <ClockCircleOutlined />
          </button>
        </Tooltip>
        <Popover
          placement="rightBottom"
          trigger="click"
          arrow={false}
          overlayClassName="mnemox-nav-popover"
          content={(
            <Menu
              className="mnemox-nav-popover-menu"
              items={settingsMenuItems}
              onClick={({ key }) => {
                if (key === 'settings') onOpenSettings()
                if (key === 'onboarding') onOpenOnboarding()
                if (key === 'learner-mode') onToggleBeginnerMode()
              }}
            />
          )}
        >
          <button
            type="button"
            className="mnemox-nav-item mnemox-utility-item"
            aria-label="设置与引导"
            title="设置与引导"
          >
            <SettingOutlined />
          </button>
        </Popover>
      </div>
    </Sider>
  )
}
