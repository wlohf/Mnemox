import type { ReactNode } from 'react'
import { Layout, Tooltip } from 'antd'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  DashboardOutlined,
  BookOutlined,
  CheckSquareOutlined,
  QuestionCircleOutlined,
  FileTextOutlined,
  CreditCardOutlined,
  CalendarOutlined,
  SettingOutlined,
  ArrowLeftOutlined,
  MessageOutlined
} from '@ant-design/icons'

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
  
  const navItems = [
    { key: '/', icon: <MessageOutlined />, label: '学习助手' },
    { key: '/dashboard', icon: <DashboardOutlined />, label: '今日概览' },
    { key: '/review', icon: <BookOutlined />, label: '复习' },
    { key: '/goals', icon: <CheckSquareOutlined />, label: '任务目标' },
    { key: '/wrong-questions', icon: <QuestionCircleOutlined />, label: '错题本' },
    { key: '/notes', icon: <FileTextOutlined />, label: '笔记' },
    { key: '/anki', icon: <CreditCardOutlined />, label: 'Anki卡片' },
    { key: '/plans', icon: <CalendarOutlined />, label: '学习计划' },
  ]

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>
      {/* 64px Left Icon Sidebar */}
      <Sider
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
        <div style={{ 
          width: 40, height: 40, borderRadius: '12px', 
          background: 'linear-gradient(135deg, var(--brand-500), var(--brand-400))',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#fff', fontSize: 20, fontWeight: 'bold', marginBottom: 32,
          boxShadow: '0 4px 12px rgba(99, 102, 241, 0.3)'
        }}>
          S
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, flex: 1, width: '100%', alignItems: 'center' }}>
          {navItems.map(item => {
            const isActive = location.pathname === item.key || (item.key !== '/' && location.pathname.startsWith(item.key))
            return (
              <Tooltip key={item.key} title={item.label} placement="right">
                <div
                  onClick={() => navigate(item.key)}
                  style={{
                    width: 44, height: 44, borderRadius: '12px',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    cursor: 'pointer', fontSize: 20,
                    color: isActive ? 'var(--brand-400)' : 'var(--text-secondary)',
                    background: isActive ? 'var(--primary-100)' : 'transparent',
                    transition: 'all 0.2s',
                    position: 'relative',
                  }}
                >
                  {isActive && (
                    <div style={{
                      position: 'absolute', left: -10, top: 12, bottom: 12, width: 4, 
                      background: 'var(--brand-500)', borderRadius: '0 4px 4px 0'
                    }} />
                  )}
                  {item.icon}
                </div>
              </Tooltip>
            )
          })}
        </div>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, alignItems: 'center' }}>
          <Tooltip title="专注番茄钟" placement="right">
            <div 
              onClick={() => navigate('/pomodoro')}
              style={{ width: 44, height: 44, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: 'var(--brand-400)', fontSize: 20, background: 'rgba(99, 102, 241, 0.1)', borderRadius: '12px', transition: 'all 0.2s' }}
              onMouseOver={(e) => e.currentTarget.style.background = 'rgba(99, 102, 241, 0.2)'}
              onMouseOut={(e) => e.currentTarget.style.background = 'rgba(99, 102, 241, 0.1)'}
            >
              ⏱
            </div>
          </Tooltip>
          <Tooltip title="设置" placement="right">
            <div style={{ width: 44, height: 44, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: 'var(--text-secondary)', fontSize: 20 }}>
              <SettingOutlined />
            </div>
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
                <span style={{ fontSize: 24, fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.02em' }}>{title}</span>
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
    </Layout>
  )
}
