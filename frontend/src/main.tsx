import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#c08a5c',
          colorBgContainer: '#fffbf5',
          colorBgLayout: '#faf6f0',
          colorBgElevated: '#fffdf8',
          colorBorder: '#ede4d9',
          colorBorderSecondary: '#f0e8dd',
          colorText: '#1d1d1f',
          colorTextSecondary: '#8b7355',
          colorTextTertiary: '#b09b82',
          borderRadius: 10,
          colorLink: '#b07d3a',
          colorSuccess: '#7cb342',
          colorError: '#d4644a',
          colorWarning: '#e6a23c',
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
)
