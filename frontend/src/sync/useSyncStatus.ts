import { useSyncExternalStore } from 'react'
import { syncEngine, type SyncState } from './SyncEngine'

export function useSyncStatus(): SyncState {
  return useSyncExternalStore(
    syncEngine.subscribe.bind(syncEngine),
    syncEngine.getSnapshot,
    syncEngine.getSnapshot, // server snapshot (SSR fallback)
  )
}
