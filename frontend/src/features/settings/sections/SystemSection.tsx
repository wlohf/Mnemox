import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, RefreshCw, RotateCw } from 'lucide-react'
import { Badge, Button, Input, KeyValue, Notice, SwitchField, toast } from '../../../ui'
import { checkSystemUpdate, getSystemVersion, type SystemUpdateInfo } from '../../../services/systemApi'
import {
  checkForDesktopUpdate,
  downloadDesktopUpdate,
  getDesktopUpdateState,
  isDesktopUpdaterAvailable,
  quitAndInstallDesktopUpdate,
  setDesktopUpdateSettings,
  subscribeDesktopUpdateState,
  type DesktopUpdateState,
} from '../../../services/desktopUpdater'
import {
  getDisplayedLatestVersion,
  getDisplayedReleaseNotes,
  getUpdateOpenUrl,
  hasDownloadableUpdate,
} from '../../../services/updateDisplay'
import { getApiErrorMessage } from '../../../services/apiClient'
import { Group, Row, Rows, settingsStyles as s } from '../SettingsDialog'

const LAST_KEY = 'sys_update_last'

function readLast(): SystemUpdateInfo | null {
  try {
    const raw = localStorage.getItem(LAST_KEY)
    return raw ? (JSON.parse(raw) as SystemUpdateInfo) : null
  } catch {
    return null
  }
}

export function SystemSection() {
  const version = useQuery({ queryKey: ['system', 'version'], queryFn: getSystemVersion, staleTime: Infinity })
  const desktop = isDesktopUpdaterAvailable()
  const [info, setInfo] = useState<SystemUpdateInfo | null>(readLast)
  const [desk, setDesk] = useState<DesktopUpdateState | null>(null)
  const [checking, setChecking] = useState(false)
  const [autoCheck, setAutoCheck] = useState(() => localStorage.getItem('sys_update_auto_check') !== 'false')
  const [interval, setIntervalMin] = useState(() => localStorage.getItem('sys_update_interval_min') || '360')
  const [notif, setNotif] = useState(() => localStorage.getItem('sys_notif') !== 'false')

  useEffect(() => {
    if (!desktop) return
    void getDesktopUpdateState().then(setDesk).catch(() => undefined)
    const off = subscribeDesktopUpdateState(setDesk)
    return () => off?.()
  }, [desktop])

  const check = async () => {
    setChecking(true)
    try {
      const [sys, d] = await Promise.all([checkSystemUpdate(), desktop ? checkForDesktopUpdate().catch(() => null) : Promise.resolve(null)])
      setInfo(sys)
      if (d) setDesk(d)
      localStorage.setItem(LAST_KEY, JSON.stringify(sys))
      if (!hasDownloadableUpdate(sys, d)) toast.success('已经是最新版本')
    } catch (e) {
      toast.error(getApiErrorMessage(e, '检查更新失败'))
    } finally {
      setChecking(false)
    }
  }

  const saveUpdatePrefs = async () => {
    const minutes = String(Math.max(5, Math.min(1440, Number(interval) || 360)))
    localStorage.setItem('sys_update_auto_check', String(autoCheck))
    localStorage.setItem('sys_update_interval_min', minutes)
    localStorage.setItem('sys_notif', String(notif))
    window.dispatchEvent(new StorageEvent('storage', { key: 'sys_update_auto_check', newValue: String(autoCheck) }))
    if (desktop) await setDesktopUpdateSettings({ autoCheck, intervalMinutes: Number(minutes) }).catch(() => undefined)
    if (notif && 'Notification' in window && Notification.permission === 'default') void Notification.requestPermission()
    toast.success('已保存')
  }

  const latest = getDisplayedLatestVersion(info, desk)
  const notes = getDisplayedReleaseNotes(info, desk)
  const canDownload = hasDownloadableUpdate(info, desk)
  const openUrl = getUpdateOpenUrl(info)

  return (
    <>
      <Group title="版本">
        <Rows>
          <Row label={`Mnemox v${version.data?.current_version ?? '…'}`} hint="学习数据保存在你自己的设备与服务里。">
            <Button size="sm" icon={<RefreshCw />} loading={checking} onClick={() => void check()}>
              检查更新
            </Button>
          </Row>
        </Rows>
        {canDownload && (
          <Notice tone="ink" title={`有新版本 v${latest}`} className={s.testResult} role="status" actions={
            desk?.phase === 'downloaded' ? (
              <Button size="sm" variant="primary" icon={<RotateCw />} onClick={() => void quitAndInstallDesktopUpdate()}>
                重启并安装
              </Button>
            ) : desktop ? (
              <Button
                size="sm"
                variant="primary"
                icon={<Download />}
                loading={desk?.phase === 'downloading'}
                onClick={() => void downloadDesktopUpdate().then(setDesk).catch(e => toast.error(getApiErrorMessage(e, '下载失败')))}
              >
                {desk?.phase === 'downloading' ? `下载中 ${Math.round(desk.progressPercent ?? 0)}%` : '下载并安装'}
              </Button>
            ) : openUrl ? (
              <Button size="sm" variant="primary" icon={<Download />} onClick={() => window.open(openUrl, '_blank', 'noopener')}>
                {info?.download_url ? '下载更新' : '查看更新'}
              </Button>
            ) : undefined
          }>
            {notes ? notes.split('\n')[0].slice(0, 120) : '更新说明未提供。'}
          </Notice>
        )}
        {info && (
          <div style={{ marginTop: 12 }}>
            <KeyValue
              items={[
                ['上次检查', new Date(info.checked_at).toLocaleString('zh-CN', { hour12: false })],
                ['最新版本', latest ? <Badge tone={canDownload ? 'ink' : 'success'}>v{latest}</Badge> : '未配置更新源'],
                ...(desk ? ([['桌面更新', desk.message || desk.phase]] as Array<[string, string]>) : []),
              ]}
            />
          </div>
        )}
      </Group>

      <Group title="自动检查与通知">
        <Rows>
          <div className={s.row}>
            <div style={{ flex: 1 }} className={s.stack}>
              <SwitchField label="自动检查更新" checked={autoCheck} onCheckedChange={setAutoCheck} />
              <SwitchField label="发现新版本时发送系统通知" description="需要浏览器或系统授予通知权限。" checked={notif} onCheckedChange={setNotif} />
            </div>
          </div>
          <Row label="检查间隔" htmlFor="sys-int" hint="5 分钟到 24 小时">
            <div style={{ width: 150 }}>
              <Input id="sys-int" type="number" min={5} max={1440} value={interval} disabled={!autoCheck} onChange={e => setIntervalMin(e.target.value)} suffix="分钟" />
            </div>
          </Row>
        </Rows>
        <div className={s.actions} style={{ marginTop: 12 }}>
          <Button variant="primary" size="sm" onClick={() => void saveUpdatePrefs()}>
            保存
          </Button>
        </div>
      </Group>
    </>
  )
}
