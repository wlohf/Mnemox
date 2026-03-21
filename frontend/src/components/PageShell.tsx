import type { ReactNode } from 'react'
import { Layout, Button, Space } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'

const { Header, Content } = Layout

interface PageShellProps {
  title: ReactNode
  onBack: () => void
  rightExtra?: ReactNode
  maxWidth?: number
  children: ReactNode
}

export function PageShell({ title, onBack, rightExtra, maxWidth = 1200, children }: PageShellProps) {
  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>
      <Header style={{ background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border-color)', paddingInline: 16 }}>
        <div style={{ maxWidth, margin: '0 auto', height: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={onBack}>返回学习页</Button>
            <span style={{ fontSize: 16, fontWeight: 600 }}>{title}</span>
          </Space>
          {rightExtra}
        </div>
      </Header>

      <Content style={{ padding: 16 }}>
        <div style={{ maxWidth, margin: '0 auto' }}>
          {children}
        </div>
      </Content>
    </Layout>
  )
}
