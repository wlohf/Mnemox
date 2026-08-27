import { Button, Card, Col, Row, Space, Typography } from 'antd'
import type { NorthStarMetricsReport } from '../../services/analyticsApi'

const { Text } = Typography

interface NorthStarMetricsCardProps {
  report: NorthStarMetricsReport | null
  onRefresh: () => void
}

export function NorthStarMetricsCard({ report, onRefresh }: NorthStarMetricsCardProps) {
  return (
    <Card size="small" title="学习行为反馈" extra={<Button size="small" onClick={onRefresh}>刷新数据</Button>}>
      {report ? (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Row gutter={[12, 12]}>
            <Col xs={12} md={6}>
              <Text type="secondary">建议执行</Text>
              <div><Text strong>{report.metrics.suggestion_execution_rate.value ?? '样本不足'}{report.metrics.suggestion_execution_rate.value !== null && report.metrics.suggestion_execution_rate.value !== undefined ? '%' : ''}</Text></div>
              <Text type="secondary">真实行为 {report.metrics.suggestion_execution_rate.completed_by_domain_event_count ?? 0} · 手动确认 {report.metrics.suggestion_execution_rate.completed_by_user_confirmation_count ?? 0}</Text>
            </Col>
            <Col xs={12} md={6}>
              <Text type="secondary">中断后恢复</Text>
              <div><Text strong>{report.metrics.interruption_recovery_time.value ?? '样本不足'}{report.metrics.interruption_recovery_time.value !== null && report.metrics.interruption_recovery_time.value !== undefined ? ' 分钟' : ''}</Text></div>
              <Text type="secondary">尚未恢复 {report.metrics.interruption_recovery_time.unrecovered_count ?? 0} 次</Text>
            </Col>
            <Col xs={12} md={6}>
              <Text type="secondary">复习按时率</Text>
              <div><Text strong>{report.metrics.review_on_time_rate.value ?? '样本不足'}{report.metrics.review_on_time_rate.value !== null && report.metrics.review_on_time_rate.value !== undefined ? '%' : ''}</Text></div>
              <Text type="secondary">已成熟机会 {report.metrics.review_on_time_rate.denominator ?? 0} 次</Text>
            </Col>
            <Col xs={12} md={6}>
              <Text type="secondary">本周有效学习</Text>
              <div><Text strong>{report.metrics.weekly_effective_study_sessions.value ?? 0} 次</Text></div>
              <Text type="secondary">至少 15 分钟才计入</Text>
            </Col>
          </Row>
          <Text type="secondary">只统计已经过观察期的原始学习事件；它用于看趋势，不会把相关性当作 Coach 的因果效果。</Text>
        </Space>
      ) : (
        <Text type="secondary">暂无足够的已记录学习事件。完成几次学习、复习或 Coach 行动后，这里会逐步出现趋势。</Text>
      )}
    </Card>
  )
}
