import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Form, Input, Button, Tabs, message, Card, Checkbox, Space } from 'antd'
import { UserOutlined, LockOutlined, MailOutlined, ThunderboltOutlined, ReadOutlined, FieldTimeOutlined } from '@ant-design/icons'
import { useAuthStore } from '../stores/authStore'
import { register } from '../services/authApi'
import { clearSavedLogin, getSavedLogin, isDesktopAuthAvailable } from '../services/desktopAuth'
import { MnemoxLogo } from '../components/MnemoxLogo'

export function LoginPage() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const [loginForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [rememberPassword, setRememberPassword] = useState(false)
  const [autoLogin, setAutoLogin] = useState(false)
  const desktopAuthAvailable = isDesktopAuthAvailable()

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      navigate('/', { replace: true })
    }
  }, [isAuthenticated, navigate])

  useEffect(() => {
    if (!desktopAuthAvailable || isAuthenticated) return
    let cancelled = false
    const loadSavedLogin = async () => {
      const saved = await getSavedLogin()
      if (cancelled || !saved) return
      loginForm.setFieldsValue({
        username: saved.username,
        password: saved.password,
      })
      setRememberPassword(true)
      setAutoLogin(saved.autoLogin)
      if (saved.autoLogin) {
        setLoading(true)
        try {
          await login(saved.username, saved.password)
          message.success('已自动登录')
          navigate('/', { replace: true })
        } catch (e: any) {
          message.error(e?.message || '自动登录失败，请重新登录')
        } finally {
          if (!cancelled) setLoading(false)
        }
      }
    }
    void loadSavedLogin()
    return () => { cancelled = true }
  }, [desktopAuthAvailable, isAuthenticated, login, loginForm, navigate])

  const handleLogin = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      await login(values.username, values.password, {
        rememberPassword: desktopAuthAvailable && rememberPassword,
        autoLogin: desktopAuthAvailable && rememberPassword && autoLogin,
      })
      message.success('登录成功')
      navigate('/', { replace: true })
    } catch (e: any) {
      message.error(e?.message || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  const handleClearSavedLogin = async () => {
    try {
      await clearSavedLogin()
      loginForm.resetFields(['password'])
      setRememberPassword(false)
      setAutoLogin(false)
      message.success('已清除保存的登录信息')
    } catch (e: any) {
      message.error(e?.message || '清除已保存登录信息失败')
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
        <Form form={loginForm} name="login" onFinish={handleLogin} autoComplete="on" size="large" style={{ marginTop: 16 }}>
          <Form.Item
            name="username"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input
              id="login-username"
              name="username"
              autoComplete="username"
              prefix={<UserOutlined style={{ color: 'var(--text-secondary)' }} />}
              placeholder="用户名"
            />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              id="login-password"
              name="password"
              autoComplete="current-password"
              prefix={<LockOutlined style={{ color: 'var(--text-secondary)' }} />}
              placeholder="密码"
            />
          </Form.Item>
          {desktopAuthAvailable && (
            <Form.Item style={{ marginBottom: 8 }}>
              <Space direction="vertical" size={4}>
                <Checkbox
                  checked={rememberPassword}
                  onChange={(event) => {
                    setRememberPassword(event.target.checked)
                    if (!event.target.checked) setAutoLogin(false)
                  }}
                >
                  记住密码
                </Checkbox>
                <Checkbox
                  checked={autoLogin}
                  disabled={!rememberPassword}
                  onChange={(event) => setAutoLogin(event.target.checked)}
                >
                  下次自动登录
                </Checkbox>
                <Button
                  type="link"
                  size="small"
                  onClick={() => void handleClearSavedLogin()}
                  style={{ padding: 0, alignSelf: 'flex-start' }}
                >
                  清除已保存登录信息
                </Button>
              </Space>
            </Form.Item>
          )}
          <Form.Item style={{ marginTop: 32 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
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
        <Form name="register" onFinish={handleRegister} autoComplete="on" size="large" style={{ marginTop: 16 }}>
          <Form.Item
            name="username"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 2, max: 50, message: '用户名长度 2-50' },
            ]}
          >
            <Input
              id="register-username"
              name="username"
              autoComplete="username"
              prefix={<UserOutlined style={{ color: 'var(--text-secondary)' }} />}
              placeholder="用户名"
            />
          </Form.Item>
          <Form.Item
            name="email"
            rules={[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '邮箱格式不正确' },
            ]}
          >
            <Input
              id="register-email"
              name="email"
              autoComplete="email"
              prefix={<MailOutlined style={{ color: 'var(--text-secondary)' }} />}
              placeholder="邮箱"
            />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 6, message: '密码至少 6 位' },
            ]}
          >
            <Input.Password
              id="register-password"
              name="password"
              autoComplete="new-password"
              prefix={<LockOutlined style={{ color: 'var(--text-secondary)' }} />}
              placeholder="密码"
            />
          </Form.Item>
          <Form.Item style={{ marginTop: 32 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
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
        background: 'var(--bg-base)',
        color: 'var(--text-primary)',
        overflow: 'hidden',
        position: 'relative'
      }}
    >
      {/* Background decorations */}
      <div style={{ position: 'absolute', top: -200, left: -200, width: 800, height: 800, background: 'radial-gradient(circle, rgba(99, 102, 241, 0.15) 0%, transparent 70%)', borderRadius: '50%' }} />
      <div style={{ position: 'absolute', bottom: -300, right: -100, width: 1000, height: 1000, background: 'radial-gradient(circle, rgba(45, 212, 191, 0.08) 0%, transparent 70%)', borderRadius: '50%' }} />
      
      {/* Left side: Brand area */}
      <div style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        padding: '0 10%',
        zIndex: 1,
        borderRight: '1px solid var(--border-light)',
        background: 'rgba(17, 24, 39, 0.4)',
        backdropFilter: 'blur(20px)'
      }}>
        <div style={{ maxWidth: 480 }}>
          <div style={{ marginBottom: 32 }}>
            <MnemoxLogo size={64} />
          </div>
          <h1 style={{ fontSize: 48, fontWeight: 700, marginBottom: 16, fontFamily: 'Space Grotesk', letterSpacing: 0, background: 'linear-gradient(to right, #fff, var(--text-secondary))', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            Mnemox
          </h1>
          <p style={{ fontSize: 18, color: 'var(--text-secondary)', marginBottom: 48, lineHeight: 1.6 }}>
            你的 AI 学习记忆教练。连接资料、计划、复盘与长期记忆。
          </p>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            {[
              { icon: <ThunderboltOutlined />, title: 'AI 驱动学习', desc: '智能分析弱点，自动生成复习计划' },
              { icon: <ReadOutlined />, title: '网状知识图谱', desc: 'Obsidian 风格双链笔记，关联你的所有知识' },
              { icon: <FieldTimeOutlined />, title: '深度工作流', desc: '集成番茄钟与进度引擎，培养心流状态' }
            ].map(feature => (
              <div key={feature.title} style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
                <div style={{ 
                  width: 40, height: 40, borderRadius: 10, background: 'rgba(99, 102, 241, 0.1)', 
                  display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--brand-400)', fontSize: 20 
                }}>
                  {feature.icon}
                </div>
                <div>
                  <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>{feature.title}</div>
                  <div style={{ fontSize: 14, color: 'var(--text-secondary)' }}>{feature.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right side: Login form */}
      <div style={{
        flex: 1,
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        zIndex: 1,
      }}>
        <Card
          style={{
            width: '100%',
            maxWidth: 420,
            background: 'var(--bg-surface)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            boxShadow: '0 24px 48px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.05)',
            backdropFilter: 'blur(20px)',
            borderRadius: 24,
            padding: '16px 8px'
          }}
        >
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <h2 style={{ fontSize: 24, fontWeight: 600, margin: 0, fontFamily: 'Space Grotesk' }}>欢迎回来</h2>
            <p style={{ color: 'var(--text-secondary)', marginTop: 8 }}>登录以继续你的学习闭环</p>
          </div>
          <Tabs items={items} centered size="large" />
        </Card>
      </div>
    </div>
  )
}
