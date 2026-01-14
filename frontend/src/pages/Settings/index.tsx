import { Card, Form, Input, Select, InputNumber, Button, Space, message } from 'antd'

export function Settings() {
  const [form] = Form.useForm()

  const handleSave = (values: any) => {
    console.log('保存设置:', values)
    message.success('设置保存成功')
  }

  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>设置</h1>
      
      <Card title="AI 配置" style={{ marginBottom: 16 }}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            ai_provider: 'openai',
            pomodoro_duration: 25,
            break_duration: 5,
          }}
          onFinish={handleSave}
        >
          <Form.Item
            label="AI 提供商"
            name="ai_provider"
            tooltip="选择你要使用的 AI 服务提供商"
          >
            <Select>
              <Select.Option value="openai">OpenAI (GPT-4)</Select.Option>
              <Select.Option value="claude">Anthropic Claude</Select.Option>
              <Select.Option value="gemini">Google Gemini</Select.Option>
              <Select.Option value="qwen">通义千问</Select.Option>
            </Select>
          </Form.Item>
          
          <Form.Item
            label="API Key"
            name="api_key"
            tooltip="请妥善保管你的 API Key"
          >
            <Input.Password placeholder="输入你的 API Key" />
          </Form.Item>
        </Form>
      </Card>
      
      <Card title="番茄钟设置" style={{ marginBottom: 16 }}>
        <Form form={form} layout="vertical">
          <Form.Item
            label="工作时长（分钟）"
            name="pomodoro_duration"
          >
            <InputNumber min={1} max={60} />
          </Form.Item>
          
          <Form.Item
            label="休息时长（分钟）"
            name="break_duration"
          >
            <InputNumber min={1} max={30} />
          </Form.Item>
        </Form>
      </Card>
      
      <Card title="复习提醒">
        <Form form={form} layout="vertical">
          <Form.Item
            label="每日提醒时间"
            name="reminder_time"
          >
            <Input type="time" />
          </Form.Item>
        </Form>
      </Card>
      
      <div style={{ marginTop: 24 }}>
        <Space>
          <Button type="primary" onClick={() => form.submit()}>
            保存设置
          </Button>
          <Button onClick={() => form.resetFields()}>
            重置
          </Button>
        </Space>
      </div>
    </div>
  )
}
