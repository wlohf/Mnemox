import { getDesktopPreference, setDesktopPreference } from '../../services/desktopPreferences'

export const DEFAULT_RIGHT_CARD_ORDER = ['current', 'review', 'progress', 'pomodoro', 'calendar', 'motivation']
export const RIGHT_SIDEBAR_CARDS = [
  { id: 'motivation', label: '每日格言' },
  { id: 'calendar', label: '今天与计划' },
  { id: 'current', label: '近期任务' },
  { id: 'review', label: '复习与错题' },
  { id: 'progress', label: '学习数据' },
  { id: 'pomodoro', label: '番茄工作法' },
]
export const RIGHT_SIDEBAR_LAYOUT_PREFERENCE_KEY = 'layout.rightSidebar'

const RIGHT_CARD_ID_SET = new Set(RIGHT_SIDEBAR_CARDS.map(card => card.id))
const DEFAULT_RIGHT_SIDEBAR_WIDTH = 320

const RIGHT_SIDEBAR_LOCAL_STORAGE_KEYS = {
  cardOrder: 'right_card_order',
  visibleCards: 'right_visible_cards',
  collapsed: 'layout_right_collapsed',
  width: 'layout_right_width',
  calendarExpanded: 'layout_right_calendar_expanded',
}

export interface RightSidebarLayoutPreference {
  cardOrder: string[]
  visibleCards: string[]
  collapsed: boolean
  width: number
  calendarExpanded: boolean
}

const DEFAULT_RIGHT_SIDEBAR_LAYOUT: RightSidebarLayoutPreference = {
  cardOrder: DEFAULT_RIGHT_CARD_ORDER,
  visibleCards: DEFAULT_RIGHT_CARD_ORDER,
  collapsed: false,
  width: DEFAULT_RIGHT_SIDEBAR_WIDTH,
  calendarExpanded: false,
}

function cloneRightSidebarLayout(layout: RightSidebarLayoutPreference): RightSidebarLayoutPreference {
  return {
    ...layout,
    cardOrder: [...layout.cardOrder],
    visibleCards: [...layout.visibleCards],
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function normalizeRightCardOrder(ids: unknown): string[] {
  if (!Array.isArray(ids)) return [...DEFAULT_RIGHT_CARD_ORDER]
  const knownIds = ids.filter((id, index) => typeof id === 'string' && RIGHT_CARD_ID_SET.has(id) && ids.indexOf(id) === index)
  const missingIds = DEFAULT_RIGHT_CARD_ORDER.filter(id => !knownIds.includes(id))
  return [...knownIds, ...missingIds]
}

export function normalizeRightVisibleCards(ids: unknown): string[] {
  if (!Array.isArray(ids)) return [...DEFAULT_RIGHT_CARD_ORDER]
  return ids.filter((id, index) => typeof id === 'string' && RIGHT_CARD_ID_SET.has(id) && ids.indexOf(id) === index)
}

export function clampRightSidebarWidth(value: unknown): number {
  const width = Number(value)
  if (!Number.isFinite(width)) return DEFAULT_RIGHT_SIDEBAR_WIDTH
  return Math.min(480, Math.max(200, width))
}

function readJsonLocalStorage(key: string): unknown {
  try {
    const saved = localStorage.getItem(key)
    return saved ? JSON.parse(saved) : null
  } catch {
    return null
  }
}

function readBooleanLocalStorage(key: string, fallback: boolean): boolean {
  try {
    const saved = localStorage.getItem(key)
    return saved === null ? fallback : saved === 'true'
  } catch {
    return fallback
  }
}

export function normalizeRightSidebarLayoutPreference(
  value: unknown,
  fallback: RightSidebarLayoutPreference = DEFAULT_RIGHT_SIDEBAR_LAYOUT,
): RightSidebarLayoutPreference {
  const raw = isRecord(value) ? value : {}
  return {
    cardOrder: normalizeRightCardOrder(raw.cardOrder ?? fallback.cardOrder),
    visibleCards: normalizeRightVisibleCards(raw.visibleCards ?? fallback.visibleCards),
    collapsed: typeof raw.collapsed === 'boolean' ? raw.collapsed : fallback.collapsed,
    width: raw.width === undefined ? fallback.width : clampRightSidebarWidth(raw.width),
    calendarExpanded: typeof raw.calendarExpanded === 'boolean' ? raw.calendarExpanded : fallback.calendarExpanded,
  }
}

export function readLocalRightSidebarLayoutPreference(): RightSidebarLayoutPreference {
  return normalizeRightSidebarLayoutPreference({
    cardOrder: readJsonLocalStorage(RIGHT_SIDEBAR_LOCAL_STORAGE_KEYS.cardOrder),
    visibleCards: readJsonLocalStorage(RIGHT_SIDEBAR_LOCAL_STORAGE_KEYS.visibleCards),
    collapsed: readBooleanLocalStorage(RIGHT_SIDEBAR_LOCAL_STORAGE_KEYS.collapsed, DEFAULT_RIGHT_SIDEBAR_LAYOUT.collapsed),
    width: localStorage.getItem(RIGHT_SIDEBAR_LOCAL_STORAGE_KEYS.width),
    calendarExpanded: readBooleanLocalStorage(
      RIGHT_SIDEBAR_LOCAL_STORAGE_KEYS.calendarExpanded,
      DEFAULT_RIGHT_SIDEBAR_LAYOUT.calendarExpanded,
    ),
  })
}

export function writeLocalRightSidebarLayoutPreference(layout: RightSidebarLayoutPreference): void {
  const normalized = normalizeRightSidebarLayoutPreference(layout)
  try {
    localStorage.setItem(RIGHT_SIDEBAR_LOCAL_STORAGE_KEYS.cardOrder, JSON.stringify(normalized.cardOrder))
    localStorage.setItem(RIGHT_SIDEBAR_LOCAL_STORAGE_KEYS.visibleCards, JSON.stringify(normalized.visibleCards))
    localStorage.setItem(RIGHT_SIDEBAR_LOCAL_STORAGE_KEYS.collapsed, String(normalized.collapsed))
    localStorage.setItem(RIGHT_SIDEBAR_LOCAL_STORAGE_KEYS.width, String(normalized.width))
    localStorage.setItem(RIGHT_SIDEBAR_LOCAL_STORAGE_KEYS.calendarExpanded, String(normalized.calendarExpanded))
  } catch {
    // Browser storage can be unavailable in hardened environments.
  }
}

export async function loadRightSidebarLayoutPreference(): Promise<RightSidebarLayoutPreference> {
  const localPreference = readLocalRightSidebarLayoutPreference()
  const desktopPreference = await getDesktopPreference<Partial<RightSidebarLayoutPreference>>(RIGHT_SIDEBAR_LAYOUT_PREFERENCE_KEY)
  const normalized = normalizeRightSidebarLayoutPreference(desktopPreference, localPreference)
  writeLocalRightSidebarLayoutPreference(normalized)

  if (!desktopPreference) {
    void setDesktopPreference<RightSidebarLayoutPreference>(RIGHT_SIDEBAR_LAYOUT_PREFERENCE_KEY, normalized)
  }

  return cloneRightSidebarLayout(normalized)
}

export async function saveRightSidebarLayoutPreference(layout: RightSidebarLayoutPreference): Promise<void> {
  const normalized = normalizeRightSidebarLayoutPreference(layout)
  writeLocalRightSidebarLayoutPreference(normalized)
  await setDesktopPreference<RightSidebarLayoutPreference>(RIGHT_SIDEBAR_LAYOUT_PREFERENCE_KEY, normalized)
}
