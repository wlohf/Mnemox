import { beforeEach, describe, expect, it, vi } from 'vitest'

const desktopPreferencesMock = vi.hoisted(() => ({
  getDesktopPreference: vi.fn(),
  setDesktopPreference: vi.fn(),
}))

vi.mock('../../services/desktopPreferences', () => desktopPreferencesMock)

import {
  loadRightSidebarLayoutPreference,
  RIGHT_SIDEBAR_LAYOUT_PREFERENCE_KEY,
  saveRightSidebarLayoutPreference,
} from './rightSidebarLayout'

describe('right sidebar layout persistence', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    desktopPreferencesMock.getDesktopPreference.mockResolvedValue(null)
    desktopPreferencesMock.setDesktopPreference.mockResolvedValue(true)
  })

  it('prefers desktop preferences over current-origin local storage', async () => {
    localStorage.setItem('right_card_order', JSON.stringify(['motivation']))
    localStorage.setItem('right_visible_cards', JSON.stringify(['motivation']))
    localStorage.setItem('layout_right_collapsed', 'false')
    localStorage.setItem('layout_right_width', '240')
    localStorage.setItem('layout_right_calendar_expanded', 'false')

    desktopPreferencesMock.getDesktopPreference.mockResolvedValueOnce({
      cardOrder: ['review', 'current'],
      visibleCards: ['review'],
      collapsed: true,
      width: 420,
      calendarExpanded: true,
    })

    const layout = await loadRightSidebarLayoutPreference()

    expect(layout).toEqual({
      cardOrder: ['review', 'current', 'progress', 'pomodoro', 'calendar', 'motivation'],
      visibleCards: ['review'],
      collapsed: true,
      width: 420,
      calendarExpanded: true,
    })
    expect(localStorage.getItem('right_card_order')).toBe(JSON.stringify(layout.cardOrder))
    expect(localStorage.getItem('right_visible_cards')).toBe(JSON.stringify(layout.visibleCards))
    expect(localStorage.getItem('layout_right_collapsed')).toBe('true')
    expect(localStorage.getItem('layout_right_width')).toBe('420')
    expect(localStorage.getItem('layout_right_calendar_expanded')).toBe('true')
    expect(desktopPreferencesMock.setDesktopPreference).not.toHaveBeenCalled()
  })

  it('seeds desktop preferences from local fallback when no desktop value exists', async () => {
    localStorage.setItem('right_card_order', JSON.stringify(['pomodoro', 'current']))
    localStorage.setItem('right_visible_cards', JSON.stringify(['pomodoro', 'unknown']))
    localStorage.setItem('layout_right_collapsed', 'true')
    localStorage.setItem('layout_right_width', '180')
    localStorage.setItem('layout_right_calendar_expanded', 'true')

    const layout = await loadRightSidebarLayoutPreference()

    expect(layout).toEqual({
      cardOrder: ['pomodoro', 'current', 'review', 'progress', 'calendar', 'motivation'],
      visibleCards: ['pomodoro'],
      collapsed: true,
      width: 200,
      calendarExpanded: true,
    })
    expect(desktopPreferencesMock.setDesktopPreference).toHaveBeenCalledWith(
      RIGHT_SIDEBAR_LAYOUT_PREFERENCE_KEY,
      layout,
    )
  })

  it('saves normalized layout to both local storage and desktop preferences', async () => {
    await saveRightSidebarLayoutPreference({
      cardOrder: ['calendar'],
      visibleCards: ['calendar', 'bad'],
      collapsed: false,
      width: 900,
      calendarExpanded: true,
    })

    const normalized = {
      cardOrder: ['calendar', 'current', 'review', 'progress', 'pomodoro', 'motivation'],
      visibleCards: ['calendar'],
      collapsed: false,
      width: 480,
      calendarExpanded: true,
    }
    expect(localStorage.getItem('right_card_order')).toBe(JSON.stringify(normalized.cardOrder))
    expect(localStorage.getItem('right_visible_cards')).toBe(JSON.stringify(normalized.visibleCards))
    expect(localStorage.getItem('layout_right_width')).toBe('480')
    expect(desktopPreferencesMock.setDesktopPreference).toHaveBeenCalledWith(
      RIGHT_SIDEBAR_LAYOUT_PREFERENCE_KEY,
      normalized,
    )
  })
})
