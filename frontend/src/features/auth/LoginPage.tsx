import { useEffect, useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Lock, Mail, UserRound } from 'lucide-react'
import { Button, Checkbox, Field, Input, Notice, Segmented, Wordmark, toast } from '../../ui'
import { useAuthStore } from '../../stores/authStore'
import { register } from '../../services/authApi'
import { clearSavedLogin, getSavedLogin, isDesktopAuthAvailable } from '../../services/desktopAuth'
import s from './login.module.css'

type Mode = 'login' | 'register'

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function PasswordInput({
  id,
  value,
  onChange,
  autoComplete,
  invalid,
  placeholder,
}: {
  id: string
  value: string
  onChange: (v: string) => void
  autoComplete: string
  invalid?: boolean
  placeholder?: string
}) {
  const [shown, setShown] = useState(false)
  return (
    <Input
      id={id}
      name="password"
      type={shown ? 'text' : 'password'}
      autoComplete={autoComplete}
      value={value}
      onChange={e => onChange(e.target.value)}
      invalid={invalid}
      placeholder={placeholder}
      size="lg"
      prefix={<Lock />}
      suffix={
        <button type="button" className={s.peek} onClick={() => setShown(v => !v)} aria-label={shown ? '隐藏密码' : '显示密码'}>
          {shown ? <EyeOff /> : <Eye />}
        </button>
      }
    />
  )
}

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const login = useAuthStore(st => st.login)
  const isAuthenticated = useAuthStore(st => st.isAuthenticated)
  const desktop = isDesktopAuthAvailable()
  const [mode, setMode] = useState<Mode>('login')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [autoLogin, setAutoLogin] = useState(false)
  const [loading, setLoading] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)

  const from = (location.state as { from?: string } | null)?.from
  const destination = from && from.startsWith('/') && !from.startsWith('//') ? from : '/today'

  useEffect(() => {
    if (isAuthenticated) navigate(destination, { replace: true })
  }, [isAuthenticated, navigate, destination])

  // Desktop: prefill the saved login; auto-login if the learner asked for it.
  useEffect(() => {
    if (!desktop || isAuthenticated) return
    let cancelled = false
    void (async () => {
      const saved = await getSavedLogin()
      if (cancelled || !saved) return
      setUsername(saved.username)
      setPassword(saved.password)
      setRemember(true)
      setAutoLogin(saved.autoLogin)
      if (!saved.autoLogin) return
      setLoading(true)
      try {
        await login(saved.username, saved.password)
        toast.success('已自动登录')
      } catch (e) {
        setFormError(e instanceof Error ? e.message : '自动登录失败，请重新登录')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [desktop, isAuthenticated, login])

  const validate = (): boolean => {
    const next: Record<string, string> = {}
    const name = username.trim()
    if (!name) next.username = '请输入用户名'
    else if (mode === 'register' && (name.length < 2 || name.length > 50)) next.username = '用户名长度需要在 2 到 50 个字符之间'
    if (mode === 'register') {
      if (!email.trim()) next.email = '请输入邮箱'
      else if (!EMAIL_RE.test(email.trim())) next.email = '邮箱格式不正确'
    }
    if (!password) next.password = '请输入密码'
    else if (mode === 'register' && password.length < 12) next.password = '密码至少 12 位'
    setErrors(next)
    return Object.keys(next).length === 0
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setFormError(null)
    if (!validate()) return
    setLoading(true)
    try {
      if (mode === 'register') {
        try {
          await register(username.trim(), email.trim(), password)
        } catch (err) {
          setFormError(err instanceof Error ? err.message : '注册失败')
          return
        }
        try {
          await login(username.trim(), password)
          toast.success('注册成功，欢迎来到 Mnemox')
        } catch {
          toast.success('注册成功，请登录')
          setMode('login')
        }
        return
      }
      await login(username.trim(), password, {
        rememberPassword: desktop && remember,
        autoLogin: desktop && remember && autoLogin,
      })
    } catch (err) {
      setFormError(err instanceof Error ? err.message : '登录失败')
    } finally {
      setLoading(false)
    }
  }

  const clearSaved = async () => {
    try {
      await clearSavedLogin()
      setPassword('')
      setRemember(false)
      setAutoLogin(false)
      toast.success('已清除保存的登录信息')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '清除失败')
    }
  }

  const switchMode = (m: Mode) => {
    setMode(m)
    setErrors({})
    setFormError(null)
  }

  return (
    <div className={s.root}>
      <section className={s.folio} aria-hidden="true">
        <div className={s.folioBrand}>
          <Wordmark tile={30} />
        </div>
        <div className={s.folioBody}>
          <p className={s.folioKicker}>AI 学习教练 · 本地优先</p>
          <h2 className={s.folioTitle}>
            每一条建议，
            <br />
            都能追溯到<mark>你自己的学习记录</mark>。
          </h2>
          <p className={s.folioLead}>
            Mnemox 把资料、计划、专注、复习与复盘连成一个闭环。它记得你在哪里卡住，也知道你什么时候学得最好。
          </p>
          <ol className={s.principles}>
            <li className={s.principle}>
              <span className={s.principleIdx}>一</span>
              <span>
                <span className={s.principleTitle}>先做最关键的一件事</span>
                <span className={s.principleBody}>每天只给一个清楚的下一步，而不是一堆待办。</span>
              </span>
            </li>
            <li className={s.principle}>
              <span className={s.principleIdx}>二</span>
              <span>
                <span className={s.principleTitle}>证据写在建议旁边</span>
                <span className={s.principleBody}>错题、笔记、复习记录，点开编号就能看到原文。</span>
              </span>
            </li>
            <li className={s.principle}>
              <span className={s.principleIdx}>三</span>
              <span>
                <span className={s.principleTitle}>你确认之前，什么都不写入</span>
                <span className={s.principleBody}>教练只起草任务、笔记和记忆，由你决定是否保留。</span>
              </span>
            </li>
          </ol>
        </div>
        <div className={s.folioFoot}>学习数据保存在你自己的设备与服务里。</div>
      </section>

      <main className={s.panel}>
        <div className={s.card}>
          <h1 className={s.cardTitle}>{mode === 'login' ? '欢迎回来' : '开始一段学习'}</h1>
          <p className={s.cardLead}>{mode === 'login' ? '登录后继续你的学习闭环。' : '创建账号，数据只属于你。'}</p>

          <div className={s.switcher}>
            <Segmented
              block
              ariaLabel="登录或注册"
              value={mode}
              onChange={switchMode}
              options={[
                { value: 'login', label: '登录' },
                { value: 'register', label: '注册' },
              ]}
            />
          </div>

          <form className={s.form} onSubmit={submit} noValidate>
            <Field label="用户名" htmlFor={`${mode}-username`} error={errors.username}>
              <Input
                id={`${mode}-username`}
                name="username"
                autoComplete="username"
                size="lg"
                prefix={<UserRound />}
                value={username}
                invalid={!!errors.username}
                onChange={e => setUsername(e.target.value)}
                autoFocus
              />
            </Field>
            {mode === 'register' && (
              <Field label="邮箱" htmlFor="register-email" error={errors.email}>
                <Input
                  id="register-email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  size="lg"
                  prefix={<Mail />}
                  value={email}
                  invalid={!!errors.email}
                  onChange={e => setEmail(e.target.value)}
                />
              </Field>
            )}
            <Field
              label="密码"
              htmlFor={`${mode}-password`}
              error={errors.password}
              hint={mode === 'register' ? '至少 12 位，不要包含用户名。' : undefined}
            >
              <PasswordInput
                id={`${mode}-password`}
                value={password}
                onChange={setPassword}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                invalid={!!errors.password}
              />
            </Field>

            {mode === 'login' && desktop && (
              <div className={s.remember}>
                <Checkbox
                  checked={remember}
                  onCheckedChange={v => {
                    setRemember(v)
                    if (!v) setAutoLogin(false)
                  }}
                  label="记住密码"
                />
                <Checkbox checked={autoLogin} disabled={!remember} onCheckedChange={setAutoLogin} label="下次自动登录" />
                <button type="button" className={s.clearLink} onClick={() => void clearSaved()}>
                  清除已保存登录信息
                </button>
              </div>
            )}

            {formError && (
              <Notice tone="danger" role="alert" className={s.formError}>
                {formError}
              </Notice>
            )}

            <Button type="submit" variant="primary" size="lg" block loading={loading} className={s.submit}>
              {mode === 'login' ? '登录' : '创建账号'}
            </Button>
          </form>

          <p className={s.foot}>
            {mode === 'login' ? (
              <>
                还没有账号？ <button type="button" onClick={() => switchMode('register')}>注册一个</button>
              </>
            ) : (
              <>
                已经有账号了？ <button type="button" onClick={() => switchMode('login')}>直接登录</button>
              </>
            )}
          </p>
        </div>
      </main>
    </div>
  )
}
