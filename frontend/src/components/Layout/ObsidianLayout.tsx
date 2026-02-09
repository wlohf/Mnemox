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
  Statistic,
  Row,
  Col,
  Switch,
  Tag,
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
  BarChartOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { usePomodoroStore } from '../../stores/pomodoroStore'

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
  file_type?: string
  content?: string
  file_path?: string
}

interface DailyPlan {
  date: string
  content: string
}

export function ObsidianLayout() {
  // 使用zustand store管理番茄钟
  const { 
    isRunning, 
    isPaused, 
    remainingTime, 
    currentTask, 
    duration,
    startTimer, 
    pauseTimer, 
    resumeTimer, 
    completeTimer, 
    resetTimer,
    tick,
    getStats 
  } = usePomodoroStore()
  
  const [pomodoroConfig, setPomodoroConfig] = useState<PomodoroConfig>({
    duration: 25,
    taskName: '',
  })
  const [showPomodoroModal, setShowPomodoroModal] = useState(false)
  const [showStatsModal, setShowStatsModal] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  
  // 获取统计数据
  const stats = getStats()

  // 资料列表（从后端加载）
  const [materials, setMaterials] = useState<Material[]>([])
  const [materialsLoading, setMaterialsLoading] = useState(false)
  const [syncToAnythingLLM, setSyncToAnythingLLM] = useState(true)
  const [ragStatus, setRagStatus] = useState<{
    enabled: boolean
    anythingllm_online: boolean
    collector_online: boolean
    workspace_ok: boolean
  } | null>(null)
  
  // 资料预览状态
  const [previewVisible, setPreviewVisible] = useState(false)
  const [currentMaterial, setCurrentMaterial] = useState<Material | null>(null)
  const [previewContent, setPreviewContent] = useState<string>('')
  const [previewLoading, setPreviewLoading] = useState(false)

  // 日历相关（计划持久化到后端）
  const [calendarExpanded, setCalendarExpanded] = useState(false)
  const [selectedDate, setSelectedDate] = useState<Dayjs | null>(null)
  const [showPlanModal, setShowPlanModal] = useState(false)
  const [dailyPlans, setDailyPlans] = useState<Record<string, string>>({})
  const [currentPlan, setCurrentPlan] = useState('')
  const [weeklyPlans, setWeeklyPlans] = useState<DailyPlan[]>([])

  // 错题列表
  const wrongQuestions = [
    { id: 1, title: '极限计算题', status: '未掌握' },
    { id: 2, title: '导数应用题', status: '部分掌握' },
  ]

  // 番茄钟倒计时
  useEffect(() => {
    if (isRunning && remainingTime > 0) {
      timerRef.current = setInterval(() => {
        tick()
      }, 1000)
    } else if (remainingTime <= 0) {
      notification.success({
        message: '番茄钟完成！',
        description: `恭喜完成任务：${currentTask}`,
        duration: 0,
      })
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('番茄钟完成！', {
          body: `任务：${currentTask}`,
          icon: '/favicon.ico',
        })
      }
    }
    
    if (!isRunning && timerRef.current) {
      clearInterval(timerRef.current)
    }

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
      }
    }
  }, [isRunning, remainingTime, tick, currentTask])

  // 请求通知权限
  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  // 番茄钟控制
  const handleStartPomodoro = () => {
    if (!pomodoroConfig.taskName) {
      message.warning('请先设置任务名称')
      setShowPomodoroModal(true)
      return
    }
    startTimer(pomodoroConfig.taskName, pomodoroConfig.duration)
  }

  const handleCompletePomodoro = () => {
    completeTimer()
    message.success('番茄钟完成！已记录到统计中')
  }

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }
  
  // 周统计图表配置
  const getWeekChartOption = () => ({
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const data = params[0]
        const dayData = stats.weeklyData[data.dataIndex]
        return `${['日', '一', '二', '三', '四', '五', '六'][new Date(dayData?.date).getDay()] || ''}<br/>🍅 ${data.value} 个<br/>⏱️ ${dayData?.minutes || 0} 分钟`
      },
    },
    grid: { top: 10, right: 10, bottom: 20, left: 30 },
    xAxis: {
      type: 'category',
      data: stats.weeklyData.map((d) => ['日', '一', '二', '三', '四', '五', '六'][new Date(d.date).getDay()]),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#999', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: 'rgba(0,0,0,0.05)' } },
      axisLabel: { color: '#999', fontSize: 10 },
    },
    series: [{
      type: 'bar',
      data: stats.weeklyData.map((d) => d.count),
      barWidth: '50%',
      itemStyle: {
        color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#ff7875' }, { offset: 1, color: '#ff4d4f' }] },
        borderRadius: [4, 4, 0, 0],
      },
    }],
  })

  // 上传资料
  const handleUpload = async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('title', file.name)
    formData.append('sync_to_anythingllm', syncToAnythingLLM ? 'true' : 'false')
    
    try {
      const response = await fetch('/api/materials/upload', {
        method: 'POST',
        body: formData,
      })
      
      if (response.ok) {
        const data = await response.json()
        const fileExt = file.name.split('.').pop()?.toLowerCase() || ''
        const newMaterial: Material = {
          id: data.id || Date.now(),
          name: data.title || file.name,
          uploadTime: dayjs().format('YYYY-MM-DD'),
          file_type: fileExt,
          file_path: data.file_path,
        }
        setMaterials((prev) => [newMaterial, ...prev])
        message.success(`已上传：${file.name}`)
      } else {
        const err = await response.json().catch(() => null)
        message.error(err?.detail || '上传失败')
      }
    } catch (error) {
      message.error('上传失败：无法连接后端（请确认后端已启动）')
    }
    return false
  }
  
  // 预览资料
  const handlePreview = async (material: Material) => {
    setCurrentMaterial(material)
    setPreviewVisible(true)
    setPreviewLoading(true)
    
    try {
      // 尝试从后端获取内容
      const response = await fetch(`/api/materials/${material.id}`)
      if (response.ok) {
        const data = await response.json()
        setPreviewContent(data.content || '暂无内容预览')
      } else {
        setPreviewContent('暂无内容预览，请确保后端服务已启动')
      }
    } catch (error) {
      // 本地模拟
      if (material.file_type === 'pdf') {
        setPreviewContent('PDF文件预览需要启动后端服务来提取文本内容')
      } else {
        setPreviewContent('请启动后端服务后，重新上传资料以支持预览功能')
      }
    }
    setPreviewLoading(false)
  }

  // 删除资料
  const deleteMaterial = (id: number) => {
    setMaterials(materials.filter((m) => m.id !== id))
    message.success('已删除')
  }

  // 首次加载：拉取资料列表 & RAG 状态
  useEffect(() => {
    const load = async () => {
      setMaterialsLoading(true)
      try {
        const res = await fetch('/api/materials?skip=0&limit=100')
        if (res.ok) {
          const arr = await res.json()
          const mapped: Material[] = (arr || []).map((m: any) => ({
            id: m.id,
            name: m.title,
            uploadTime: (m.created_at || '').slice(0, 10) || dayjs().format('YYYY-MM-DD'),
            file_type: m.file_type,
            file_path: m.file_path,
          }))
          setMaterials(mapped.reverse())
        }
      } finally {
        setMaterialsLoading(false)
      }

      try {
        const ragRes = await fetch('/api/rag/health')
        if (ragRes.ok) {
          const j = await ragRes.json()
          setRagStatus(j)
        }
      } catch {
        // ignore
      }

      await loadWeeklyPlans()
    }
    load()
  }, [])

  const loadWeeklyPlans = async () => {
    // 周一到周日
    const start = dayjs().startOf('week').add(1, 'day')
    const end = start.add(6, 'day')
    const startStr = start.format('YYYY-MM-DD')
    const endStr = end.format('YYYY-MM-DD')
    try {
      const res = await fetch(`/api/plans?start=${startStr}&end=${endStr}`)
      if (res.ok) {
        const arr = await res.json()
        const list: DailyPlan[] = (arr || []).map((p: any) => ({ date: p.date, content: p.content || '' }))
        setWeeklyPlans(list)
        // 合并到缓存，使日历上的小绿点即时显示
        setDailyPlans((prev) => {
          const next = { ...prev }
          for (const p of list) next[p.date] = p.content
          return next
        })
      }
    } catch {
      // ignore
    }
  }

  // 日历相关
  const onDateSelect = (date: Dayjs) => {
    setSelectedDate(date)
    const dateStr = date.format('YYYY-MM-DD')
    ;(async () => {
      try {
        const res = await fetch(`/api/plans/${dateStr}`)
        if (res.ok) {
          const j = await res.json()
          setCurrentPlan(j.content || '')
          setDailyPlans((prev) => ({ ...prev, [dateStr]: j.content || '' }))
        } else {
          setCurrentPlan(dailyPlans[dateStr] || '')
        }
      } catch {
        setCurrentPlan(dailyPlans[dateStr] || '')
      } finally {
        setShowPlanModal(true)
      }
    })()
  }

  const savePlan = () => {
    if (selectedDate) {
      const dateStr = selectedDate.format('YYYY-MM-DD')
      ;(async () => {
        try {
          const res = await fetch(`/api/plans/${dateStr}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: currentPlan }),
          })
          if (!res.ok) {
            const err = await res.json().catch(() => null)
            throw new Error(err?.detail || '保存失败')
          }
          setDailyPlans((prev) => ({ ...prev, [dateStr]: currentPlan }))
          message.success('计划已保存')
          setShowPlanModal(false)
          await loadWeeklyPlans()
        } catch (e: any) {
          message.error(e?.message || '保存失败（请确认后端已启动）')
        }
      })()
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
            loading={materialsLoading}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    type="text"
                    size="small"
                    icon={<FileOutlined />}
                    onClick={() => handlePreview(item)}
                    title="预览"
                    style={{ color: '#1890ff' }}
                  />,
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => deleteMaterial(item.id)}
                    title="删除"
                  />,
                ]}
                style={{ cursor: 'pointer', padding: '8px 12px' }}
                onClick={() => handlePreview(item)}
              >
                <List.Item.Meta
                  avatar={<FileOutlined style={{ color: item.file_type === 'pdf' ? '#ff4d4f' : '#1890ff' }} />}
                  title={<span style={{ fontSize: 13 }}>{item.name}</span>}
                  description={
                    <span style={{ fontSize: 11, color: '#999' }}>
                      {item.uploadTime} · {item.file_type?.toUpperCase() || 'FILE'}
                    </span>
                  }
                />
              </List.Item>
            )}
          />
        </div>

        {/* 左下：导入资料 */}
        <div style={{ padding: '16px', borderTop: '1px solid #f0f0f0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontSize: 12, color: '#666' }}>同步到 AnythingLLM</span>
            <Switch size="small" checked={syncToAnythingLLM} onChange={setSyncToAnythingLLM} />
          </div>
          {ragStatus && (
            <div style={{ marginBottom: 8 }}>
              <Tag color={ragStatus.enabled && ragStatus.anythingllm_online ? 'green' : 'default'}>
                AnythingLLM: {ragStatus.anythingllm_online ? '在线' : '离线'}
              </Tag>
              <Tag color={ragStatus.enabled && ragStatus.collector_online ? 'green' : 'default'}>
                Collector: {ragStatus.collector_online ? '在线' : '离线'}
              </Tag>
            </div>
          )}
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

        {/* 左下：本周计划（来自右侧日历的每日计划） */}
        <div style={{ padding: '16px', borderTop: '1px solid #f0f0f0' }}>
          <h3 style={{ marginBottom: 12 }}>
            <CalendarOutlined /> 本周计划
          </h3>
          <List
            size="small"
            dataSource={weeklyPlans}
            locale={{ emptyText: '本周暂无计划（在右侧日历中添加）' }}
            renderItem={(p) => (
              <List.Item style={{ padding: '6px 0' }}>
                <div style={{ width: '100%' }}>
                  <div style={{ fontSize: 12, color: '#666' }}>{p.date}</div>
                  <div
                    style={{
                      fontSize: 12,
                      color: '#999',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {(p.content || '').split('\n')[0] || '（空）'}
                  </div>
                </div>
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
            <div style={{ display: 'flex', gap: 4 }}>
              <Button
                type="text"
                size="small"
                icon={<BarChartOutlined />}
                onClick={() => setShowStatsModal(true)}
                title="查看统计"
              />
              <Button
                type="link"
                size="small"
                onClick={() => setShowPomodoroModal(true)}
              >
                设置
              </Button>
            </div>
          }
          style={{
            position: 'absolute',
            bottom: 24,
            left: 24,
            right: 24,
          }}
        >
          <div style={{ textAlign: 'center' }}>
            {/* 今日统计 */}
            <Row gutter={8} style={{ marginBottom: 12 }}>
              <Col span={12}>
                <Statistic 
                  title={<span style={{ fontSize: 11 }}>今日番茄</span>} 
                  value={stats.todayCount} 
                  suffix="个"
                  valueStyle={{ fontSize: 18, color: '#ff4d4f' }}
                />
              </Col>
              <Col span={12}>
                <Statistic 
                  title={<span style={{ fontSize: 11 }}>专注时长</span>} 
                  value={stats.todayMinutes} 
                  suffix="分钟"
                  valueStyle={{ fontSize: 18, color: '#1890ff' }}
                />
              </Col>
            </Row>
            
            {(currentTask || pomodoroConfig.taskName) && (
              <div style={{ marginBottom: 8, fontSize: 12, color: '#666' }}>
                {currentTask || pomodoroConfig.taskName}
              </div>
            )}

            <div
              style={{
                fontSize: 48,
                fontWeight: 'bold',
                fontFamily: 'monospace',
                margin: '16px 0',
                color: isRunning ? '#ff4d4f' : '#333',
              }}
            >
              {formatTime(remainingTime)}
            </div>

            <Progress
              percent={Math.round(
                (1 - remainingTime / (duration * 60)) * 100
              )}
              showInfo={false}
              strokeColor={isRunning ? '#ff4d4f' : '#52c41a'}
            />

            <div
              style={{ marginTop: 16, display: 'flex', gap: 8, justifyContent: 'center' }}
            >
              {!isRunning && !isPaused && (
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  onClick={handleStartPomodoro}
                >
                  开始
                </Button>
              )}

              {isRunning && (
                <Button icon={<PauseCircleOutlined />} onClick={pauseTimer}>
                  暂停
                </Button>
              )}

              {isPaused && (
                <>
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    onClick={resumeTimer}
                  >
                    继续
                  </Button>
                  <Button icon={<CheckCircleOutlined />} onClick={handleCompletePomodoro}>
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
          resetTimer()
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
      
      {/* 番茄钟统计弹窗 */}
      <Modal
        title={<span><BarChartOutlined /> 番茄钟统计</span>}
        open={showStatsModal}
        onCancel={() => setShowStatsModal(false)}
        footer={null}
        width={500}
      >
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <Card size="small" style={{ textAlign: 'center', background: '#fff2e8' }}>
              <div style={{ fontSize: 24, fontWeight: 'bold', color: '#ff4d4f' }}>{stats.todayCount}</div>
              <div style={{ fontSize: 12, color: '#999' }}>今日番茄</div>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" style={{ textAlign: 'center', background: '#e6f7ff' }}>
              <div style={{ fontSize: 24, fontWeight: 'bold', color: '#1890ff' }}>{stats.todayMinutes}</div>
              <div style={{ fontSize: 12, color: '#999' }}>专注分钟</div>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" style={{ textAlign: 'center', background: '#f6ffed' }}>
              <div style={{ fontSize: 24, fontWeight: 'bold', color: '#52c41a' }}>{stats.weekCount}</div>
              <div style={{ fontSize: 12, color: '#999' }}>本周番茄</div>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" style={{ textAlign: 'center', background: '#f9f0ff' }}>
              <div style={{ fontSize: 24, fontWeight: 'bold', color: '#722ed1' }}>{Math.round(stats.weekMinutes / 60)}</div>
              <div style={{ fontSize: 12, color: '#999' }}>本周小时</div>
            </Card>
          </Col>
        </Row>
        
        <Card size="small" title="本周趋势">
          <ReactECharts option={getWeekChartOption()} style={{ height: 200 }} />
        </Card>
      </Modal>
      
      {/* 资料预览抽屉 */}
      <Drawer
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <FileOutlined style={{ color: currentMaterial?.file_type === 'pdf' ? '#ff4d4f' : '#1890ff' }} />
            <span>{currentMaterial?.name || '资料预览'}</span>
          </div>
        }
        placement="right"
        width={700}
        open={previewVisible}
        onClose={() => setPreviewVisible(false)}
        extra={
          <div style={{ color: '#999', fontSize: 12 }}>
            上传时间：{currentMaterial?.uploadTime}
          </div>
        }
      >
        {previewLoading ? (
          <div style={{ textAlign: 'center', padding: '100px 0', color: '#999' }}>
            加载中...
          </div>
        ) : (
          <div>
            {/* 文件信息卡片 */}
            <Card size="small" style={{ marginBottom: 16, background: '#fafafa' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>{currentMaterial?.name}</div>
                  <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                    类型：{currentMaterial?.file_type?.toUpperCase() || '未知'} · 
                    上传：{currentMaterial?.uploadTime}
                  </div>
                </div>
                <Badge 
                  count={currentMaterial?.file_type?.toUpperCase()} 
                  style={{ 
                    backgroundColor: currentMaterial?.file_type === 'pdf' ? '#ff4d4f' : '#1890ff' 
                  }} 
                />
              </div>
            </Card>
            
            {/* 内容预览区 */}
            <Card 
              title="📄 内容预览" 
              size="small"
              bodyStyle={{ 
                maxHeight: 'calc(100vh - 280px)', 
                overflow: 'auto',
                background: '#fafafa',
                padding: 16
              }}
            >
              {currentMaterial?.file_type === 'pdf' ? (
                <div>
                  <div style={{ 
                    padding: '40px', 
                    textAlign: 'center', 
                    border: '2px dashed #d9d9d9', 
                    borderRadius: 8,
                    marginBottom: 16
                  }}>
                    <FileOutlined style={{ fontSize: 48, color: '#ff4d4f', marginBottom: 16 }} />
                    <div style={{ color: '#666' }}>PDF 文件</div>
                    <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>
                      {currentMaterial?.name}
                    </div>
                  </div>
                  <div style={{ 
                    background: '#fff', 
                    padding: 16, 
                    borderRadius: 8,
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.8,
                    fontSize: 14
                  }}>
                    {previewContent || '正在提取PDF文本内容...'}
                  </div>
                </div>
              ) : (
                <div style={{ 
                  whiteSpace: 'pre-wrap', 
                  lineHeight: 1.8,
                  fontSize: 14,
                  background: '#fff',
                  padding: 16,
                  borderRadius: 8
                }}>
                  {previewContent || '暂无预览内容'}
                </div>
              )}
            </Card>
          </div>
        )}
      </Drawer>
    </Layout>
  )
}
