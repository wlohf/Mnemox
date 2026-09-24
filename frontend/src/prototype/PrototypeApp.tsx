import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, Menu, Moon, PanelLeft, PanelRight, Sun } from 'lucide-react'
import { IconButton, TooltipProvider } from '../ui'
import { Sidebar } from './shell/Sidebar'
import { EvidencePanel } from './shell/EvidencePanel'
import { CommandPalette } from './shell/CommandPalette'
import { Composer, HomePage } from './home/HomePage'
import s from './shell/shell.module.css'

type Theme = 'light' | 'dark'

function initialTheme(): Theme {
  const q = new URLSearchParams(location.search).get('theme')
  if (q === 'dark' || q === 'light') return q
  const saved = localStorage.getItem('mx_proto_theme')
  if (saved === 'dark' || saved === 'light') return saved
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function PrototypeApp() {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [collapsed, setCollapsed] = useState(false)
  const [mobileNav, setMobileNav] = useState(false)
  const [evidence, setEvidence] = useState(() => new URLSearchParams(location.search).get('evidence') === '1')
  const [activeCite, setActiveCite] = useState<number | null>(null)
  const [cmd, setCmd] = useState(false)
  const [page, setPage] = useState('today')

  useEffect(() => {
    const root = document.documentElement
    root.dataset.mxTheme = theme
    localStorage.setItem('mx_proto_theme', theme)
  }, [theme])

  const toggleTheme = useCallback(() => {
    const apply = () => setTheme(t => (t === 'dark' ? 'light' : 'dark'))
    const d = document as Document & { startViewTransition?: (cb: () => void) => unknown }
    if (d.startViewTransition && !matchMedia('(prefers-reduced-motion: reduce)').matches) d.startViewTransition(apply)
    else apply()
  }, [])

  const openCite = useCallback((n: number) => {
    setActiveCite(n)
    setEvidence(true)
  }, [])

  const navigate = useCallback((key: string) => {
    setPage(key)
    setMobileNav(false)
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); setCmd(v => !v) }
      else if (mod && e.key === '\\') { e.preventDefault(); setCollapsed(v => !v) }
      else if (mod && e.key === '.') { e.preventDefault(); setEvidence(v => !v) }
      else if (e.key === 'Escape') { setMobileNav(false); if (innerWidth <= 1180) setEvidence(false) }
    }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [])

  return (
    <TooltipProvider>
      <div
        className={s.shell}
        data-sidebar={collapsed ? 'collapsed' : undefined}
        data-evidence={evidence ? 'open' : undefined}
        data-mobile-nav={mobileNav ? 'open' : undefined}
      >
        <Sidebar
          current={page}
          onNavigate={navigate}
          onToggle={() => setCollapsed(v => !v)}
          onOpenCommand={() => setCmd(true)}
        />

        <main className={s.main}>
          <div className={s.topbar}>
            <span className={s.mobileBar}>
              <IconButton label="打开导航" onClick={() => setMobileNav(true)}><Menu /></IconButton>
            </span>
            {collapsed && (
              <span className={s.desktopOnly}>
                <IconButton label="展开侧栏" kbd={['⌘', '\\']} onClick={() => setCollapsed(false)}><PanelLeft /></IconButton>
              </span>
            )}
            <nav className={s.crumbs} aria-label="位置">
              <span>学习工作台</span><ChevronRight /><strong>今天</strong>
            </nav>
            <div className={s.topbarEnd}>
              <IconButton label={theme === 'dark' ? '浅色' : '深色'} onClick={toggleTheme}>
                {theme === 'dark' ? <Sun /> : <Moon />}
              </IconButton>
              <span className={s.vDivider} />
              <IconButton label="证据面板" kbd={['⌘', '.']} data-active={evidence || undefined} onClick={() => setEvidence(v => !v)}>
                <PanelRight />
              </IconButton>
            </div>
          </div>

          <div className={s.scroll}>
            <HomePage activeCite={activeCite} onCite={openCite} />
          </div>
          <Composer />
        </main>

        <aside className={s.evidence} aria-label="证据" aria-hidden={!evidence}>
          <div className={s.evidenceInner}>
            <EvidencePanel active={activeCite} onActive={setActiveCite} onClose={() => setEvidence(false)} />
          </div>
        </aside>

        <div className={s.scrim} onClick={() => { setMobileNav(false); setEvidence(false) }} />
      </div>

      <CommandPalette open={cmd} onOpenChange={setCmd} onToggleTheme={toggleTheme} onNavigate={navigate} />
    </TooltipProvider>
  )
}
