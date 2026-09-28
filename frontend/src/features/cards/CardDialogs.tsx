import { useEffect, useState } from 'react'
import { Download, FileUp, Sparkles } from 'lucide-react'
import { Button, Dialog, Field, Input, Notice, Textarea, toast } from '../../ui'
import {
  aiGenerateAnkiCards,
  createAnkiCard,
  exportAnkiCardsCSV,
  importAnkiCardsCSV,
  updateAnkiCard,
  type AnkiCardItem,
} from '../../services/ankiApi'
import { getApiErrorMessage } from '../../services/apiClient'
import { csvLooksValid, joinTags, tagsOf } from './cardModel'
import s from './cards.module.css'

/* ============================================================================
   Write / edit a card
   ========================================================================== */
export function CardDialog({
  open,
  onOpenChange,
  card,
  onSaved,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  card?: AnkiCardItem | null
  onSaved: (card: AnkiCardItem, created: boolean) => void
}) {
  const editing = Boolean(card)
  const [front, setFront] = useState('')
  const [back, setBack] = useState('')
  const [tags, setTags] = useState('')
  const [note, setNote] = useState('')
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setFront(card?.front ?? '')
    setBack(card?.back ?? '')
    setTags(card ? tagsOf(card).join('，') : '')
    setNote(card?.note ?? '')
    setTouched(false)
  }, [open, card])

  const frontBad = touched && !front.trim()
  const backBad = touched && !back.trim()

  const submit = async (again: boolean) => {
    setTouched(true)
    if (!front.trim() || !back.trim()) return
    setBusy(true)
    try {
      const payload = {
        front: front.trim(),
        back: back.trim(),
        tags: joinTags(tags.split(/[,，\s]+/)) || undefined,
        note: note.trim() || undefined,
      }
      if (card) {
        const saved = await updateAnkiCard(card.id, payload)
        onSaved(saved, false)
        toast.success('卡片已保存')
        onOpenChange(false)
      } else {
        const saved = await createAnkiCard(payload)
        if (!saved) throw new Error('没能创建卡片')
        onSaved(saved, true)
        toast.success('已加入卡组', { description: '今天就会出现在复习里。' })
        if (again) {
          setFront('')
          setBack('')
          setNote('')
          setTouched(false)
          requestAnimationFrame(() => document.getElementById('card-front')?.focus())
        } else {
          onOpenChange(false)
        }
      }
    } catch (error) {
      toast.error(getApiErrorMessage(error, '保存失败'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={editing ? '编辑卡片' : '写一张卡'}
      description={editing ? undefined : '正面写一个能回答的问题，背面写最简的答案。一张卡只考一件事。'}
      width={34}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          {!editing && (
            <Button variant="secondary" loading={busy} onClick={() => void submit(true)}>
              保存并再写一张
            </Button>
          )}
          <Button variant="primary" loading={busy} onClick={() => void submit(false)}>
            保存
          </Button>
        </>
      }
    >
      <div className={s.form}>
        <Field label="正面：问题" htmlFor="card-front" error={frontBad ? '正面不能为空' : undefined}>
          <Textarea
            id="card-front"
            autoFocus
            reading
            autoGrow
            rows={2}
            maxHeight={180}
            invalid={frontBad}
            value={front}
            placeholder="例如：费曼复盘里“讲不顺”代表什么？"
            onChange={e => setFront(e.target.value)}
          />
        </Field>
        <Field label="背面：答案" htmlFor="card-back" error={backBad ? '背面不能为空' : undefined}>
          <Textarea
            id="card-back"
            reading
            autoGrow
            rows={3}
            maxHeight={240}
            invalid={backBad}
            value={back}
            placeholder="例如：理解结构里还有缺口，明天从这里补。"
            onChange={e => setBack(e.target.value)}
          />
        </Field>
        <Field label="标签" htmlFor="card-tags" optional hint="用逗号分隔，复习时可以按标签筛选。">
          <Input id="card-tags" value={tags} placeholder="例如：费曼，学习方法" onChange={e => setTags(e.target.value)} />
        </Field>
        <Field label="补充说明" htmlFor="card-note" optional>
          <Input id="card-note" value={note} placeholder="出处、例子或记忆线索" onChange={e => setNote(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  )
}

/* ============================================================================
   Generate cards with AI from a topic and optional source text
   ========================================================================== */
export function GenerateDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onCreated: (cards: AnkiCardItem[]) => void
}) {
  const [topic, setTopic] = useState('')
  const [source, setSource] = useState('')
  const [count, setCount] = useState('5')
  const [tags, setTags] = useState('')
  const [busy, setBusy] = useState(false)
  const [made, setMade] = useState<AnkiCardItem[] | null>(null)
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    if (!open) return
    setTopic('')
    setSource('')
    setCount('5')
    setTags('')
    setMade(null)
    setTouched(false)
  }, [open])

  const n = Number(count)
  const countBad = !Number.isInteger(n) || n < 1 || n > 20
  const topicBad = touched && !topic.trim()

  const submit = async () => {
    setTouched(true)
    if (!topic.trim() || countBad) return
    setBusy(true)
    try {
      const r = await aiGenerateAnkiCards({
        topic: topic.trim(),
        source_text: source.trim() || undefined,
        count: n,
        tags: joinTags(tags.split(/[,，\s]+/)) || undefined,
      })
      if (!r) throw new Error('AI 没能生成卡片，检查一下设置里的 AI 模型')
      setMade(r.cards)
      onCreated(r.cards)
      toast.success(`已生成 ${r.created} 张卡`)
    } catch (error) {
      toast.error(getApiErrorMessage(error, '生成失败'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={v => !busy && onOpenChange(v)}
      title={made ? `生成了 ${made.length} 张卡` : '用 AI 出卡'}
      description={made ? '它们已经加入卡组。不满意的可以在卡组里直接编辑或删除。' : '给一个主题，最好再贴一段原文。AI 会按“一张卡只考一件事”的原则出卡。'}
      width={36}
      footer={
        made ? (
          <Button variant="primary" onClick={() => onOpenChange(false)}>
            好
          </Button>
        ) : (
          <>
            <Button variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>
              取消
            </Button>
            <Button variant="primary" icon={<Sparkles />} loading={busy} disabled={countBad} onClick={() => void submit()}>
              生成
            </Button>
          </>
        )
      }
    >
      {made ? (
        <ul className={s.preview}>
          {made.map(c => (
            <li key={c.id}>
              <b>{c.front}</b>
              <span>{c.back}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className={s.form}>
          <div className={s.formRow}>
            <Field label="主题" htmlFor="gen-topic" error={topicBad ? '写一个主题' : undefined}>
              <Input id="gen-topic" autoFocus value={topic} invalid={topicBad} placeholder="例如：间隔复习的原理" onChange={e => setTopic(e.target.value)} />
            </Field>
            <Field label="张数" htmlFor="gen-count" error={countBad ? '1–20' : undefined}>
              <Input id="gen-count" type="number" inputMode="numeric" min={1} max={20} value={count} invalid={countBad} onChange={e => setCount(e.target.value)} />
            </Field>
          </div>
          <Field label="原文" htmlFor="gen-source" optional hint="贴一段讲义、笔记或错题解析，卡片会更贴合你学的内容。">
            <Textarea id="gen-source" reading autoGrow rows={5} maxHeight={280} value={source} onChange={e => setSource(e.target.value)} />
          </Field>
          <Field label="标签" htmlFor="gen-tags" optional>
            <Input id="gen-tags" value={tags} placeholder="例如：记忆方法" onChange={e => setTags(e.target.value)} />
          </Field>
        </div>
      )}
    </Dialog>
  )
}

/* ============================================================================
   CSV import / export (Anki-compatible columns)
   ========================================================================== */
export function CsvDialog({
  open,
  onOpenChange,
  onImported,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onImported: () => void
}) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    if (open) setText('')
  }, [open])

  const check = text.trim() ? csvLooksValid(text) : null

  const doExport = async () => {
    setExporting(true)
    try {
      const r = await exportAnkiCardsCSV()
      if (!r) throw new Error('导出失败')
      const blob = new Blob([`﻿${r.csv}`], { type: 'text/csv;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = r.filename || 'mnemox_cards.csv'
      a.click()
      URL.revokeObjectURL(url)
      toast.success(`已导出 ${r.count} 张卡`)
    } catch (error) {
      toast.error(getApiErrorMessage(error, '导出失败'))
    } finally {
      setExporting(false)
    }
  }

  const doImport = async () => {
    if (!check?.ok) return
    setBusy(true)
    try {
      const r = await importAnkiCardsCSV(text)
      if (!r) throw new Error('导入失败，检查一下 CSV 格式')
      toast.success(`导入了 ${r.created} 张卡`, { description: r.skipped ? `跳过 ${r.skipped} 行（正面或背面为空）。` : undefined })
      onImported()
      onOpenChange(false)
    } catch (error) {
      toast.error(getApiErrorMessage(error, '导入失败'))
    } finally {
      setBusy(false)
    }
  }

  const readFile = async (file: File | undefined) => {
    if (!file) return
    if (file.size > 5 * 1024 * 1024) {
      toast.warning('文件超过 5 MB，拆小一点再导入')
      return
    }
    setText(await file.text())
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="导入与导出"
      description="CSV 的第一行是表头，至少要有 front 和 back 两列。可选列：tags、note、due_at、interval_days、ease_factor、repetitions。"
      width={38}
      footerStart={
        <Button variant="ghost" size="sm" icon={<Download />} loading={exporting} onClick={() => void doExport()}>
          导出全部卡片
        </Button>
      }
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button variant="primary" icon={<FileUp />} loading={busy} disabled={!check?.ok} onClick={() => void doImport()}>
            导入{check?.ok ? ` ${check.rows} 行` : ''}
          </Button>
        </>
      }
    >
      <div className={s.form}>
        <Field label="从文件读取" htmlFor="csv-file" optional>
          <Input id="csv-file" type="file" accept=".csv,text/csv" onChange={e => void readFile(e.target.files?.[0])} />
        </Field>
        <Field label="或者直接粘贴" htmlFor="csv-text">
          <Textarea
            id="csv-text"
            className={s.mono}
            rows={8}
            value={text}
            placeholder={'front,back,tags\n什么是间隔效应？,分散练习比集中练习记得更牢,记忆'}
            onChange={e => setText(e.target.value)}
          />
        </Field>
        {check && !check.ok && <Notice tone="warning">{check.reason}</Notice>}
      </div>
    </Dialog>
  )
}
