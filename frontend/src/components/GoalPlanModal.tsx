import { useState, useEffect } from 'react'
import { Modal, Form, InputNumber, Select, message, Spin } from 'antd'
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

export function GoalPlanModal({ open, goalId, materialId, onClose, onSuccess }: GoalPlanModalProps) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [loadingChapters, setLoadingChapters] = useState(false)

  useEffect(() => {
    if (open && materialId) {
      void loadChapters()
    }
  }, [open, materialId])

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
      okText="生成本周任务"
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
        </Form>

        <div style={{ 
          marginTop: 16, 
          padding: 12, 
          background: 'var(--primary-50)', 
          borderRadius: 'var(--radius-md)',
          fontSize: 13,
          color: 'var(--text-secondary)',
        }}>
          💡 提示：系统会根据你的设定，每周自动生成学习任务。完成本周任务后，可以手动生成下周任务。
        </div>
      </Spin>
    </Modal>
  )
}
