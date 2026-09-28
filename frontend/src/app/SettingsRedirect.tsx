import { useEffect } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { useShell, type SettingsSection } from './shell/shellStore'

/** Legacy full-page settings routes now open the settings dialog. */
export function SettingsRedirect({ section }: { section: SettingsSection }) {
  const [params] = useSearchParams()
  const openSettings = useShell(st => st.openSettings)
  useEffect(() => {
    openSettings(section, params.get('mode'))
  }, [openSettings, params, section])
  return <Navigate to="/today" replace />
}
