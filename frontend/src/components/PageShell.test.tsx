import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { PageShell } from './PageShell'

vi.mock('./SettingsModal', () => ({
  SettingsModal: ({ open }: { open: boolean }) => (open ? <div data-testid="settings-modal">设置弹窗</div> : null),
}))

function LocationProbe() {
  const location = useLocation()

  return <div data-testid="location">{location.pathname}</div>
}

describe('PageShell settings entry', () => {
  let container: HTMLDivElement | null = null
  let root: ReturnType<typeof createRoot> | null = null

  afterEach(() => {
    if (root) {
      act(() => {
        root?.unmount()
      })
      root = null
    }
    if (container) {
      container.remove()
      container = null
    }
    vi.restoreAllMocks()
  })

  it('opens the settings modal without routing to the profile page', () => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)

    act(() => {
      root!.render(
        <MemoryRouter initialEntries={['/dashboard']}>
          <PageShell title="测试页面" onBack={() => {}}>
            <LocationProbe />
          </PageShell>
        </MemoryRouter>,
      )
    })

    const settingsButton = container.querySelector('button[aria-label="设置"]')
    expect(settingsButton).not.toBeNull()

    act(() => {
      settingsButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(container.querySelector('[data-testid="settings-modal"]')?.textContent).toContain('设置弹窗')
    expect(container.querySelector('[data-testid="location"]')?.textContent).toBe('/dashboard')
  })
})
