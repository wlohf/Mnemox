import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Form, Input, Button, Tabs, message, Card } from 'antd'
import { UserOutlined, LockOutlined, MailOutlined } from '@ant-design/icons'
import { useAuthStore } from '../stores/authStore'
import { register } from '../services/authApi'

export function LoginPage() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const [loading, setLoading] = useState(false)

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      navigate('/', { replace: true })
    }
  }, [isAuthenticated, navigate])

  const handleLogin = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      await login(values.username, values.password)
      message.success('登录成功')
      navigate('/', { replace: true })
    } catch (e: any) {
      message.error(e?.message || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  const handleRegister = async (values: {
    username: string
    email: string
    password: string
  }) => {
    setLoading(true)
    try {
      await register(values.username, values.email, values.password)
    } catch (e: any) {
      message.error(e?.message || '注册失败')
      setLoading(false)
      return
    }
    // Registration succeeded — now auto-login
    try {
      await login(values.username, values.password)
      message.success('注册成功，已自动登录')
      navigate('/', { replace: true })
    } catch {
      message.success('注册成功，请登录')
      setLoading(false)
    }
  }

  const items = [
    {
      key: 'login',
      label: '登录',
      children: (
        <Form onFinish={handleLogin} autoComplete="off" size="large">
          <Form.Item
            name="username"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              style={{ background: '#c08a5c', borderColor: '#c08a5c' }}
            >
              登录
            </Button>
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'register',
      label: '注册',
      children: (
        <Form onFinish={handleRegister} autoComplete="off" size="large">
          <Form.Item
            name="username"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 2, max: 50, message: '用户名长度 2-50' },
            ]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item
            name="email"
            rules={[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '邮箱格式不正确' },
            ]}
          >
            <Input prefix={<MailOutlined />} placeholder="邮箱" />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 6, message: '密码至少 6 位' },
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              style={{ background: '#c08a5c', borderColor: '#c08a5c' }}
            >
              注册
            </Button>
          </Form.Item>
        </Form>
      ),
    },
  ]

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        background: 'linear-gradient(135deg, #f5f0e8 0%, #e8ddd0 100%)',
      }}
    >
      <Card
        style={{
          width: 400,
          boxShadow: '0 4px 24px rgba(0,0,0,0.1)',
          borderRadius: 12,
        }}
      >
        <h2
          style={{
            textAlign: 'center',
            color: '#c08a5c',
            marginBottom: 24,
            fontSize: 24,
          }}
        >
          StudyAssistant
        </h2>
        <Tabs items={items} centered />
      </Card>
    </div>
  )
}
