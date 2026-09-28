import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Checkbox, Field, Input, Notice, Select, Skeleton, SwitchField, toast } from '../../../ui'
import { getCoachPreferences, updateCoachPreferences, type CoachPreferences } from '../../../services/coachApi'
import { isDesktopCoachNotificationAvailable } from '../../../services/desktopCoach'
import { qk } from '../../../app/queryClient'
import { Group, Row, Rows, settingsStyles as s } from '../SettingsDialog'

const CHANNELS = [
  { value: 'chat_inline', label: '对话里' },
  { value: 'in_app_nudge', label: '应用内提醒' },
  { value: 'agent_panel', label: '「今天」页面' },
  { value: 'desktop_notification', label: '桌面通知' },
]

function deviceZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

export function CoachSection() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: qk.coachPreferences, queryFn: getCoachPreferences })
  const [draft, setDraft] = useState<Partial<CoachPreferences>>({})
  const [saving, setSaving] = useState(false)
  const [reminder, setReminder] = useState(() => localStorage.getItem('intervention_enabled') !== 'false')
  const [interval, setIntervalMin] = useState(() => localStorage.getItem('intervention_interval_min') || '30')
  const desktop = isDesktopCoachNotificationAvailable()

  useEffect(() => setDraft({}), [q.data])
  if (q.isLoading) return <Skeleton height={320} radius={12} />
  if (!q.data) return <Notice tone="danger">没能读取教练设置，请确认本地服务已启动。</Notice>
  const p: CoachPreferences = { ...q.data, ...draft }
  const set = (patch: Partial<CoachPreferences>) => setDraft(d => ({ ...d, ...patch }))
  const zones = Array.from(new Set([deviceZone(), 'Asia/Shanghai', 'UTC', 'Asia/Tokyo', 'Europe/London', 'America/New_York', 'America/Los_Angeles']))

  const save = async () => {
    setSaving(true)
    try {
      if (Object.keys(draft).length > 0) {
        const next = await updateCoachPreferences(draft)
        if (!next) throw new Error('教练设置保存失败')
      }
      const minutes = String(Math.max(5, Math.min(240, Number(interval) || 30)))
      localStorage.setItem('intervention_enabled', String(reminder))
      localStorage.setItem('intervention_interval_min', minutes)
      localStorage.setItem('coach_preferences_updated', String(Date.now()))
      window.dispatchEvent(new StorageEvent('storage', { key: 'coach_preferences_updated' }))
      window.dispatchEvent(new StorageEvent('storage', { key: 'intervention_interval_min', newValue: minutes }))
      await qc.invalidateQueries({ queryKey: qk.coachPreferences })
      toast.success('教练设置已保存')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const toggleChannel = (value: string, on: boolean) => {
    const cur = new Set(p.allowed_channels ?? [])
    if (on) cur.add(value)
    else cur.delete(value)
    set({ allowed_channels: Array.from(cur) })
  }

  return (
    <>
      <Group title="主动提醒">
        <Rows>
          <div className={s.row}>
            <div style={{ flex: 1 }} className={s.stack}>
              <SwitchField label="启用教练" description="关闭后教练只在你提问时回应，不会主动提醒。" checked={p.enabled} onCheckedChange={v => set({ enabled: v })} />
              <SwitchField
                label="允许主动找我"
                description="比如复习积压、专注中断之后，给一个最小的下一步。"
                checked={p.proactive_enabled}
                disabled={!p.enabled}
                onCheckedChange={v => set({ proactive_enabled: v })}
              />
              <SwitchField
                label="桌面通知"
                description={desktop ? '应用在后台时也能收到提醒。' : '仅在 Mnemox 桌面版中可用。'}
                checked={p.desktop_notifications_enabled}
                disabled={!desktop || !p.enabled}
                onCheckedChange={v =>
                  set({
                    desktop_notifications_enabled: v,
                    ...(v
                      ? {
                          proactive_enabled: true,
                          allowed_channels: Array.from(new Set([...(p.allowed_channels ?? []), 'desktop_notification'])),
                        }
                      : {}),
                  })
                }
              />
            </div>
          </div>
          <Row label="提醒出现的位置">
            <div className={s.actions}>
              {CHANNELS.map(c => (
                <Checkbox
                  key={c.value}
                  label={c.label}
                  checked={(p.allowed_channels ?? []).includes(c.value)}
                  disabled={c.value === 'desktop_notification' && !desktop}
                  onCheckedChange={v => toggleChannel(c.value, v)}
                />
              ))}
            </div>
          </Row>
        </Rows>
      </Group>

      <Group title="打扰程度" desc="教练宁可少说一句，也不想变成另一个通知收件箱。">
        <Rows>
          <div className={s.row}>
            <div className={s.grid2} style={{ flex: 1 }}>
              <Field label="每天最多提醒" htmlFor="c-max">
                <Input
                  id="c-max"
                  type="number"
                  min={1}
                  max={10}
                  value={p.max_nudges_per_day}
                  onChange={e => set({ max_nudges_per_day: Math.max(1, Math.min(10, Number(e.target.value) || 1)) })}
                  suffix="次"
                />
              </Field>
              <Field label="两次提醒至少间隔" htmlFor="c-gap">
                <Input
                  id="c-gap"
                  type="number"
                  min={0}
                  max={1440}
                  value={p.min_minutes_between_nudges}
                  onChange={e => set({ min_minutes_between_nudges: Math.max(0, Math.min(1440, Number(e.target.value) || 0)) })}
                  suffix="分钟"
                />
              </Field>
              <Field label="免打扰开始" htmlFor="c-qs">
                <Input id="c-qs" type="time" step={900} value={p.quiet_hours_start ?? ''} onChange={e => set({ quiet_hours_start: e.target.value || null })} />
              </Field>
              <Field label="免打扰结束" htmlFor="c-qe">
                <Input id="c-qe" type="time" step={900} value={p.quiet_hours_end ?? ''} onChange={e => set({ quiet_hours_end: e.target.value || null })} />
              </Field>
              <Field label="时区">
                <Select
                  ariaLabel="时区"
                  value={p.time_zone}
                  onValueChange={v => set({ time_zone: v })}
                  options={zones.map(z => ({ value: z, label: z === deviceZone() ? `${z}（本机）` : z }))}
                />
              </Field>
            </div>
          </div>
        </Rows>
      </Group>

      <Group title="每日状态提醒" desc="根据今天的学习时长、待办积压和到期复习，必要时在应用里提醒一次。">
        <Rows>
          <div className={s.row}>
            <div style={{ flex: 1 }}>
              <SwitchField label="页面内提醒" checked={reminder} onCheckedChange={setReminder} />
            </div>
          </div>
          <Row label="检查间隔" htmlFor="c-int">
            <div style={{ width: 140 }}>
              <Input id="c-int" type="number" min={5} max={240} value={interval} onChange={e => setIntervalMin(e.target.value)} suffix="分钟" />
            </div>
          </Row>
        </Rows>
      </Group>

      <div className={s.actions} style={{ marginTop: 20 }}>
        <Button variant="primary" loading={saving} onClick={() => void save()}>
          保存教练设置
        </Button>
      </div>
    </>
  )
}
