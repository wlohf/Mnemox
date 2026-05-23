import { useEffect, useRef, useState } from 'react'
import { Modal, Tabs, Radio, Space, Select, Switch, Divider, Button, message, Slider, InputNumber } from 'antd'
import {
  BgColorsOutlined,
  ApiOutlined,
  FileTextOutlined,
  SettingOutlined,
  SunOutlined,
  MoonOutlined,
  DesktopOutlined,
  SmileOutlined,
  PictureOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import { useThemeStore, type ThemeMode } from '../stores/themeStore'
import { AISettingsDrawer } from './AISettingsDrawer'
import { generateAIQuote } from '../services/motivationApi'
import { checkSystemUpdate, getSystemVersion, type SystemUpdateInfo } from '../services/systemApi'
import { getApiErrorMessage } from '../services/apiClient'
import {
  checkForDesktopUpdate,
  downloadDesktopUpdate,
  getDesktopUpdateState,
  getDesktopUpdateSettings,
  isDesktopUpdaterAvailable,
  quitAndInstallDesktopUpdate,
  setDesktopUpdateSettings,
  subscribeDesktopUpdateState,
  type DesktopUpdateState,
} from '../services/desktopUpdater'
import {
  getDisplayedLatestVersion,
  getDisplayedReleaseNotes,
  hasDownloadableUpdate,
  isDesktopUpdateAvailable,
} from '../services/updateDisplay'
import { useNavigate } from 'react-router-dom'

interface SettingsModalProps {
  open: boolean
  onClose: () => void
}

function showApiError(error: unknown, fallback: string) {
  message.error(getApiErrorMessage(error, fallback))
}

export function SettingsModal({ open, onClose }: SettingsModalProps) {
  const { mode, setMode, bgImage, bgOpacity, setBgImage, setBgOpacity, resetToDefault } = useThemeStore()
  const [aiDrawerOpen, setAiDrawerOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  const handleBgUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 5 * 1024 * 1024) { message.warning('图片不能超过 5MB'); return }
    const reader = new FileReader()
    reader.onload = (ev) => setBgImage(ev.target?.result as string)
    reader.readAsDataURL(file)
    e.target.value = ''
  }

  const themeOptions: { value: ThemeMode; label: React.ReactNode; desc: string }[] = [
    {
      value: 'system',
      label: <span><DesktopOutlined style={{ marginRight: 6 }} />跟随系统</span>,
      desc: '自动跟随操作系统的深色/浅色设置',
    },
    {
      value: 'warm',
      label: <span><SunOutlined style={{ marginRight: 6 }} />白天 · 暖灰工作台</span>,
      desc: '暖灰纸感背景，适合日间专注学习',
    },
    {
      value: 'dark',
      label: <span><MoonOutlined style={{ marginRight: 6 }} />黑夜 · 深色研究舱</span>,
      desc: '石墨深色界面，适合夜间阅读和长时间研究',
    },
  ]

  const tabs = [
    {
      key: 'theme',
      label: <span><BgColorsOutlined /> 主题</span>,
      children: (
        <div style={{ padding: '8px 0' }}>
          <div style={{ marginBottom: 16, color: 'var(--text-secondary)', fontSize: 13 }}>选择界面主题风格</div>
          <Radio.Group
            value={mode}
            onChange={(e) => setMode(e.target.value as ThemeMode)}
            style={{ width: '100%' }}
          >
            <Space direction="vertical" style={{ width: '100%' }}>
              {themeOptions.map((opt) => (
                <Radio
                  key={opt.value}
                  value={opt.value}
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    borderRadius: 'var(--radius-md)',
                    border: `1px solid ${mode === opt.value ? 'var(--primary-600)' : 'var(--border-color)'}`,
                    background: mode === opt.value ? 'var(--primary-50)' : 'var(--bg-tertiary)',
                    marginBottom: 0,
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{opt.label}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>{opt.desc}</div>
                  </div>
                </Radio>
              ))}
            </Space>
          </Radio.Group>

          <Divider style={{ margin: '16px 0 12px' }} />
          <div style={{ fontWeight: 500, fontSize: 13, color: 'var(--text-primary)', marginBottom: 10 }}>
            <PictureOutlined style={{ marginRight: 6 }} />自定义背景图
          </div>
          <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/gif,image/webp,image/bmp" style={{ display: 'none' }} onChange={handleBgUpload} />
          <Space wrap>
            <Button icon={<PictureOutlined />} size="small" onClick={() => fileInputRef.current?.click()}>
              {bgImage ? '更换图片' : '上传图片'}
            </Button>
            {bgImage && (
              <Button icon={<DeleteOutlined />} size="small" danger onClick={() => setBgImage(null)}>
                移除背景
              </Button>
            )}
            <Button size="small" danger onClick={resetToDefault}>
              恢复默认设置
            </Button>
          </Space>
          {bgImage && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 6 }}>
                透明度（越小越浅）：{Math.round(bgOpacity * 100)}%
              </div>
              <Slider
                min={5} max={40} value={Math.round(bgOpacity * 100)}
                onChange={v => setBgOpacity(v / 100)}
                style={{ width: '100%' }}
              />
              <div style={{ marginTop: 8, borderRadius: 6, overflow: 'hidden', height: 60, position: 'relative', border: '1px solid var(--border-color)' }}>
                <img src={bgImage} style={{ width: '100%', height: '100%', objectFit: 'cover', opacity: bgOpacity }} alt="preview" />
              </div>
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'ai',
      label: <span><ApiOutlined /> AI 供应商</span>,
      children: (
        <div style={{ padding: '8px 0' }}>
          <div style={{ marginBottom: 16, color: 'var(--text-secondary)', fontSize: 13 }}>
            配置 AI 模型供应商、API Key 及路由策略
          </div>
          <Button
            type="default"
            icon={<ApiOutlined />}
            onClick={() => { setAiDrawerOpen(true) }}
            block
          >
            打开 AI 供应商配置
          </Button>
        </div>
      ),
    },
    {
      key: 'motivation',
      label: <span><SmileOutlined /> 激励语录</span>,
      children: <MotivationSettings />,
    },
    {
      key: 'prompts',
      label: <span><FileTextOutlined /> 提示词</span>,
      children: (
        <div style={{ padding: '8px 0' }}>
          <div style={{ marginBottom: 16, color: 'var(--text-secondary)', fontSize: 13 }}>
            管理自定义提示词模板
          </div>
          <Button
            type="default"
            icon={<FileTextOutlined />}
            onClick={() => { onClose(); navigate('/prompts') }}
            block
          >
            打开提示词管理
          </Button>
        </div>
      ),
    },
    {
      key: 'system',
      label: <span><SettingOutlined /> 系统</span>,
      children: <SystemSettings />,
    },
  ]

  return (
    <>
      <Modal
        open={open}
        onCancel={onClose}
        footer={null}
        title={<span><SettingOutlined style={{ marginRight: 8 }} />设置</span>}
        width={520}
        styles={{ body: { padding: '8px 0 0' } }}
      >
        <Tabs
          items={tabs}
          size="small"
          tabPosition="left"
          style={{ minHeight: 320 }}
        />
      </Modal>
      <AISettingsDrawer open={aiDrawerOpen} onClose={() => setAiDrawerOpen(false)} />
    </>
  )
}

function SystemSettings() {
  const compactUpdateNotes = (notes?: string | null) => {
    const text = (notes || '').trim()
    if (!text) return ''
    if (text.includes('APP_UPDATE_MANIFEST_URL')) return '未配置更新源'
    return text.split('\n')[0].trim().slice(0, 80)
  }

  const parseIntWithDefault = (value: string | null, fallback: number) => {
    const parsed = Number.parseInt(value ?? '', 10)
    return Number.isNaN(parsed) ? fallback : parsed
  }

  const [notifEnabled, setNotifEnabled] = useState(() => {
    return localStorage.getItem('sys_notif') !== 'false'
  })
  const [lang, setLang] = useState(() => localStorage.getItem('sys_lang') || 'zh')
  const [autoSave, setAutoSave] = useState(() => localStorage.getItem('sys_autosave') !== 'false')
  const [compactMode, setCompactMode] = useState(() => localStorage.getItem('sys_compact') === 'true')
  const [currentVersion, setCurrentVersion] = useState('1.0.0')
  const [updateInfo, setUpdateInfo] = useState<SystemUpdateInfo | null>(null)
  const [checkingUpdate, setCheckingUpdate] = useState(false)
  const [desktopUpdateState, setDesktopUpdateState] = useState<DesktopUpdateState | null>(null)
  const desktopUpdaterAvailable = isDesktopUpdaterAvailable()
  const [autoCheckUpdate, setAutoCheckUpdate] = useState(() => {
    return localStorage.getItem('sys_update_auto_check') !== 'false'
  })
  const [updateCheckIntervalMin, setUpdateCheckIntervalMin] = useState(() => {
    return parseIntWithDefault(localStorage.getItem('sys_update_interval_min'), 360)
  })
  const [interventionEnabled, setInterventionEnabled] = useState(() =>
    localStorage.getItem('intervention_enabled') !== 'false'
  )
  const [interventionInterval, setInterventionInterval] = useState(() =>
    parseIntWithDefault(localStorage.getItem('intervention_interval_min'), 30)
  )

  const loadVersion = async () => {
    try {
      const version = await getSystemVersion()
      setCurrentVersion(version.current_version)
    } catch {
      // Version is non-critical in settings; manual update checks surface errors.
    }
  }

  const checkUpdate = async (showToast: boolean) => {
    setCheckingUpdate(true)
    try {
      let desktopState: DesktopUpdateState | null = null
      let systemResult: SystemUpdateInfo | null = null
      let systemError: unknown = null

      if (desktopUpdaterAvailable) {
        try {
          desktopState = await checkForDesktopUpdate()
          setDesktopUpdateState(desktopState)
        } catch {
          desktopState = await getDesktopUpdateState().catch(() => null)
          if (desktopState) {
            setDesktopUpdateState(desktopState)
          }
        }
      }

      try {
        systemResult = await checkSystemUpdate()
        setUpdateInfo(systemResult)
        localStorage.setItem('sys_update_last', JSON.stringify(systemResult))
        if (systemResult.latest_version) {
          localStorage.setItem('sys_update_last_latest_version', systemResult.latest_version)
        }
      } catch (error) {
        systemError = error
      }

      if (systemError && !desktopState) {
        throw systemError
      }

      if (!showToast) {
        return
      }
      if (hasDownloadableUpdate(systemResult, desktopState)) {
        const version = getDisplayedLatestVersion(systemResult, desktopState)
        message.success(version ? `发现新版本 v${version}` : '发现新版本')
      } else if (systemError) {
        message.warning(getApiErrorMessage(systemError, '版本说明获取失败，但桌面更新检查已完成'))
      } else {
        message.info('当前已是最新版本')
      }
    } catch (error) {
      if (showToast) {
        message.error(getApiErrorMessage(error, '检查更新失败，请稍后再试'))
      }
    } finally {
      setCheckingUpdate(false)
    }
  }

  const handleOpenUpdateLink = async () => {
    if (desktopUpdaterAvailable && isDesktopUpdateAvailable(desktopUpdateState)) {
      try {
        const nextState = await downloadDesktopUpdate()
        setDesktopUpdateState(nextState)
        message.success('开始下载更新')
        return
      } catch (error) {
        message.error(getApiErrorMessage(error, '下载更新失败，请稍后再试'))
        return
      }
    }

    const url = updateInfo?.download_url || updateInfo?.release_page
    if (!url) {
      message.warning('当前版本暂无可用下载链接')
      return
    }
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  useEffect(() => {
    void loadVersion()

    const cachedUpdateInfo = localStorage.getItem('sys_update_last')
    if (cachedUpdateInfo) {
      try {
        const parsed = JSON.parse(cachedUpdateInfo) as SystemUpdateInfo
        setUpdateInfo(parsed)
      } catch {
        localStorage.removeItem('sys_update_last')
      }
    }

    if (!desktopUpdaterAvailable) {
      return
    }

    void getDesktopUpdateSettings()
      .then((settings) => {
        setAutoCheckUpdate(settings.autoCheck)
        setUpdateCheckIntervalMin(settings.intervalMinutes)
      })
      .catch(() => {
        // keep local defaults when desktop settings are unavailable
      })

    void getDesktopUpdateState()
      .then(setDesktopUpdateState)
      .catch(() => {
        // ignore initial desktop updater state failures
      })

    const unsubscribe = subscribeDesktopUpdateState((state) => {
      setDesktopUpdateState(state)
    })
    return () => {
      unsubscribe?.()
    }
  }, [desktopUpdaterAvailable])

  const handleQuitAndInstall = async () => {
    try {
      await quitAndInstallDesktopUpdate()
    } catch (error) {
      message.error(getApiErrorMessage(error, '安装更新失败，请稍后再试'))
    }
  }

  const save = () => {
    localStorage.setItem('sys_notif', String(notifEnabled))
    localStorage.setItem('sys_lang', lang)
    localStorage.setItem('sys_autosave', String(autoSave))
    localStorage.setItem('sys_compact', String(compactMode))
    localStorage.setItem('sys_update_auto_check', String(autoCheckUpdate))
    localStorage.setItem('sys_update_interval_min', String(updateCheckIntervalMin))
    localStorage.setItem('intervention_enabled', String(interventionEnabled))
    localStorage.setItem('intervention_interval_min', String(interventionInterval))
    window.dispatchEvent(new StorageEvent('storage', { key: 'sys_update_auto_check', newValue: String(autoCheckUpdate) }))
    window.dispatchEvent(new StorageEvent('storage', { key: 'sys_update_interval_min', newValue: String(updateCheckIntervalMin) }))
    window.dispatchEvent(new StorageEvent('storage', { key: 'intervention_enabled', newValue: String(interventionEnabled) }))
    window.dispatchEvent(new StorageEvent('storage', { key: 'intervention_interval_min', newValue: String(interventionInterval) }))

    if (desktopUpdaterAvailable) {
      void setDesktopUpdateSettings({
        autoCheck: autoCheckUpdate,
        intervalMinutes: updateCheckIntervalMin,
      })
    }
    message.success('系统设置已保存')
  }

  const displayedLatestVersion = getDisplayedLatestVersion(updateInfo, desktopUpdateState)
  const displayedReleaseNotes = getDisplayedReleaseNotes(updateInfo, desktopUpdateState)
  const canDownloadUpdate = hasDownloadableUpdate(updateInfo, desktopUpdateState)

  const row = (label: string, desc: string, control: React.ReactNode) => (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 0', borderBottom: '1px solid var(--border-light)' }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>{label}</div>
        <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>{desc}</div>
      </div>
      {control}
    </div>
  )

  return (
    <div style={{ padding: '8px 0' }}>
      {row('桌面通知', '番茄钟完成时发送系统通知',
        <Switch size="small" checked={notifEnabled} onChange={setNotifEnabled} />
      )}
      {row('自动保存', '编辑内容时自动保存草稿',
        <Switch size="small" checked={autoSave} onChange={setAutoSave} />
      )}
      {row('紧凑模式', '减小间距，显示更多内容',
        <Switch size="small" checked={compactMode} onChange={setCompactMode} />
      )}
      {row('界面语言', '切换显示语言（重启生效）',
        <Select size="small" value={lang} onChange={setLang} style={{ width: 100 }}
          options={[{ value: 'zh', label: '中文' }, { value: 'en', label: 'English' }]}
        />
      )}
      <Divider style={{ margin: '12px 0' }} />
      <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)', marginBottom: 10 }}>应用更新</div>
      {row('自动检查更新', '启动后按间隔自动检查新版本',
        <Switch size="small" checked={autoCheckUpdate} onChange={setAutoCheckUpdate} />
      )}
      {autoCheckUpdate && row('检查间隔', '自动检查周期（分钟）',
        <InputNumber
          size="small"
          min={5}
          max={1440}
          value={updateCheckIntervalMin}
          onChange={v => setUpdateCheckIntervalMin(v ?? 360)}
          addonAfter="分钟"
          style={{ width: 120 }}
        />
      )}
      <div style={{ marginTop: 10 }}>
        <Space wrap>
          <Button size="small" loading={checkingUpdate} onClick={() => void checkUpdate(true)}>
            手动检查更新
          </Button>
          {canDownloadUpdate && (
            <Button type="primary" size="small" onClick={handleOpenUpdateLink}>
              {isDesktopUpdateAvailable(desktopUpdateState) ? '下载并安装更新' : '下载更新'}
            </Button>
          )}
          {desktopUpdaterAvailable && desktopUpdateState?.phase === 'downloaded' && (
            <Button type="primary" size="small" onClick={() => void handleQuitAndInstall()}>
              重启并安装
            </Button>
          )}
        </Space>
      </div>
      <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-tertiary)' }}>
        {updateInfo?.checked_at
          ? `上次检查：${new Date(updateInfo.checked_at).toLocaleString()}`
          : '上次检查：尚未执行'}
      </div>
      {!!displayedLatestVersion && (
        <div style={{ marginTop: 2, fontSize: 12, color: 'var(--text-tertiary)' }}>
          最新版本：v{displayedLatestVersion}
        </div>
      )}
      {!!compactUpdateNotes(displayedReleaseNotes) && (
        <div style={{ marginTop: 2, fontSize: 12, color: 'var(--text-tertiary)' }}>
          更新说明：{compactUpdateNotes(displayedReleaseNotes)}
        </div>
      )}
      {desktopUpdaterAvailable && !!desktopUpdateState?.message && (
        <div style={{ marginTop: 2, fontSize: 12, color: 'var(--text-tertiary)' }}>
          桌面更新状态：{desktopUpdateState.message}
          {desktopUpdateState.phase === 'downloading' && typeof desktopUpdateState.progressPercent === 'number'
            ? `（${desktopUpdateState.progressPercent}%）`
            : ''}
        </div>
      )}
      <Divider style={{ margin: '12px 0' }} />
      <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)', marginBottom: 10 }}>AI 学习教练提醒</div>
      {row('主动提醒', '学习状态异常时自动弹出建议',
        <Switch size="small" checked={interventionEnabled} onChange={setInterventionEnabled} />
      )}
      {interventionEnabled && row('提醒间隔', '每隔多少分钟检查一次学习状态（默认30分钟）',
        <InputNumber
          size="small"
          min={5} max={240}
          value={interventionInterval}
          onChange={v => setInterventionInterval(v ?? 30)}
          addonAfter="分钟"
          style={{ width: 110 }}
        />
      )}
      <Divider style={{ margin: '12px 0' }} />
      <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginBottom: 8 }}>
        版本：Mnemox v{currentVersion} · 数据存储于本地
      </div>
      <Button type="primary" size="small" onClick={save}>保存设置</Button>
    </div>
  )
}

function MotivationSettings() {
  const [loading, setLoading] = useState(false)

  const handleGenerate = async () => {
    setLoading(true)
    try {
      await generateAIQuote()
      message.success('已生成新的激励语录')
    } catch (error) {
      showApiError(error, '生成失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ padding: '8px 0' }}>
      <div style={{ marginBottom: 16, color: 'var(--text-secondary)', fontSize: 13 }}>
        管理右侧栏的激励语录
      </div>
      <Button
        type="default"
        loading={loading}
        onClick={handleGenerate}
        block
        style={{ marginBottom: 8 }}
      >
        ✨ AI 生成激励语录
      </Button>
      <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
        生成后将自动显示在右侧栏「今日激励」中
      </div>
    </div>
  )
}
