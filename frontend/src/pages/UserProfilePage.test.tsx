import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { UserProfile } from '../services/profileApi'
import { UserProfilePage } from './UserProfilePage'

const api = vi.hoisted(() => ({ getProfile: vi.fn(), refreshProfile: vi.fn() }))
vi.mock('../services/profileApi', () => api)
vi.mock('echarts-for-react', () => ({
  default: ({ option }: { option: object }) => <pre data-chart>{JSON.stringify(option)}</pre>,
}))
vi.mock('../components/PageShell', () => ({
  PageShell: ({ children, rightExtra }: { children: ReactNode; rightExtra: ReactNode }) => <div>{rightExtra}{children}</div>,
}))
vi.mock('antd', () => {
  const Box = ({ children, title }: { children?: ReactNode; title?: ReactNode }) => <div>{title}{children}</div>
  const List = ({ dataSource, renderItem }: { dataSource: string[]; renderItem: (s: string, i: number) => ReactNode }) => <div>{dataSource.map(renderItem)}</div>
  List.Item = Box
  return {
    Card: Box, Row: Box, Col: Box, Tag: Box, Space: Box, Spin: Box,
    Typography: { Text: Box }, List,
    Empty: ({ description }: { description: string }) => <div>{description}</div>,
    Alert: ({ message, description }: { message: string; description?: string }) => <div>{message}{description}</div>,
    Statistic: ({ title, value, suffix }: { title: string; value: string | number; suffix: string }) => <div data-stat>{title}：{value}{suffix}</div>,
    Button: ({ onClick, children }: { onClick: () => void; children: ReactNode }) => <button onClick={onClick}>{children}</button>,
  }
})

function fixture(): UserProfile {
  const metrics = {
    finished_count: 4, completed_count: 2, completion_rate: 0.5,
    actual_minutes: 30, actual_duration_count: 2, unknown_actual_duration_count: 2,
    median_actual_minutes: 15, hour_counts: { '9': 3, '10': 1 },
  }
  return {
    user_id: 1, total_study_hours: 100, total_study_days: 2, total_pomodoros: 2,
    avg_session_duration: 15, avg_pomodoro_per_day: 1,
    optimal_hours: '09:00-10:00', preferred_time_slots: { morning: 1 },
    focus_score: 80, self_control_score: 70, consistency_score: 50, planning_score: 50,
    streak_days: 2, weak_points: [], recent_performance: {}, last_updated: null,
    data_insufficient: true, insights: [], lifetime_metrics: metrics,
    evidence_summary: {
      assessment: 'descriptive_only', time_zone: 'Asia/Shanghai', time_zone_source: 'coach_preference',
      metrics, quality_counts: {}, limitations: [],
      coverage: { included_record_count: 4, excluded_record_count: 0, observed_days: 2, unlinked_task_count: 1, truncated: false },
    },
  }
}

describe('profile evidence display', () => {
  let root: ReturnType<typeof createRoot> | undefined
  let container: HTMLDivElement | undefined
  afterEach(() => {
    act(() => root?.unmount())
    container?.remove()
    vi.clearAllMocks()
  })
  async function render(profile: UserProfile) {
    api.getProfile.mockResolvedValue(profile)
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    await act(async () => { root!.render(<MemoryRouter><UserProfilePage /></MemoryRouter>) })
    return container
  }

  it('uses measured percentages and hourly counts instead of legacy trait scores and slot proportions', async () => {
    const page = await render(fixture())
    const charts = [...page.querySelectorAll('[data-chart]')].map(node => JSON.parse(node.textContent!))
    expect(charts[0].series[0].data[0].value).toEqual([50, 50, 75])
    expect(charts[1].series[0].data).toHaveLength(24)
    expect(charts[1].series[0].data[9]).toEqual([9, 0, 3])
    expect(page.textContent).toContain('已记录实际时长：0.5小时')
    expect(page.textContent).toContain('实际时长缺失 2 条')
    expect(page.textContent).not.toContain('专注度')
    expect(page.textContent).not.toContain('8000')
    expect(page.textContent).toContain('结束记录最多的时段')
  })

  it('shows unknown duration without displaying old totals or inferring traits from an empty sample', async () => {
    const profile = fixture()
    profile.evidence_summary = null
    profile.lifetime_metrics = null
    const page = await render(profile)
    expect(page.textContent).toContain('已记录实际时长：—小时')
    expect(page.querySelectorAll('[data-chart]')).toHaveLength(0)
    expect(page.textContent).not.toContain('100小时')
    expect(page.textContent).not.toContain('至少 7 天')
    expect(page.textContent).not.toContain('最佳学习')
  })
})
