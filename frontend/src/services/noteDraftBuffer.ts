/** A pending draft is flushed on navigation; debounce only delays background writes. */
export class NoteDraftBuffer {
  private pending: { key: string; value: Record<string, unknown>; onSaved: (at: string) => void } | null = null
  private timer: ReturnType<typeof setTimeout> | undefined

  constructor(private storage: Pick<Storage, 'setItem'>, private onError: () => void) {}

  schedule(key: string, value: Record<string, unknown>, onSaved: (at: string) => void) {
    if (this.pending && this.pending.key !== key && !this.flush()) return
    clearTimeout(this.timer)
    this.pending = { key, value, onSaved }
    this.timer = setTimeout(() => this.flush(), 700)
  }

  flush(): boolean {
    clearTimeout(this.timer)
    if (!this.pending) return true
    const draft = this.pending
    const savedAt = new Date().toISOString()
    try {
      this.storage.setItem(draft.key, JSON.stringify({ ...draft.value, savedAt }))
    } catch {
      this.onError()
      return false // Keep the snapshot so a later flush can retry.
    }
    this.pending = null
    draft.onSaved(savedAt)
    return true
  }

  discard(key: string) {
    if (this.pending?.key === key) {
      clearTimeout(this.timer)
      this.pending = null
    }
  }
}
