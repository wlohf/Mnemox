import { useMemo, type ReactNode } from 'react'
import { App as AntdApp, ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useThemeStore } from '../stores/themeStore'

/*
 * Screens not yet rebuilt on the Mnemox UI kit still use Ant Design. This
 * boundary feeds antd the same palette (as literal hex, which antd's token
 * parser requires) so those screens sit in the new shell without clashing.
 */

const LIGHT = {
  colorPrimary: '#284f88',
  colorPrimaryHover: '#20447a',
  colorPrimaryActive: '#17396b',
  colorPrimaryBg: '#e8f0fd',
  colorBgContainer: '#fdfdfe',
  colorBgLayout: '#f6f7fa',
  colorBgElevated: '#ffffff',
  colorBorder: '#dde0e5',
  colorBorderSecondary: '#e6e8ec',
  colorText: '#191e29',
  colorTextSecondary: '#444954',
  colorTextTertiary: '#5f636d',
  colorTextQuaternary: '#8e929a',
  colorSuccess: '#267450',
  colorWarning: '#b15900',
  colorError: '#ba312c',
  colorInfo: '#284f88',
  colorLink: '#284f88',
  colorLinkHover: '#20447a',
  colorFillSecondary: '#191e290d',
  colorFillTertiary: '#191e290a',
}

const DARK = {
  colorPrimary: '#8db3ea',
  colorPrimaryHover: '#9cc0f5',
  colorPrimaryActive: '#7fa6e0',
  colorPrimaryBg: '#1f2c3f',
  colorBgContainer: '#161920',
  colorBgLayout: '#101318',
  colorBgElevated: '#1d2027',
  colorBorder: '#2a2e35',
  colorBorderSecondary: '#23262d',
  colorText: '#e7eaef',
  colorTextSecondary: '#b7bbc2',
  colorTextTertiary: '#9498a1',
  colorTextQuaternary: '#656970',
  colorSuccess: '#73c59e',
  colorWarning: '#eea563',
  colorError: '#f07f77',
  colorInfo: '#8db3ea',
  colorLink: '#8db3ea',
  colorLinkHover: '#9cc0f5',
  colorFillSecondary: '#e7eaef18',
  colorFillTertiary: '#e7eaef0e',
}

export function useLegacyAntdTheme() {
  const dark = useThemeStore(st => st.resolvedTheme === 'dark')
  return useMemo(
    () => ({
      algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
      token: {
        ...(dark ? DARK : LIGHT),
        colorTextLightSolid: dark ? '#0b1729' : '#fafcfe',
        borderRadius: 7,
        borderRadiusLG: 12,
        fontFamily: "'Inter Variable', 'Inter', -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei UI', 'Microsoft YaHei', 'Segoe UI', system-ui, sans-serif",
        fontSize: 14,
        controlHeight: 34,
        boxShadow: '0 1px 2px rgba(25,30,41,0.04), 0 8px 20px -6px rgba(25,30,41,0.1)',
        boxShadowSecondary: '0 2px 4px rgba(25,30,41,0.04), 0 18px 44px -14px rgba(25,30,41,0.22)',
        motionDurationMid: '0.2s',
      },
      components: {
        Button: { primaryShadow: 'none', defaultShadow: 'none', dangerShadow: 'none', fontWeight: 560 },
        Card: { headerFontSize: 14 },
        Layout: { bodyBg: dark ? '#101318' : '#f6f7fa', siderBg: dark ? '#0b0d12' : '#eef0f5', headerBg: 'transparent' },
        Modal: { titleFontSize: 17 },
        Tabs: { inkBarColor: dark ? '#8db3ea' : '#284f88' },
      },
    }),
    [dark],
  )
}

export function LegacyBoundary({ children }: { children: ReactNode }) {
  const antdTheme = useLegacyAntdTheme()
  return (
    <ConfigProvider locale={zhCN} theme={antdTheme}>
      <AntdApp className="mx-legacy">{children}</AntdApp>
    </ConfigProvider>
  )
}
