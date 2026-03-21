import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout as AntLayout, Menu, theme } from 'antd'
import {
  DashboardOutlined,
  BookOutlined,
  ReadOutlined,
  ReloadOutlined,
  ExceptionOutlined,
  BarChartOutlined,
  EditOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import type { MenuProps } from 'antd'

const { Header, Content, Sider } = AntLayout

type MenuItem = Required<MenuProps>['items'][number]

const menuItems: MenuItem[] = [
  { key: '/', icon: <DashboardOutlined />, label: '仪表盘' },
  { key: '/materials', icon: <BookOutlined />, label: '资料管理' },
  { key: '/study', icon: <ReadOutlined />, label: '学习空间' },
  { key: '/review', icon: <ReloadOutlined />, label: '复习中心' },
  { key: '/wrong-questions', icon: <ExceptionOutlined />, label: '错题本' },
  { key: '/statistics', icon: <BarChartOutlined />, label: '统计分析' },
  { key: '/notes', icon: <EditOutlined />, label: '笔记' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
]

export function Layout() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const {
    token: { colorBgContainer, borderRadiusLG },
  } = theme.useToken()

  const handleMenuClick: MenuProps['onClick'] = (e) => {
    navigate(e.key)
  }

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}>
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontSize: collapsed ? 16 : 20,
            fontWeight: 'bold',
          }}
        >
          {collapsed ? '学' : '学习助手'}
        </div>
        <Menu
          theme="dark"
          selectedKeys={[location.pathname]}
          mode="inline"
          items={menuItems}
          onClick={handleMenuClick}
        />
      </Sider>
      <AntLayout>
        <Header style={{ padding: 0, background: colorBgContainer }} />
        <Content style={{ margin: '24px 16px 0' }}>
          <div
            style={{
              padding: 24,
              minHeight: 360,
              background: colorBgContainer,
              borderRadius: borderRadiusLG,
            }}
          >
            <Outlet />
          </div>
        </Content>
      </AntLayout>
    </AntLayout>
  )
}
