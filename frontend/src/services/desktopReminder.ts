import { getDesktopBridge, type PomodoroReminderPayload } from './desktopBridge'

export type { PomodoroReminderPayload }

function normalizeReminder(payload: PomodoroReminderPayload): PomodoroReminderPayload | null {
  const taskName = payload.taskName.trim()
  const dueAt = Number(payload.dueAt)
  if (!taskName || !Number.isFinite(dueAt) || dueAt <= 0) return null
  return {
    taskName,
    dueAt,
    mode: payload.mode === 'break' ? 'break' : 'focus',
  }
}

export function isDesktopReminderAvailable(): boolean {
  const bridge = getDesktopBridge()
  return Boolean(bridge?.setPomodoroReminder && bridge?.clearPomodoroReminder)
}

export async function setPomodoroReminder(payload: PomodoroReminderPayload): Promise<boolean> {
  const bridge = getDesktopBridge()
  const normalized = normalizeReminder(payload)
  if (!bridge?.setPomodoroReminder || !normalized) return false
  await bridge.setPomodoroReminder(normalized)
  return true
}

export async function clearPomodoroReminder(): Promise<boolean> {
  const bridge = getDesktopBridge()
  if (!bridge?.clearPomodoroReminder) return false
  await bridge.clearPomodoroReminder()
  return true
}

export function onReminderTriggered(callback: (payload: PomodoroReminderPayload) => void): (() => void) | null {
  const bridge = getDesktopBridge()
  if (!bridge?.onReminderTriggered) return null
  return bridge.onReminderTriggered(callback)
}
