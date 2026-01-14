import { useState, useEffect, useRef } from 'react'
import {
  Layout,
  Card,
  List,
  Button,
  Input,
  InputNumber,
  Modal,
  Progress,
  message,
  notification,
  Upload,
  Calendar,
  Badge,
  Drawer,
} from 'antd'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'
import {
  ExceptionOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  CheckCircleOutlined,
  UploadOutlined,
  FileOutlined,
  DeleteOutlined,
  CalendarOutlined,
  DownOutlined,
  UpOutlined,
} from '@ant-design/icons'

const { Sider, Content } = Layout
const { TextArea } = Input

interface PomodoroConfig {
  duration: number
  taskName: string
}

interface Material {
  id: number
  name: string
  uploadTime: string
}

interface DailyPlan {
  date: string
  content: string
}

export function ObsidianLayout() {
  // 番茄钟状态
  const [pomodoroTime, setPomodoroTime] = useState(25 * 60)
  const [isRunning, setIsRunning] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const [pomodoroConfig, setPomodoroConfig] = useState<PomodoroConfig>({
    duration: 25,
    taskName: '',
  })
  const [showPomodoroModal, setShowPomodoroModal] = useState(false)
  const timerRef = useRef<NodeJS.Timeout | null>(null)

  // 资料列表
  const [materials, setMaterials] = useState<Material[]>([
    { id: 1, name: '高等数学.pdf', uploadTime: '2024-01-10' },
    { id: 2, name: '线性代数.pdf', uploadTime: '2024-01-09' },
  ])

  // 日历相关
  const [calendarExpanded, setCalendarExpanded] = useState(false)
  const [selectedDate, setSelectedDate] = useState<Dayjs | null>(null)
  const [showPlanModal, setShowPlanModal] = useState(false)
  const [dailyPlans, setDailyPlans] = useState<Record<string, string>>({
    '2024-01-10': '复习第一章\n完成10道习题',
    '2024-01-11': '学习第二章\n整理笔记',
  })
  const [currentPlan, setCurrentPlan] = useState('')

  // 错题列表
  const wrongQuestions = [
    { id: 1, title: '极限计算题', status: '未掌握' },
    { id: 2, title: '导数应用题', status: '部分掌握' },
  ]

  // 番茄钟倒计时
  useEffect(() => {
    if (isRunning && pomodoroTime > 0) {
      timerRef.current = setInterval(() => {
        setPomodoroTime((prev) => {
          if (prev <= 1) {
            setIsRunning(false)
            notification.success({
              message: '番茄钟完成！',
              description: `恭喜完成任务：${pomodoroConfig.taskName}`,
              duration: 0,
            })
            if ('Notification' in window && Notification.permission === 'granted') {
              new Notification('番茄钟完成！', {
                body: `任务：${pomodoroConfig.taskName}`,
                icon: '/favicon.ico',
              })
            }
            return pomodoroConfig.duration * 60
          }
          return prev - 1
        })
      }, 1000)
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current)
      }
    }

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
      }
    }
  }, [isRunning, pomodoroConfig.duration, pomodoroConfig.taskName])

  // 请求通知权限
  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  // 番茄钟控制
  const startPomodoro = () => {
    if (!pomodoroConfig.taskName) {
      message.warning('请先设置任务名称')
      setShowPomodoroModal(true)
      return
    }
    setIsRunning(true)
    setIsPaused(false)
  }

  const pausePomodoro = () => {
    setIsPaused(true)
    setIsRunning(false)
  }

  const resumePomodoro = () => {
    setIsPaused(false)
    setIsRunning(true)
  }

  const completePomodoro = () => {
    message.success('番茄钟完成！')
    setIsRunning(false)
    setIsPaused(false)
    setPomodoroTime(pomodoroConfig.duration * 60)
  }

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }

  // 上传资料
  const handleUpload = (file: File) => {
    const newMaterial: Material = {
      id: Date.now(),
      name: file.name,
      uploadTime: dayjs().format('YYYY-MM-DD'),
    }
    setMaterials([newMaterial, ...materials])
    message.success(`已上传：${file.name}`)
    return false // 阻止默认上传行为
  }

  // 删除资料
  const deleteMaterial = (id: number) => {
    setMaterials(materials.filter((m) => m.id !== id))
    message.success('已删除')
  }

  // 日历相关
  const onDateSelect = (date: Dayjs) => {
    setSelectedDate(date)
    const dateStr = date.format('YYYY-MM-DD')
    setCurrentPlan(dailyPlans[dateStr] || '')
    setShowPlanModal(true)
  }

  const savePlan = () => {
    if (selectedDate) {
      const dateStr = selectedDate.format('YYYY-MM-DD')
      setDailyPlans({
        ...dailyPlans,
        [dateStr]: currentPlan,
      })
      message.success('计划已保存')
      setShowPlanModal(false)
    }
  }

  const dateCellRender = (value: Dayjs) => {
    const dateStr = value.format('YYYY-MM-DD')
    const hasPlan = dailyPlans[dateStr]
    return hasPlan ? (
      <Badge status="success" text="" />
    ) : null
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* 左侧边栏 */}
      <Sider
        width={280}
        style={{
          background: '#fafafa',
          borderRight: '1px solid #f0f0f0',
          overflow: 'auto',
          height: '100vh',
          position: 'fixed',
          left: 0,
        }}
      >
        {/* 左上：资料库 */}
        <div style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0 }}>
              <FileOutlined /> 资料库
            </h3>
          </div>
          <List
            size="small"
            dataSource={materials}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => deleteMaterial(item.id)}
                  />,
                ]}
                style={{ cursor: 'pointer', padding: '8px 12px' }}
              >
                <List.Item.Meta
                  avatar={<FileOutlined />}
                  title={item.name}
                  description={
                    <span style={{ fontSize: 11, color: '#999' }}>
                      {item.uploadTime}
                    </span>
                  }
                />
              </List.Item>
            )}
          />
        </div>

        {/* 左下：导入资料 */}
        <div style={{ padding: '16px', borderTop: '1px solid #f0f0f0' }}>
          <Upload
            beforeUpload={handleUpload}
            showUploadList={false}
            accept=".pdf,.doc,.docx,.txt,.md"
          >
            <Button icon={<UploadOutlined />} block>
              导入资料
            </Button>
          </Upload>
        </div>

        {/* 左下：错题本 */}
        <div style={{ padding: '16px', borderTop: '1px solid #f0f0f0' }}>
          <h3 style={{ marginBottom: 16 }}>
            <ExceptionOutlined /> 错题本
          </h3>
          <List
            size="small"
            dataSource={wrongQuestions}
            renderItem={(item) => (
              <List.Item style={{ cursor: 'pointer' }}>
                <List.Item.Meta
                  title={<span style={{ fontSize: 13 }}>{item.title}</span>}
                  description={
                    <span style={{ fontSize: 11, color: '#999' }}>
                      {item.status}
                    </span>
                  }
                />
              </List.Item>
            )}
          />
        </div>
      </Sider>

      {/* 中间内容区 */}
      <Layout style={{ marginLeft: 280, marginRight: 320 }}>
        <Content style={{ padding: '24px', background: '#fff', minHeight: '100vh' }}>
          <div style={{ maxWidth: 800, margin: '0 auto' }}>
            <h2>AI 学习助手</h2>

            {/* 对话区域 */}
            <div
              style={{
                minHeight: 500,
                marginTop: 24,
                padding: 16,
                background: '#fafafa',
                borderRadius: 8,
              }}
            >
              <div style={{ textAlign: 'center', color: '#999', padding: '100px 0' }}>
                <p style={{ fontSize: 16 }}>欢迎使用学习助手！</p>
                <p>选择一个资料开始学习，或者直接提问</p>
              </div>
            </div>

            {/* 输入区域 */}
            <div style={{ marginTop: 16 }}>
              <TextArea
                placeholder="输入你的问题或回答..."
                autoSize={{ minRows: 3, maxRows: 6 }}
                style={{ marginBottom: 8 }}
              />
              <Button type="primary" size="large" block>
                发送
              </Button>
            </div>
          </div>
        </Content>
      </Layout>

      {/* 右侧信息栏 */}
      <Sider
        width={320}
        style={{
          background: '#fff',
          borderLeft: '1px solid #f0f0f0',
          overflow: 'auto',
          height: '100vh',
          position: 'fixed',
          right: 0,
          padding: '24px',
        }}
      >
        {/* 日历 - 可折叠 */}
        <Card
          size="small"
          title={
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <CalendarOutlined />
              <span>日历</span>
            </div>
          }
          extra={
            <Button
              type="text"
              size="small"
              icon={calendarExpanded ? <UpOutlined /> : <DownOutlined />}
              onClick={() => setCalendarExpanded(!calendarExpanded)}
            />
          }
          style={{ marginBottom: 16 }}
        >
          {calendarExpanded ? (
            <Calendar
              fullscreen={false}
              onSelect={onDateSelect}
              cellRender={dateCellRender}
            />
          ) : (
            <div style={{ textAlign: 'center', padding: '8px 0', color: '#999', fontSize: 12 }}>
              点击展开查看完整日历
            </div>
          )}
        </Card>

        {/* 当前学习信息 */}
        <Card size="small" title="当前学习" style={{ marginBottom: 16 }}>
          <p style={{ color: '#999', fontSize: 13 }}>暂未选择章节</p>
        </Card>

        {/* 学习进度 */}
        <Card size="small" title="今日进度" style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>学习时间</div>
            <Progress percent={30} size="small" />
          </div>
          <div>
            <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>完成任务</div>
            <Progress percent={50} size="small" status="active" />
          </div>
        </Card>

        {/* 番茄钟 - 固定在底部 */}
        <Card
          size="small"
          title="🍅 番茄工作法"
          extra={
            <Button
              type="link"
              size="small"
              onClick={() => setShowPomodoroModal(true)}
            >
              设置
            </Button>
          }
          style={{
            position: 'absolute',
            bottom: 24,
            left: 24,
            right: 24,
          }}
        >
          <div style={{ textAlign: 'center' }}>
            {pomodoroConfig.taskName && (
              <div style={{ marginBottom: 8, fontSize: 12, color: '#666' }}>
                {pomodoroConfig.taskName}
              </div>
            )}

            <div
              style={{
                fontSize: 48,
                fontWeight: 'bold',
                fontFamily: 'monospace',
                margin: '16px 0',
              }}
            >
              {formatTime(pomodoroTime)}
            </div>

            <Progress
              percent={Math.round(
                (1 - pomodoroTime / (pomodoroConfig.duration * 60)) * 100
              )}
              showInfo={false}
              strokeColor="#52c41a"
            />

            <div
              style={{ marginTop: 16, display: 'flex', gap: 8, justifyContent: 'center' }}
            >
              {!isRunning && !isPaused && (
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  onClick={startPomodoro}
                >
                  开始
                </Button>
              )}

              {isRunning && (
                <Button icon={<PauseCircleOutlined />} onClick={pausePomodoro}>
                  暂停
                </Button>
              )}

              {isPaused && (
                <>
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    onClick={resumePomodoro}
                  >
                    继续
                  </Button>
                  <Button icon={<CheckCircleOutlined />} onClick={completePomodoro}>
                    完成
                  </Button>
                </>
              )}
            </div>
          </div>
        </Card>
      </Sider>

      {/* 番茄钟设置弹窗 */}
      <Modal
        title="番茄钟设置"
        open={showPomodoroModal}
        onOk={() => {
          setPomodoroTime(pomodoroConfig.duration * 60)
          setShowPomodoroModal(false)
          message.success('设置成功')
        }}
        onCancel={() => setShowPomodoroModal(false)}
      >
        <div style={{ marginBottom: 16 }}>
          <label>任务名称</label>
          <Input
            placeholder="例如：学习第一章"
            value={pomodoroConfig.taskName}
            onChange={(e) =>
              setPomodoroConfig({ ...pomodoroConfig, taskName: e.target.value })
            }
            style={{ marginTop: 8 }}
          />
        </div>
        <div>
          <label>番茄时长（分钟）</label>
          <InputNumber
            min={1}
            max={60}
            value={pomodoroConfig.duration}
            onChange={(value) =>
              setPomodoroConfig({ ...pomodoroConfig, duration: value || 25 })
            }
            style={{ marginTop: 8, width: '100%' }}
          />
        </div>
      </Modal>

      {/* 日程计划弹窗 */}
      <Modal
        title={`${selectedDate?.format('YYYY年MM月DD日')} 的计划`}
        open={showPlanModal}
        onOk={savePlan}
        onCancel={() => setShowPlanModal(false)}
        width={600}
      >
        <TextArea
          placeholder="输入今日计划或学习记录...&#10;例如：&#10;- 复习第一章&#10;- 完成10道练习题&#10;- 整理笔记"
          value={currentPlan}
          onChange={(e) => setCurrentPlan(e.target.value)}
          autoSize={{ minRows: 8, maxRows: 15 }}
        />
      </Modal>
    </Layout>
  )
}
