import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

const themeStoreMock = vi.hoisted(() => ({
  setMode: vi.fn(),
  setBgImage: vi.fn(),
  setBgOpacity: vi.fn(),
  resetToDefault: vi.fn(),
}))

vi.mock('../stores/themeStore', () => ({
  useThemeStore: () => ({
    mode: 'system',
    setMode: themeStoreMock.setMode,
    resolvedTheme: 'warm',
    bgImage: null,
    bgOpacity: 0.15,
    setBgImage: themeStoreMock.setBgImage,
    setBgOpacity: themeStoreMock.setBgOpacity,
    resetToDefault: themeStoreMock.resetToDefault,
  }),
}))

const imageApiMock = vi.hoisted(() => ({
  uploadBackgroundImageStrict: vi.fn().mockResolvedValue({
    url: '/api/uploads/images/1/background.png?token=test-token',
    raw_url: '/api/uploads/images/1/background.png',
    filename: 'background.png',
    original_name: 'large-background.png',
    markdown: '![large-background.png](/api/uploads/images/1/background.png?token=test-token)',
  }),
}))

vi.mock('../services/imageApi', () => imageApiMock)

const messageMock = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
}))

vi.mock('antd', () => {
  const Button = ({ children, onClick, ...props }: any) => (
    <button type="button" onClick={onClick} disabled={props.disabled}>
      {children}
    </button>
  )
  const Modal = ({ open, children }: any) => (open ? <div>{children}</div> : null)
  const Tabs = ({ items = [] }: any) => <div>{items[0]?.children}</div>
  const Radio = ({ children }: any) => <label>{children}</label>
  Radio.Group = ({ children }: any) => <div>{children}</div>
  const Space = ({ children }: any) => <div>{children}</div>
  const Divider = () => <hr />
  const Select = () => <select />
  const Switch = () => <input type="checkbox" />
  const Slider = () => <input type="range" />
  const InputNumber = () => <input type="number" />
  const TimePicker = () => <input />

  return {
    Button,
    Divider,
    InputNumber,
    Modal,
    Radio,
    Select,
    Slider,
    Space,
    Switch,
    Tabs,
    TimePicker,
    message: messageMock,
  }
})

vi.mock('@ant-design/icons', () => {
  const Icon = () => <span />
  return {
    ApiOutlined: Icon,
    BgColorsOutlined: Icon,
    DeleteOutlined: Icon,
    DesktopOutlined: Icon,
    FileTextOutlined: Icon,
    MoonOutlined: Icon,
    PictureOutlined: Icon,
    RobotOutlined: Icon,
    SettingOutlined: Icon,
    SmileOutlined: Icon,
    SunOutlined: Icon,
  }
})

vi.mock('./AISettingsDrawer', () => ({
  AISettingsDrawer: () => null,
}))

import { SettingsModal } from './SettingsModal'

describe('SettingsModal custom background upload', () => {
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
    vi.clearAllMocks()
  })

  it('uploads large custom backgrounds instead of rejecting them at 5MB', async () => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)

    await act(async () => {
      root!.render(
        <MemoryRouter>
          <SettingsModal open onClose={() => {}} />
        </MemoryRouter>,
      )
    })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement | null
    expect(input).not.toBeNull()

    const file = new File([new Uint8Array(6 * 1024 * 1024)], 'large-background.png', {
      type: 'image/png',
    })
    Object.defineProperty(input, 'files', {
      value: [file],
      configurable: true,
    })

    await act(async () => {
      input!.dispatchEvent(new Event('change', { bubbles: true }))
      await Promise.resolve()
    })

    expect(messageMock.warning).not.toHaveBeenCalledWith('图片不能超过 5MB')
    expect(imageApiMock.uploadBackgroundImageStrict).toHaveBeenCalledWith(file)
    expect(themeStoreMock.setBgImage).toHaveBeenCalledWith('/api/uploads/images/1/background.png')
  })
})
