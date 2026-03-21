import { Button, Col, Row, Statistic } from 'antd'

interface TodayFocusActionsProps {
  todayTaskCount: number
  pendingCount: number
  dueReviewCount: number
  studyMinutes: number
  onOpenGoals: () => void
  onOpenReview: () => void
  onStartFocus: () => void
  onOpenFeynman: () => void
}

export function TodayFocusActions(props: TodayFocusActionsProps) {
  const {
    todayTaskCount,
    pendingCount,
    dueReviewCount,
    studyMinutes,
    onOpenGoals,
    onOpenReview,
    onStartFocus,
    onOpenFeynman,
  } = props

  return (
    <div
      style={{
        marginBottom: 12,
        border: '1px solid var(--border-color)',
        borderRadius: 'var(--radius-lg)',
        background: 'var(--bg-secondary)',
        padding: '14px 16px',
        boxShadow: 'var(--shadow-xs)',
      }}
    >
      {/* Stats row - compact */}
      <Row gutter={[12, 8]} style={{ marginBottom: 12 }}>
        <Col xs={12} md={6}>
          <Statistic
            title={<span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>今日任务</span>}
            value={todayTaskCount}
            valueStyle={{ fontSize: 20, fontWeight: 600, color: 'var(--text-primary)' }}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title={<span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>待完成</span>}
            value={pendingCount}
            valueStyle={{ fontSize: 20, fontWeight: 600, color: pendingCount > 0 ? 'var(--warning)' : 'var(--text-primary)' }}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title={<span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>到期复习</span>}
            value={dueReviewCount}
            valueStyle={{ fontSize: 20, fontWeight: 600, color: dueReviewCount > 0 ? 'var(--error)' : 'var(--text-primary)' }}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title={<span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>学习分钟</span>}
            value={studyMinutes}
            valueStyle={{ fontSize: 20, fontWeight: 600, color: 'var(--accent-600)' }}
          />
        </Col>
      </Row>

      {/* Action buttons - horizontal row */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Button
          type="primary"
          size="small"
          onClick={onOpenGoals}
          style={{ borderRadius: 'var(--radius-sm)', fontSize: 12 }}
        >
          📋 定今天任务
        </Button>
        <Button
          size="small"
          onClick={onOpenReview}
          style={{ borderRadius: 'var(--radius-sm)', fontSize: 12, color: 'var(--text-secondary)' }}
        >
          🔄 处理复习
        </Button>
        <Button
          size="small"
          onClick={onStartFocus}
          style={{ borderRadius: 'var(--radius-sm)', fontSize: 12, color: 'var(--text-secondary)' }}
        >
          🍅 专注25分钟
        </Button>
        <Button
          size="small"
          onClick={onOpenFeynman}
          style={{ borderRadius: 'var(--radius-sm)', fontSize: 12, color: 'var(--text-secondary)' }}
        >
          💡 费曼复盘
        </Button>
      </div>
    </div>
  )
}
