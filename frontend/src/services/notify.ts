/**
 * Framework-neutral notification port for services and stores.
 *
 * Services must not import a UI library. The app registers a sink at startup
 * (the new toast system, or the legacy antd `message` for old screens);
 * until then messages are dropped silently, which keeps unit tests quiet.
 */
export type NotifyLevel = 'info' | 'success' | 'warning' | 'error'
export type NotifySink = (level: NotifyLevel, text: string) => void

let sink: NotifySink | null = null

export function setNotifySink(next: NotifySink | null): void {
  sink = next
}

function emit(level: NotifyLevel, text: string): void {
  try {
    sink?.(level, text)
  } catch {
    // Notification failures must never break a data request.
  }
}

export const notify = {
  info: (text: string) => emit('info', text),
  success: (text: string) => emit('success', text),
  warning: (text: string) => emit('warning', text),
  error: (text: string) => emit('error', text),
}
