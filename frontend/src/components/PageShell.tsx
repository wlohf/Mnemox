import { useState, type ReactNode } from 'react'
import { Layout, Menu, Popover, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  ClockCircleOutlined,
  SettingOutlined,
  ArrowLeftOutlined,
} from '@ant-design/icons'
import { GLOBAL_NAV_GROUPS, isGlobalNavGroupActive, isGlobalNavPathActive } from './Layout/GlobalNavRail'
import { SettingsModal } from './SettingsModal'

const { Sider, Content } = Layout

interface PageShellProps {
  title: ReactNode
  onBack: () => void
  rightExtra?: ReactNode
  maxWidth?: number
  children: ReactNode
}

export function PageShell({ title, onBack, rightExtra, maxWidth = 1200, children }: PageShellProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const [showSettings, setShowSettings] = useState(false)

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>
      {/* 64px Left Icon Sidebar */}
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
          M
        </div>

        <div className="mnemox-global-nav-stack">
          {GLOBAL_NAV_GROUPS.map(group => {
            const isActive = isGlobalNavGroupActive(location.pathname, group)
            const menuItems: MenuProps['items'] = group.children.map((item) => ({
              key: item.key,
              icon: item.icon,
              label: item.label,
            }))
            const selectedKeys = group.children
              .filter((item) => isGlobalNavPathActive(location.pathname, item.key))
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
                    onClick={({ key }) => navigate(String(key))}
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
          <Tooltip title="专注番茄钟" placement="right">
            <button
              type="button"
              onClick={() => navigate('/pomodoro')}
              className="mnemox-nav-item mnemox-utility-item"
              aria-label="专注番茄钟"
              style={{ color: 'var(--brand-400)', background: 'rgba(99, 102, 241, 0.1)' }}
            >
              <ClockCircleOutlined />
            </button>
          </Tooltip>
          <Tooltip title="设置" placement="right">
            <button
              type="button"
              className="mnemox-nav-item mnemox-utility-item"
              aria-label="设置"
              onClick={() => setShowSettings(true)}
            >
              <SettingOutlined />
            </button>
          </Tooltip>
        </div>
      </Sider>

      {/* Main Content Area */}
      <Layout style={{ marginLeft: 64, background: 'transparent' }}>
        <Content style={{ padding: '32px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ maxWidth, margin: '0 auto', width: '100%', flex: 1, display: 'flex', flexDirection: 'column' }}>
            
            {/* Inner Page Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 32 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <div 
                  onClick={onBack}
                  style={{
                    width: 36, height: 36, borderRadius: '50%',
                    background: 'var(--bg-surface)', border: '1px solid var(--border-light)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    cursor: 'pointer', color: 'var(--text-secondary)',
                    transition: 'all 0.2s',
                  }}
                  onMouseOver={(e) => e.currentTarget.style.color = 'var(--text-primary)'}
                  onMouseOut={(e) => e.currentTarget.style.color = 'var(--text-secondary)'}
                >
                  <ArrowLeftOutlined />
                </div>
                <span style={{ fontSize: 24, fontWeight: 600, color: 'var(--text-primary)', letterSpacing: 0 }}>{title}</span>
              </div>
              {rightExtra}
            </div>

            {/* Page Children */}
            <div style={{ flex: 1 }}>
              {children}
            </div>
          </div>
        </Content>
      </Layout>
      <SettingsModal open={showSettings} onClose={() => setShowSettings(false)} />
    </Layout>
  )
}
