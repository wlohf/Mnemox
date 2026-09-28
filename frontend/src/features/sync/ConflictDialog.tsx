import { useState } from 'react'
import { useLiveQuery } from 'dexie-react-hooks'
import { Cloud, Laptop } from 'lucide-react'
import { Badge, Button, Dialog, Empty, Notice, toast } from '../../ui'
import { db as activeDb, type ModuleName } from '../../db/studyDb'
import { syncEngine } from '../../sync/SyncEngine'
import { useShell } from '../../app/shell/shellStore'
import s from './conflict.module.css'

type SyncConflict = Record<string, unknown> & {
  _localId: string
  _conflictAt: string | null
  _conflictServerData: string | null
  _conflictOpType?: string
}

interface ConflictEntry {
  module: ModuleName
  item: SyncConflict
  server: Record<string, unknown> | null
}

const asText = (v: unknown, fallback = '') => (typeof v === 'string' && v.trim() ? v.trim() : fallback)

const MODULE_META: Record<ModuleName, { label: string; title: (item: SyncConflict) => string }> = {
  notes: { label: '笔记', title: i => asText(i.title, '未命名笔记') },
  goals: { label: '目标', title: i => asText(i.title, '未命名目标') },
  goalTasks: { label: '任务', title: i => asText(i.title, '未命名任务') },
  ankiCards: { label: '记忆卡', title: i => asText(i.front, '未命名记忆卡') },
  wrongQuestions: { label: '错题', title: i => asText(i.content, '未命名错题') },
}

function parseServer(value: string | null): Record<string, unknown> | null {
  if (!value) return null
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null
  } catch {
    return null
  }
}

function preview(item: Record<string, unknown>, module: ModuleName): string {
  const primary = module === 'ankiCards' ? asText(item.front) : module === 'wrongQuestions' ? asText(item.content) : asText(item.title)
  const body =
    module === 'notes' ? asText(item.content) : module === 'ankiCards' ? asText(item.back) : asText(item.description ?? item.explanation)
  return [primary, body].filter(Boolean).join('：') || '无可预览内容'
}

function when(value: string | null): string {
  if (!value) return '刚刚'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '刚刚' : d.toLocaleString('zh-CN', { hour12: false })
}

export function ConflictDialog() {
  const open = useShell(st => st.conflictsOpen)
  const setOpen = useShell(st => st.setConflictsOpen)
  const db = activeDb
  const conflicts =
    useLiveQuery(async (): Promise<ConflictEntry[]> => {
      const modules = Object.keys(MODULE_META) as ModuleName[]
      const rows = await Promise.all(
        modules.map(async module => {
          const list = (await db.table(module).toArray()) as SyncConflict[]
          return list
            .filter(r => r._syncStatus === 'conflicted')
            .map(r => ({ module, item: r, server: parseServer(r._conflictServerData) }))
        }),
      )
      return rows.flat()
    }, [db]) ?? []
  const [busy, setBusy] = useState<string | null>(null)

  const resolve = async (module: ModuleName, localId: string, strategy: 'keep_local' | 'use_server') => {
    const key = `${module}:${localId}:${strategy}`
    setBusy(key)
    try {
      await syncEngine.resolveConflict(module, localId, strategy)
      toast.success(strategy === 'keep_local' ? '已保留本机版本，正在同步' : '已采用云端版本')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '冲突处理失败，请重试')
    } finally {
      setBusy(null)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      width={46}
      title={`处理同步冲突${conflicts.length ? `（${conflicts.length}）` : ''}`}
      description="同一条内容在本机离线期间和云端都被修改过。系统没有自动覆盖任何一边，请逐条决定保留哪个版本。"
    >
      {conflicts.length === 0 ? (
        <Empty icon={<Cloud />} title="没有待处理的同步冲突" body="本机和云端已经一致。" />
      ) : (
        <>
          <Notice tone="warning" className={s.notice}>
            采用云端版本会丢弃这条内容在本机的未同步修改。
          </Notice>
          <ul className={s.list} role="list">
            {conflicts.map(({ module, item, server }) => {
              const meta = MODULE_META[module]
              const key = `${module}:${item._localId}`
              const localDelete = item._conflictOpType === 'delete'
              return (
                <li key={key} className={s.item}>
                  <div className={s.head}>
                    <Badge tone="evidence">{meta.label}</Badge>
                    <span className={s.title}>{meta.title(item)}</span>
                    <span className={s.when}>发现于 {when(item._conflictAt)}</span>
                  </div>
                  <div className={s.compare}>
                    <div className={s.side}>
                      <span className={s.sideLabel}>
                        <Laptop aria-hidden />
                        {localDelete ? '本机操作：删除这条记录' : '本机未同步版本'}
                      </span>
                      <p className={s.sideBody}>{preview(item, module)}</p>
                    </div>
                    <div className={s.side}>
                      <span className={s.sideLabel}>
                        <Cloud aria-hidden />
                        云端版本
                      </span>
                      <p className={s.sideBody}>
                        {server?.__deleted
                          ? '云端已删除这条记录'
                          : server
                            ? preview(server, module)
                            : '云端摘要暂不可用，请先重试同步再处理。'}
                      </p>
                    </div>
                  </div>
                  <div className={s.actions}>
                    <Button
                      variant="primary"
                      size="sm"
                      loading={busy === `${key}:keep_local`}
                      disabled={busy !== null && busy !== `${key}:keep_local`}
                      onClick={() => void resolve(module, item._localId, 'keep_local')}
                    >
                      {localDelete ? '继续删除云端记录' : server?.__deleted ? '用本机内容重新创建' : '保留本机并同步'}
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      loading={busy === `${key}:use_server`}
                      disabled={busy !== null && busy !== `${key}:use_server`}
                      onClick={() => void resolve(module, item._localId, 'use_server')}
                    >
                      采用云端版本
                    </Button>
                  </div>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </Dialog>
  )
}
