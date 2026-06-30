import { getDesktopBridge, type CoachNotificationPayload, type CoachNotificationRoutePayload } from './desktopBridge'

export type { CoachNotificationPayload }

function trimText(value: unknown, maxLength: number): string {
  return String(value || '').trim().slice(0, maxLength)
}

export function normalizeCoachNotificationPayload(payload: CoachNotificationPayload): CoachNotificationPayload | null {
  const id = trimText(payload.id, 80)
  const title = trimText(payload.title, 80)
  const body = trimText(payload.body, 240)
  const route = payload.route ? trimText(payload.route, 200) : null
  if (!id || !title || !body) return null
  return { id, title, body, route }
}

export function isDesktopCoachNotificationAvailable(): boolean {
  const bridge = getDesktopBridge()
  return Boolean(bridge?.showCoachNotification)
}

export async function showDesktopCoachNotification(payload: CoachNotificationPayload): Promise<boolean> {
  const bridge = getDesktopBridge()
  const normalized = normalizeCoachNotificationPayload(payload)
  if (!bridge?.showCoachNotification || !normalized) return false
  await bridge.showCoachNotification(normalized)
  return true
}

export function onCoachNotificationRoute(callback: (payload: CoachNotificationRoutePayload) => void): (() => void) | null {
  const bridge = getDesktopBridge()
  if (!bridge?.onCoachNotificationRoute) return null
  return bridge.onCoachNotificationRoute(callback)
}
