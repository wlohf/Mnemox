import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Spin, Tag, message } from 'antd'
import { getDashboard, type DashboardData } from '../services/learningApi'
import { getApiErrorMessage } from '../services/apiClient'
import { PageShell } from '../components/PageShell'

export function DashboardPage() {
  const navigate = useNavigate()
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<'all' | 'review' | 'task'>('all')

  const load = async () => {
    setLoading(true)
    try {
      const d = await getDashboard()
      setData(d)
    } catch (error) {
      message.error(getApiErrorMessage(error, '加载今日概览失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const mission = data?.today_mission
  const allItems = [
    ...(data?.recommended_actions || []).map(a => ({ ...a, _kind: a.type === 'review' ? 'review' as const : 'task' as const })),
    ...(data?.today_tasks || [])
      .filter(t => t.status !== 'completed')
      .map(t => ({ type: t.task_type || 'task', title: t.title, item_id: t.id, _kind: 'task' as const })),
  ]
  const filtered = filter === 'all' ? allItems : allItems.filter(i => i._kind === filter)

  return (
    <PageShell title="今日概览" onBack={() => navigate('/')} maxWidth={860}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div style={{ fontSize: 14, color: 'var(--text-tertiary)', letterSpacing: '0.02em' }}>
          {new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}
        </div>
      </div>

      <Spin spinning={loading}>
        {mission && (
          <div style={{
            background: 'var(--bg-surface)',
            borderRadius: 'var(--radius-lg)',
            padding: '24px 28px',
            marginBottom: 24,
            boxShadow: 'var(--shadow-sm)',
            border: '1px solid var(--border-light)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 240 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10, flexWrap: 'wrap' }}>
                  <Tag color="blue" style={{ margin: 0 }}>今日唯一任务</Tag>
                  <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>预计 {mission.estimated_minutes} 分钟</span>
                </div>
                <div style={{ fontSize: 24, lineHeight: 1.25, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>
                  {mission.title}
                </div>
                <div style={{ fontSize: 14, lineHeight: 1.7, color: 'var(--text-secondary)', maxWidth: 620 }}>
                  {mission.reason}
                </div>
              </div>
              <Button type="primary" size="large" onClick={() => navigate(mission.route)} style={{ flexShrink: 0 }}>
                {mission.cta}
              </Button>
            </div>
            <div style={{
              marginTop: 16,
              padding: '12px 14px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border-light)',
              color: 'var(--text-secondary)',
              fontSize: 13,
              lineHeight: 1.6,
            }}>
              <strong style={{ color: 'var(--text-primary)' }}>先主动回忆：</strong>
              {mission.active_recall_prompt}
            </div>
          </div>
        )}

        {/* Stats row */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginBottom: 32 }}>
          {[
            { label: '今日任务', value: data?.today_task_count ?? 0, color: 'var(--text-primary)' },
            { label: '待复习', value: data?.due_review_count ?? 0, color: 'var(--amber-400)' },
            { label: '专注分钟', value: data?.today_study_minutes ?? 0, color: 'var(--brand-400)' },
          ].map(s => (
            <div key={s.label} style={{ 
              background: 'var(--bg-surface)', 
              borderRadius: 'var(--radius-lg)', 
              padding: '24px 32px', 
              boxShadow: 'var(--shadow-sm)', 
              border: '1px solid var(--border-light)'
            }}>
              <div style={{ fontSize: 36, fontWeight: 700, color: s.color, lineHeight: 1, fontFamily: 'Space Grotesk' }}>{s.value}</div>
              <div style={{ fontSize: 13, color: 'var(--text-tertiary)', marginTop: 8, fontWeight: 500 }}>{s.label}</div>
            </div>
          ))}
        </div>

        {/* Filter tabs */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          {(['all', 'review', 'task'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              style={{
                padding: '6px 16px', borderRadius: 999, fontSize: 13, fontWeight: 500, cursor: 'pointer',
                border: filter === f ? 'none' : '1px solid var(--border-light)',
                background: filter === f ? 'rgba(99, 102, 241, 0.15)' : 'transparent',
                color: filter === f ? 'var(--brand-400)' : 'var(--text-secondary)',
                transition: 'all 150ms',
              }}
            >
              {{ all: '全部', review: '复习', task: '任务' }[f]}
            </button>
          ))}
        </div>

        {/* Task list */}
        <div style={{ 
          background: 'var(--bg-surface)', 
          borderRadius: 'var(--radius-lg)', 
          overflow: 'hidden', 
          marginBottom: 32, 
          boxShadow: 'var(--shadow-sm)',
          border: '1px solid var(--border-light)'
        }}>
          {filtered.length === 0 ? (
            <div style={{ padding: '48px 16px', textAlign: 'center', color: 'var(--text-tertiary)', fontSize: 14 }}>
              暂无待办项目，你可以去对话页添加学习任务
            </div>
          ) : filtered.map((item, i) => (
            <div
              key={i}
              onClick={() => navigate(item._kind === 'review' ? '/review' : '/goals')}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '16px 24px',
                borderBottom: i < filtered.length - 1 ? '1px solid var(--border-light)' : 'none',
                cursor: 'pointer',
                transition: 'background 0.2s',
              }}
              onMouseOver={(e) => e.currentTarget.style.background = 'var(--bg-elevated)'}
              onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <div style={{
                  width: 20, height: 20, borderRadius: '50%',
                  border: `2px solid ${item._kind === 'review' ? 'var(--amber-400)' : 'var(--border-color)'}`,
                  flexShrink: 0,
                }} />
                <span style={{ fontSize: 14, color: 'var(--text-primary)', fontWeight: 500 }}>{item.title}</span>
              </div>
              <span style={{
                fontSize: 12, padding: '4px 10px', borderRadius: 6, fontWeight: 600,
                background: item._kind === 'review' ? 'rgba(251, 191, 36, 0.1)' : 'rgba(99, 102, 241, 0.1)',
                color: item._kind === 'review' ? 'var(--amber-400)' : 'var(--brand-400)',
              }}>
                {item._kind === 'review' ? '复习' : '任务'}
              </span>
            </div>
          ))}
        </div>

        {/* Pomodoro CTA */}
        <div style={{
          background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.1), rgba(129, 140, 248, 0.05))', 
          borderRadius: 'var(--radius-lg)',
          padding: '24px 32px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16,
          boxShadow: 'var(--shadow-sm)',
          border: '1px solid rgba(99, 102, 241, 0.2)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{
              width: 56, height: 56, borderRadius: '50%',
              background: 'linear-gradient(135deg, var(--brand-500), var(--brand-400))',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#fff', fontSize: 24, boxShadow: '0 4px 12px rgba(99, 102, 241, 0.4)'
            }}>
              ⏱
            </div>
            <div>
              <div style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-primary)' }}>开启番茄专注</div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>
                今日已完成 {data?.today_pomodoro_count ?? 0} 个番茄钟
              </div>
            </div>
          </div>
          <button
            onClick={() => navigate('/pomodoro')}
            style={{
              padding: '12px 32px', borderRadius: 'var(--radius-md)', fontSize: 14, fontWeight: 600, cursor: 'pointer',
              background: 'linear-gradient(135deg, var(--brand-500), var(--brand-400))', border: 'none',
              color: '#fff', flexShrink: 0,
              boxShadow: '0 4px 16px rgba(99, 102, 241, 0.3)',
              transition: 'transform 0.2s',
            }}
            onMouseOver={(e) => e.currentTarget.style.transform = 'translateY(-2px)'}
            onMouseOut={(e) => e.currentTarget.style.transform = 'translateY(0)'}
          >
            开始专注
          </button>
        </div>

      </Spin>
    </PageShell>
  )
}
