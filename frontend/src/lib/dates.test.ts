import { describe, expect, it } from 'vitest'
import { dayDiff, deadlineLabel, dueLabel, formatStamp, minutesSince, parseServerTime, shortDate, toLocalDay } from './dates'

describe('date helpers', () => {
  it('keeps date-only values stable and rejects invalid dates', () => {
    expect(toLocalDay('2026-09-25')).toBe('2026-09-25')
    expect(toLocalDay('2026-02-30')).toBeNull()
    expect(dayDiff('2026-10-02', '2026-09-25')).toBe(7)
    expect(shortDate('2026-09-25')).toBe('9月25日')
  })

  it('treats timezone-less server timestamps as UTC', () => {
    expect(parseServerTime('2026-09-25T10:30:00')?.toISOString()).toBe('2026-09-25T10:30:00.000Z')
    expect(formatStamp(new Date(2026, 8, 25, 10, 30))).toBe('9月25日 10:30')
    expect(minutesSince('2026-09-25T10:00:00Z', Date.parse('2026-09-25T10:42:00Z'))).toBe(42)
  })

  it('describes task and deadline dates', () => {
    expect(dueLabel('2026-09-23', '2026-09-25')).toEqual({ text: '逾期 2 天', tone: 'overdue' })
    expect(dueLabel('2026-09-26', '2026-09-25')).toEqual({ text: '明天', tone: 'soon' })
    expect(dueLabel('2026-09-23', '2026-09-25', true)).toEqual({ text: '9月23日' })
    expect(deadlineLabel('2026-10-02', '2026-09-25')).toEqual({ text: '还剩 7 天', tone: undefined })
  })
})
