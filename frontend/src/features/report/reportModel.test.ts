import { describe, expect, it } from 'vitest'
import type { EDAReport } from '../../services/analyticsApi'
import type { UserProfile } from '../../services/profileApi'
import {
  abilityRows,
  formatMinutes,
  heatGrid,
  heatLevel,
  labelledDays,
  niceTicks,
  outcomesOf,
  reportTarget,
  trendCaption,
  weakPointsOf,
  windowHours,
} from './reportModel'

const profile = (over: Partial<UserProfile> = {}): UserProfile => ({
  user_id: 1,
  total_study_hours: 1.25,
  total_study_days: 3,
  total_pomodoros: 3,
  avg_session_duration: 25,
  avg_pomodoro_per_day: 1,
  optimal_hours: '23:00-01:00',
  preferred_time_slots: null,
  self_control_score: 60,
  consistency_score: 0,
  focus_score: 60,
  planning_score: 50,
  streak_days: 0,
  weak_points: ['费曼复盘'],
  recent_performance: null,
  last_updated: '2026-09-25T14:32:31',
  data_insufficient: true,
  insights: [],
  ...over,
})

describe('abilityRows', () => {
  it('shows only the measured abilities, on the 0–100 scale the backend uses', () => {
    const rows = abilityRows(profile({ focus_score: 60, consistency_score: 23.3, streak_days: 7 }))
    expect(rows.map(r => [r.key, r.value])).toEqual([
      ['focus', 60],
      ['consistency', 23],
    ])
    expect(rows[1].foot).toBe('已连续学习 7 天，满 30 天记满分')
  })
  it('clamps out-of-range and missing scores', () => {
    const rows = abilityRows(profile({ focus_score: 140, consistency_score: Number.NaN }))
    expect(rows.map(r => r.value)).toEqual([100, 0])
  })
})

describe('weakPointsOf', () => {
  it('keeps the backend order, trims and removes duplicates', () => {
    expect(weakPointsOf([' 导数 ', '极限', '导数', '', null, '积分'])).toEqual(['导数', '极限', '积分'])
  })
  it('accepts object rows from older profiles and caps the list', () => {
    const many = Array.from({ length: 14 }, (_, i) => ({ knowledge_point: `点${i}` }))
    expect(weakPointsOf(many)).toHaveLength(10)
    expect(weakPointsOf([{ name: '概率' }, 42])).toEqual(['概率'])
    expect(weakPointsOf(null)).toEqual([])
  })
})

describe('reportTarget', () => {
  it('maps legacy deep links onto sections of the report', () => {
    expect(reportTarget('?tab=intervention', '')).toBe('report-today')
    expect(reportTarget('', '#profile')).toBe('report-profile')
    expect(reportTarget('?days=7', '#today')).toBe('report-today')
    expect(reportTarget('?days=7', '')).toBeNull()
    expect(reportTarget('', '#unknown')).toBeNull()
  })
})

describe('formatMinutes', () => {
  it('uses minutes below an hour and hours above', () => {
    expect(formatMinutes(25.4)).toBe('25 分钟')
    expect(formatMinutes(93.1)).toBe('1.6 小时')
    expect(formatMinutes(120)).toBe('2 小时')
    expect(formatMinutes(725)).toBe('12 小时')
    expect(formatMinutes(null)).toBe('0 分钟')
  })
})

describe('niceTicks', () => {
  it('produces clean ticks that reach the maximum', () => {
    expect(niceTicks(25)).toEqual([0, 10, 20, 30])
    expect(niceTicks(100)).toEqual([0, 25, 50, 75, 100])
    expect(niceTicks(0)).toEqual([0, 0.25, 0.5, 0.75, 1])
  })
})

describe('labelledDays', () => {
  it('labels every day for a week and sparsely otherwise, always the last', () => {
    expect([...labelledDays(7)].sort((a, b) => a - b)).toEqual([0, 1, 2, 3, 4, 5, 6])
    const month = labelledDays(30)
    expect(month.has(29)).toBe(true)
    expect(month.size).toBe(5)
    expect(labelledDays(90).has(89)).toBe(true)
  })
})

describe('outcomesOf', () => {
  it('derives full completions from the rate and keeps real stop reasons', () => {
    const o = outcomesOf({ pomodoro_count: 5, completion_rate: 60, stop_reason_counts: { early_done: 0, interrupted: 1, distracted: 1 } })
    expect(o).toEqual([
      { key: 'completed', label: '完整完成', count: 3 },
      { key: 'interrupted', label: '临时中断', count: 1 },
      { key: 'distracted', label: '走神停下', count: 1 },
    ])
  })
  it('puts unexplained sessions under other and never goes negative', () => {
    const o = outcomesOf({ pomodoro_count: 4, completion_rate: 25, stop_reason_counts: {} })
    expect(o.map(x => [x.key, x.count])).toEqual([
      ['completed', 1],
      ['other', 3],
    ])
    expect(outcomesOf({ pomodoro_count: 0, completion_rate: 0 })).toEqual([])
  })
})

describe('time of day', () => {
  it('parses study windows, including ones that wrap midnight', () => {
    expect([...windowHours('20:00-21:00')]).toEqual([20])
    expect([...windowHours('23:00-01:00')]).toEqual([23, 0])
    expect(windowHours('whenever').size).toBe(0)
  })
  it('buckets heat into five steps with zero reserved', () => {
    expect([0, 1, 10, 25].map(v => heatLevel(v, 25))).toEqual([0, 1, 2, 5])
    expect(heatLevel(5, 0)).toBe(0)
  })
  it('builds the weekday × hour grid with totals', () => {
    const g = heatGrid({
      charts: { hour_week_heatmap: { hours: [], weekdays: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'], points: [[23, 0, 25], [21, 2, 18], [23, 0, 5]] } },
    } as unknown as EDAReport)
    expect(g.cells[0][23]).toBe(30)
    expect(g.hourTotals[23]).toBe(30)
    expect(g.dayTotals[2]).toBe(18)
    expect(g.max).toBe(30)
  })
})

describe('trendCaption', () => {
  it('summarises the period from the data itself', () => {
    const r = {
      period_days: 7,
      summary: { total_minutes: 50 },
      daily_points: [
        { date: '2026-09-24', study_minutes: 25 },
        { date: '2026-09-25', study_minutes: 25 },
        { date: '2026-09-23', study_minutes: 0 },
      ],
    } as unknown as EDAReport
    expect(trendCaption(r)).toBe('近 7 天共学习 50 分钟，其中 2 天有记录；最长的一天是 9/24，25 分钟。')
    expect(trendCaption({ ...r, daily_points: [] })).toBe('近 7 天还没有学习记录。')
  })
})
