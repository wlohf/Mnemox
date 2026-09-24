import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import '../design/tokens.css'
import './prototype.css'
import { PrototypeApp } from './PrototypeApp'

// Tokens live on <html> so Radix portals (tooltips, dialogs) inherit them.
document.documentElement.classList.add('mx-root')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PrototypeApp />
  </StrictMode>,
)
