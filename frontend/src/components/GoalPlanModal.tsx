import { useState, useEffect } from 'react'
import { Modal, Form, Input, InputNumber, Select, DatePicker, Button, message, Spin } from 'antd'
import dayjs from 'dayjs'
import { apiFetch } from '../services/apiClient'

interface Chapter {
  id: number
  title: string
}

interface GoalPlanModalProps {
  open: boolean
  goalId: number | null
  materialId: number | null
  onClose: () => void
  onSuccess: () => void
}

type ManualTaskType = 'learn' | 'review' | 'practice' | 'summarize'

interface ManualTaskRow {
  id: string
  title: string
  task_type: ManualTaskType
  planned_date: string | null
}

const TASK_TYPE_OPTIONS: { label: string; value: ManualTaskType }[] = [
  { label: '学习', value: 'learn' },
  { label: '复习', value: 'review' },
  { label: '练习', value: 'practice' },
  { label: '总结', value: 'summarize' },
]

const createManualTaskRow = (): ManualTaskRow => ({
  id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  title: '',
  task_type: 'learn',
  planned_date: null,
})

export function GoalPlanModal({ open, goalId, materialId, onClose, onSuccess }: GoalPlanModalProps) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [loadingChapters, setLoadingChapters] = useState(false)
  const [manualTasks, setManualTasks] = useState<ManualTaskRow[]>([createManualTaskRow()])

  useEffect(() => {
    if (open && materialId) {
      void loadChapters()
      return
    }
    setChapters([])
  }, [open, materialId])

  useEffect(() => {
    if (!open || materialId) return
    setManualTasks([createManualTaskRow()])
    form.setFieldValue('manual_description', undefined)
  }, [open, materialId, form])

  const loadChapters = async () => {
    if (!materialId) return
    setLoadingChapters(true)
    try {
      const data = await apiFetch<Chapter[]>(`/api/materials/${materialId}/chapters`)
      setChapters(data)
    } catch (error) {
      message.error('加载章节失败')
    } finally {
      setLoadingChapters(false)
    }
  }

  const handleSubmit = async () => {
    if (!goalId) return
    
    try {
      const values = await form.validateFields()
      setLoading(true)

      if (!materialId) {
        const rows = manualTasks
          .map((row) => ({ ...row, title: row.title.trim() }))
          .filter((row) => row.title.length > 0)

        if (rows.length === 0) {
          message.warning('请至少填写一条手动任务')
          return
        }

        await Promise.all(
          rows.map((row) =>
            apiFetch(`/api/goals/${goalId}/tasks`, {
              method: 'POST',
              body: JSON.stringify({
                title: row.title,
                description: values.manual_description?.trim() || null,
                task_type: row.task_type,
                planned_date: row.planned_date,
              }),
            })
          )
        )

        message.success(`已创建 ${rows.length} 条手动任务`)
        form.resetFields()
        setManualTasks([createManualTaskRow()])
        onSuccess()
        onClose()
        return
      }
      
      const response = await apiFetch(`/api/goals/${goalId}/plan`, {
        method: 'POST',
        body: JSON.stringify({
          total_days: values.total_days,
          current_chapter_id: values.current_chapter_id || null,
          study_days_per_week: values.study_days_per_week,
        }),
      })
      
      message.success(`学习计划已设定，生成了 ${response.generated_tasks} 个本周任务`)
      form.resetFields()
      onSuccess()
      onClose()
    } catch (error: any) {
      message.error(error.message || '设定学习计划失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      title="制定学习计划"
      open={open}
      onCancel={onClose}
      onOk={handleSubmit}
      confirmLoading={loading}
      okText={materialId ? '生成本周任务' : '创建手动任务'}
      cancelText="取消"
      width={500}
    >
      <Spin spinning={loadingChapters}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            total_days: 14,
            study_days_per_week: 5,
          }}
        >
          {materialId ? (
            <>
              <Form.Item
                label="计划学习天数"
                name="total_days"
                rules={[{ required: true, message: '请输入计划天数' }]}
                extra="你希望在多少天内学完这个目标？"
              >
                <InputNumber min={1} max={365} style={{ width: '100%' }} addonAfter="天" />
              </Form.Item>

              <Form.Item
                label="当前进度"
                name="current_chapter_id"
                extra="从哪一章开始学习？留空则从第一章开始"
              >
                <Select
                  placeholder="选择当前章节（可选）"
                  allowClear
                  options={chapters.map((ch) => ({
                    label: ch.title,
                    value: ch.id,
                  }))}
                />
              </Form.Item>

              <Form.Item
                label="每周学习天数"
                name="study_days_per_week"
                rules={[{ required: true, message: '请输入每周学习天数' }]}
                extra="每周计划学习几天？（周末会自动跳过）"
              >
                <InputNumber min={1} max={7} style={{ width: '100%' }} addonAfter="天/周" />
              </Form.Item>
            </>
          ) : (
            <>
              <div style={{ marginBottom: 12, fontSize: 13, color: 'var(--text-secondary)' }}>
                当前目标未绑定资料，可逐条填写任务并单独设置类型与计划日期
              </div>

              <div style={{ display: 'grid', gap: 10, marginBottom: 12 }}>
                {manualTasks.map((row, index) => (
                  <div
                    key={row.id}
                    style={{
                      border: '1px solid var(--border-color)',
                      borderRadius: 'var(--radius-sm)',
                      padding: 10,
                      background: 'var(--bg-primary)',
                    }}
                  >
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 8 }}>
                      任务 {index + 1}
                    </div>
                    <div style={{ display: 'grid', gap: 8 }}>
                      <Input
                        placeholder="任务标题（如：六级听力精听 1 套）"
                        value={row.title}
                        onChange={(e) => {
                          const value = e.target.value
                          setManualTasks((prev) =>
                            prev.map((item) => (item.id === row.id ? { ...item, title: value } : item))
                          )
                        }}
                      />
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 8 }}>
                        <Select
                          value={row.task_type}
                          options={TASK_TYPE_OPTIONS}
                          onChange={(value) => {
                            setManualTasks((prev) =>
                              prev.map((item) => (item.id === row.id ? { ...item, task_type: value as ManualTaskType } : item))
                            )
                          }}
                        />
                        <DatePicker
                          style={{ width: '100%' }}
                          placeholder="计划日期（可选）"
                          value={row.planned_date ? dayjs(row.planned_date) : null}
                          onChange={(value) => {
                            setManualTasks((prev) =>
                              prev.map((item) => (
                                item.id === row.id
                                  ? { ...item, planned_date: value ? value.format('YYYY-MM-DD') : null }
                                  : item
                              ))
                            )
                          }}
                        />
                        <Button
                          danger
                          disabled={manualTasks.length <= 1}
                          onClick={() => {
                            setManualTasks((prev) => prev.filter((item) => item.id !== row.id))
                          }}
                        >
                          删除
                        </Button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              <Button
                onClick={() => setManualTasks((prev) => [...prev, createManualTaskRow()])}
                style={{ marginBottom: 12 }}
              >
                + 新增一条任务
              </Button>

              <Form.Item
                label="统一备注（可选）"
                name="manual_description"
              >
                <Input placeholder="例如：本周重点提高听力细节捕捉与长难句理解" />
              </Form.Item>
            </>
          )}
        </Form>

        <div style={{ 
          marginTop: 16, 
          padding: 12, 
          background: 'var(--primary-50)', 
          borderRadius: 'var(--radius-md)',
          fontSize: 13,
          color: 'var(--text-secondary)',
        }}>
          {materialId
            ? '💡 提示：系统会根据你的设定，每周自动生成学习任务。完成本周任务后，可以手动生成下周任务。'
            : '💡 提示：无资料目标也可以先手动建任务，后续再补资料并切换为自动生成。'}
        </div>
      </Spin>
    </Modal>
  )
}
