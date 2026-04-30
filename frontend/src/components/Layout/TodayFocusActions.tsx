import { Button } from 'antd'

interface TodayFocusActionsProps {
  todayTaskCount: number
  pendingCount: number
  dueReviewCount: number
  studyMinutes: number
  focusMinutes: number
  onOpenGoals: () => void
  onOpenReview: () => void
  onStartFocus: () => void
  onOpenFeynman: () => void
  onOpenEDA: () => void
  onOpenIntervention: () => void
}

export function TodayFocusActions(props: TodayFocusActionsProps) {
  const {
    todayTaskCount, pendingCount, dueReviewCount, studyMinutes,
    focusMinutes, onOpenGoals, onOpenReview, onStartFocus,
    onOpenFeynman, onOpenEDA, onOpenIntervention,
  } = props

  return (
    <div style={{
      marginBottom: 12,
      borderRadius: 'var(--radius-lg)',
      background: 'var(--bg-secondary)',
      padding: '24px',
      boxShadow: 'var(--shadow-sm)',
    }}>
      {/* 主行动按钮 */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
        <Button
          type="primary"
          size="small"
          onClick={onOpenGoals}
          style={{ borderRadius: 'var(--radius-sm)', fontSize: 12 }}
        >
          📋 定今天任务
        </Button>
        {dueReviewCount > 0 && (
          <Button
            size="small"
            onClick={onOpenReview}
            style={{ borderRadius: 'var(--radius-sm)', fontSize: 12, borderColor: 'var(--error)', color: 'var(--error)' }}
          >
            🔄 处理复习 {dueReviewCount}
          </Button>
        )}
        <Button
          size="small"
          onClick={onStartFocus}
          style={{ borderRadius: 'var(--radius-sm)', fontSize: 12, color: 'var(--text-secondary)' }}
        >
          🍅 专注{focusMinutes}分钟
        </Button>
        <Button size="small" onClick={onOpenFeynman} style={{ borderRadius: 'var(--radius-sm)', fontSize: 12, color: 'var(--text-secondary)' }}>
          💡 费曼复盘
        </Button>
        <Button size="small" onClick={onOpenEDA} style={{ borderRadius: 'var(--radius-sm)', fontSize: 12, color: 'var(--text-secondary)' }}>
          📊 EDA报告
        </Button>
        <Button size="small" onClick={onOpenIntervention} style={{ borderRadius: 'var(--radius-sm)', fontSize: 12, color: 'var(--text-secondary)' }}>
          🔔 AI干预
        </Button>
      </div>

      {/* 次级统计 — 小字辅助信息 */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {[
          { label: '今日任务', value: todayTaskCount, color: 'var(--text-secondary)' },
          { label: '待完成', value: pendingCount, color: pendingCount > 0 ? 'var(--warning)' : 'var(--text-tertiary)' },
          { label: '学习分钟', value: studyMinutes, color: 'var(--text-tertiary)' },
        ].map(s => (
          <span key={s.label} style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
            {s.label}
            <span style={{ fontWeight: 600, color: s.color, marginLeft: 4 }}>{s.value}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

