import React from 'react'
import ReactDOM from 'react-dom/client'
import '@fontsource-variable/inter/wght.css'
import '@fontsource-variable/noto-serif-sc/wght.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import './design/tokens.css'
import './design/base.css'
// Legacy stylesheet for screens still on Ant Design; loaded after the base so
// its scoped rules keep working, but it no longer defines colours.
import './index.css'
import './stores/themeStore' // applies the theme attribute before first paint
import App from './App'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
