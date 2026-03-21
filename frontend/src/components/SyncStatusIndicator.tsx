import { Tooltip } from 'antd'
import {
  CloudOutlined,
  SyncOutlined,
  DisconnectOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useSyncStatus } from '../sync/useSyncStatus'
import { syncEngine } from '../sync/SyncEngine'

export function SyncStatusIndicator() {
  const { status, online } = useSyncStatus()

  const handleClick = () => {
    void syncEngine.syncAll()
  }

  let icon: React.ReactNode
  let color: string
  let tip: string

  switch (status) {
    case 'idle':
      icon = <CloudOutlined />
      color = '#7cb342'
      tip = '已同步'
      break
    case 'syncing':
      icon = <SyncOutlined spin />
      color = '#1890ff'
      tip = '同步中...'
      break
    case 'offline':
      icon = <DisconnectOutlined />
      color = '#999'
      tip = '离线模式'
      break
    case 'error':
      icon = <WarningOutlined />
      color = '#d4644a'
      tip = '同步出错，点击重试'
      break
  }

  if (!online && status !== 'offline') {
    icon = <DisconnectOutlined />
    color = '#999'
    tip = '离线模式'
  }

  return (
    <Tooltip title={tip}>
      <span
        onClick={handleClick}
        style={{
          cursor: 'pointer',
          color,
          fontSize: 16,
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
        }}
      >
        {icon}
        <span style={{ fontSize: 11 }}>{tip}</span>
      </span>
    </Tooltip>
  )
}
