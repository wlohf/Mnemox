import { Alert, Card, Space, Switch, Tag, Typography } from 'antd'
import type { AgentProactiveRuntimeStatus } from '../../services/agentApi'

const { Text } = Typography

function formatDateTime(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(date)
}

interface ProactiveReviewChecksCardProps {
  status: AgentProactiveRuntimeStatus | null
  saving: boolean
  onChange: (enabled: boolean) => void
}

/**
 * Keeps the deployment-wide scheduler state and the learner's opt-in choice
 * together, so a local-only session cannot be mistaken for a running worker.
 */
export function ProactiveReviewChecksCard({
  status,
  saving,
  onChange,
}: ProactiveReviewChecksCardProps) {
  return (
    <Card
      size="small"
      title="主动复习检查"
      extra={(
        <Switch
          checked={Boolean(status?.preference.proactive_enabled)}
          loading={saving}
          disabled={!status}
          onChange={onChange}
          checkedChildren="已开启"
          unCheckedChildren="已关闭"
          aria-label="开启或关闭后台复习检查"
        />
      )}
    >
      {status ? (
        <Space direction="vertical" size={6} style={{ width: '100%' }} aria-live="polite">
          <Space wrap>
            <Tag color={status.preference.proactive_enabled ? 'green' : 'default'}>
              {status.preference.proactive_enabled ? '已同意检查' : '未开启'}
            </Tag>
            <Tag color={status.scheduler.running ? 'processing' : 'default'}>
              {status.scheduler.available
                ? status.scheduler.running ? '后台检查器运行中' : '后台检查器未运行'
                : '当前模式仅页面内评估'}
            </Tag>
            {status.scheduler.last_success_at && <Text type="secondary">最近检查：{formatDateTime(status.scheduler.last_success_at)}</Text>}
          </Space>
          <Text type="secondary">{status.scheduler.message}</Text>
          {status.scheduler.last_error_at && (
            <Alert
              type="warning"
              showIcon
              message="上一次后台检查未完成"
              description="系统会在下一次低频周期重试；没有修改你的计划、任务或复习数据。"
            />
          )}
        </Space>
      ) : (
        <Text type="secondary">正在读取主动检查状态…</Text>
      )}
    </Card>
  )
}
