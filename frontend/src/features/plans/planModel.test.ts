import { describe, expect, it } from 'vitest'
import { appendTasks, checklistOf, dayTitle, isPlainDay, monthGrid, monthRange, previewOf, shiftMonth, statsOf, toggleLine } from './planModel'

const PLAN = ['# 9月25日', '', '- [ ] 阅读第一章', '- [x] 复习错题', '* [X] 专注 25 分钟', '普通文字', '  - [ ] 缩进的任务'].join('\n')

describe('checklist', () => {
  it('parses every checklist style with its line number', () => {
    expect(checklistOf(PLAN)).toEqual([
      { line: 2, title: '阅读第一章', done: false },
      { line: 3, title: '复习错题', done: true },
      { line: 4, title: '专注 25 分钟', done: true },
      { line: 6, title: '缩进的任务', done: false },
    ])
  })
  it('computes stats', () => {
    expect(statsOf(PLAN)).toEqual({ total: 4, done: 2, ratio: 0.5 })
    expect(statsOf('')).toEqual({ total: 0, done: 0, ratio: 0 })
  })
  it('toggles one line and leaves others untouched', () => {
    const next = toggleLine(PLAN, 2)
    expect(next.split('\n')[2]).toBe('- [x] 阅读第一章')
    expect(toggleLine(next, 2)).toBe(PLAN)
    expect(toggleLine(PLAN, 5)).toBe(PLAN)
  })
  it('appends tasks after existing content', () => {
    expect(appendTasks('# 标题', ['A', ' ', 'B'])).toBe('# 标题\n\n- [ ] A\n- [ ] B\n')
    expect(appendTasks('', ['A'])).toBe('- [ ] A\n')
    expect(appendTasks('x', [])).toBe('x')
  })
  it('previews the first meaningful line', () => {
    expect(previewOf(PLAN)).toBe('阅读第一章')
    expect(previewOf('# 只有标题')).toBe('')
    expect(previewOf('## 早上\n> **先**复习')).toBe('先复习')
  })
})

describe('calendar', () => {
  it('builds a Monday-first six-week grid', () => {
    const grid = monthGrid('2026-09', '2026-09-25')
    expect(grid).toHaveLength(42)
    expect(grid[0].day).toBe('2026-08-31')
    expect(grid.find(c => c.isToday)?.day).toBe('2026-09-25')
    expect(grid.filter(c => c.inMonth)).toHaveLength(30)
  })
  it('shifts months across years', () => {
    expect(shiftMonth('2026-12', 1)).toBe('2027-01')
    expect(shiftMonth('2026-01', -1)).toBe('2025-12')
  })
  it('covers the whole visible grid', () => {
    expect(monthRange('2026-09')).toEqual({ start: '2026-08-31', end: '2026-10-11' })
  })
  it('names days relative to today', () => {
    expect(dayTitle('2026-09-25', '2026-09-25')).toEqual({ primary: '今天', secondary: '9月25日 周五' })
    expect(dayTitle('2026-09-26', '2026-09-25').primary).toBe('明天')
    expect(dayTitle('2026-10-02', '2026-09-25')).toEqual({ primary: '10月2日', secondary: '2026年 · 周五' })
  })
  it('validates plain days', () => {
    expect(isPlainDay('2026-02-28')).toBe(true)
    expect(isPlainDay('2026-02-30')).toBe(false)
    expect(isPlainDay('9/25')).toBe(false)
    expect(isPlainDay(null)).toBe(false)
  })
})
