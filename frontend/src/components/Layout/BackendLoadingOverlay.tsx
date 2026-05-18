import { Spin } from 'antd'

export function BackendLoadingOverlay() {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100vh',
      background: 'var(--bg-primary)',
      gap: 16,
    }}>
      <Spin size="large" />
      <div style={{ color: 'var(--text-secondary)', fontSize: 16 }}>正在等待后端服务启动...</div>
      <div style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>后端服务就绪后将自动加载数据</div>
    </div>
  )
}
