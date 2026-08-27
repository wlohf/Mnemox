import { Tooltip } from 'antd'
import {
  CloudOutlined,
  SyncOutlined,
  DisconnectOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useSyncStatus } from '../sync/useSyncStatus'
import { syncEngine } from '../sync/SyncEngine'

interface SyncStatusIndicatorProps {
  onResolveConflicts?: () => void
}

export function SyncStatusIndicator({ onResolveConflicts }: SyncStatusIndicatorProps) {
  const { status, online, failedCount, conflictCount, lastError } = useSyncStatus()

  const handleClick = () => {
    if (conflictCount > 0) {
      onResolveConflicts?.()
      return
    }
    void (status === 'error' ? syncEngine.retryFailed() : syncEngine.syncAll())
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
      tip = lastError || '同步出错，点击重试'
      break
  }

  if (!online && status !== 'offline') {
    icon = <DisconnectOutlined />
    color = '#999'
    tip = '离线模式'
  }

  if (conflictCount > 0) {
    icon = <WarningOutlined />
    color = '#a87332'
    tip = `${conflictCount} 条同步冲突待你决定`
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
        <span style={{ fontSize: 11 }}>
          {conflictCount > 0 ? `待处理 ${conflictCount}` : failedCount > 0 ? `同步失败 ${failedCount}` : tip}
        </span>
      </span>
    </Tooltip>
  )
}
