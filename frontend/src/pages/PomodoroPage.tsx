import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, Col, Input, InputNumber, Modal, Row, Segmented, Statistic, Upload, message } from 'antd'
import {
  BarChartOutlined,
  DeleteOutlined,
  PauseCircleFilled,
  PictureOutlined,
  PlayCircleFilled,
  ReloadOutlined,
  StopFilled,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { usePomodoroStore, type DateRange } from '../stores/pomodoroStore'
import { PageShell } from '../components/PageShell'
import { getCurrentQuote, type MotivationQuote } from '../services/motivationApi'

const MAX_BACKGROUND_IMAGE_SIZE = 3 * 1024 * 1024

type PomodoroStageStyle = CSSProperties & {
  '--mnemox-pomodoro-background'?: string
}

export function PomodoroPage() {
  const navigate = useNavigate()
  const {
    getStats,
    getCumulativeStats,
    getTaskDistribution,
    isRunning,
    isPaused,
    duration,
    remainingTime,
    currentTask,
    timerMode,
    breakDuration,
    startTimer,
    startBreakTimer,
    setBreakDuration,
    pauseTimer,
    resumeTimer,
    completeTimer,
    resetTimer,
    backgroundImage,
    setBackgroundImage,
  } = usePomodoroStore()

  const [range, setRange] = useState<DateRange>('week')
  const [taskName, setTaskName] = useState('专注学习')
  const [focusMinutes, setFocusMinutes] = useState(25)
  const [stopReasonModalVisible, setStopReasonModalVisible] = useState(false)
  const [stopReason, setStopReason] = useState('')
  const [quote, setQuote] = useState<MotivationQuote | null>(null)

  useEffect(() => {
    void getCurrentQuote().then(setQuote).catch(() => undefined)
  }, [])

  const stats = getStats()
  const cumulative = getCumulativeStats()
  const distribution = getTaskDistribution(range)

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  const handleStart = () => {
    const safeName = taskName.trim() || '专注学习'
    startTimer(safeName, focusMinutes)
    message.success('番茄钟已启动')
  }

  const handleStop = () => {
    if (timerMode === 'break') {
      resetTimer()
      message.success('休息已结束')
      return
    }
    setStopReasonModalVisible(true)
  }

  const confirmStop = () => {
    completeTimer(undefined, { startBreak: false })
    message.success(stopReason.trim() ? '已记录本次停止原因' : '番茄钟已停止')
    setStopReasonModalVisible(false)
    setStopReason('')
  }

  const handleTakeBreak = () => {
    startBreakTimer(breakDuration)
    message.success('开始休息')
  }

  const handleBackgroundUpload = (file: File) => {
    if (!file.type.startsWith('image/')) {
      message.warning('请选择图片文件')
      return false
    }

    if (file.size > MAX_BACKGROUND_IMAGE_SIZE) {
      message.warning('背景图不能超过 3MB')
      return false
    }

    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result
      if (typeof result !== 'string') {
        message.error('背景图读取失败')
        return
      }

      try {
        setBackgroundImage(result)
        message.success('番茄背景已更新')
      } catch {
        message.error('背景图保存失败，请换一张更小的图片')
      }
    }
    reader.onerror = () => message.error('背景图读取失败')
    reader.readAsDataURL(file)
    return false
  }

  const handleResetBackground = () => {
    setBackgroundImage(null)
    message.success('已恢复默认背景')
  }

  const weekOption = useMemo(() => ({
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const data = params[0]
        const dayData = stats.weeklyData[data.dataIndex]
        const minutes = dayData?.minutes || 0
        return `${['日', '一', '二', '三', '四', '五', '六'][new Date(dayData?.date).getDay()] || ''}<br/>番茄 ${data.value} 个<br/>${minutes.toFixed(1)} 分钟`
      },
    },
    grid: { top: 10, right: 10, bottom: 20, left: 30 },
    xAxis: {
      type: 'category',
      data: stats.weeklyData.map((d) => ['日', '一', '二', '三', '四', '五', '六'][new Date(d.date).getDay()]),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: 'var(--text-secondary)', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: 'var(--border-light)' } },
      axisLabel: { color: 'var(--text-secondary)', fontSize: 10 },
    },
    series: [{
      type: 'bar',
      data: stats.weeklyData.map((d) => d.count),
      barWidth: '50%',
      itemStyle: {
        color: '#eef4f1',
        borderRadius: [4, 4, 0, 0],
      },
    }],
  }), [stats.weeklyData])

  const pieOption = useMemo(() => ({
    tooltip: {
      trigger: 'item',
      formatter: (params: any) => {
        const minutes = params.data.minutes as number
        const hours = minutes / 60
        const display = hours >= 1 ? `${hours.toFixed(1)}h` : `${minutes.toFixed(1)}m`
        return `${params.name}<br/>${display}<br/>番茄 ${params.data.count} 个 (${params.percent}%)`
      },
    },
    legend: {
      orient: 'vertical',
      right: 10,
      top: 'center',
      textStyle: { fontSize: 11, color: 'var(--text-secondary)' },
    },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['35%', '50%'],
      data: distribution.map((t) => ({
        value: t.minutes,
        name: t.taskName,
        minutes: t.minutes,
        count: t.count,
        itemStyle: { color: t.color },
      })),
      label: { show: false },
      itemStyle: { borderColor: 'var(--bg-surface)', borderWidth: 2 },
    }],
  }), [distribution])

  const totalDuration = Math.max(1, duration * 60)
  const progress = isRunning || isPaused ? Math.max(0, Math.min(1, 1 - remainingTime / totalDuration)) : 0
  const radius = 132
  const circumference = 2 * Math.PI * radius
  const strokeDashoffset = circumference - progress * circumference
  const isBreak = timerMode === 'break'
  const statusLabel = isRunning || isPaused ? (isBreak ? '休息中' : '专注中') : '准备开始'
  const activeTask = isRunning || isPaused ? currentTask || (isBreak ? '休息' : '专注学习') : taskName
  const stageStyle: PomodoroStageStyle | undefined = backgroundImage
    ? { '--mnemox-pomodoro-background': `url("${backgroundImage}")` }
    : undefined

  return (
    <PageShell
      title="番茄专注"
      onBack={() => navigate('/')}
      maxWidth={1280}
      rightExtra={(
        <div className="mnemox-pomodoro-header-actions">
          <Upload
            accept="image/png,image/jpeg,image/gif,image/webp,image/bmp"
            showUploadList={false}
            beforeUpload={handleBackgroundUpload}
          >
            <Button icon={<PictureOutlined />}>{backgroundImage ? '更换背景' : '上传背景'}</Button>
          </Upload>
          {backgroundImage && (
            <Button icon={<DeleteOutlined />} onClick={handleResetBackground}>
              默认背景
            </Button>
          )}
          <Segmented
            value={range}
            onChange={(value) => setRange(value as DateRange)}
            options={[
              { label: '日', value: 'day' },
              { label: '周', value: 'week' },
              { label: '月', value: 'month' },
              { label: '全部', value: 'all' },
            ]}
          />
        </div>
      )}
    >
      <section className="mnemox-pomodoro-stage" style={stageStyle}>
        <div className="mnemox-pomodoro-quote">
          <span className="mnemox-pomodoro-quote-mark">“</span>
          <p>{quote?.content || '如果一个人不知道他要驶向哪个码头，那么任何风都不会是顺风。'}</p>
          {quote?.author && <small>{quote.author}</small>}
        </div>

        <div className="mnemox-pomodoro-ring" aria-label="番茄倒计时">
          <svg viewBox="0 0 320 320" aria-hidden="true">
            <circle cx="160" cy="160" r={radius} className="mnemox-pomodoro-ring-track" />
            <circle
              cx="160"
              cy="160"
              r={radius}
              className="mnemox-pomodoro-ring-progress"
              strokeDasharray={circumference}
              strokeDashoffset={strokeDashoffset}
            />
          </svg>
          <div className="mnemox-pomodoro-time">
            <strong>{formatTime(remainingTime || focusMinutes * 60)}</strong>
            <span>{statusLabel}</span>
          </div>
        </div>

        <div className="mnemox-pomodoro-task">{activeTask}</div>

        {!isRunning && !isPaused && (
          <div className="mnemox-pomodoro-setup">
            <Input
              value={taskName}
              onChange={(event) => setTaskName(event.target.value)}
              placeholder="本轮专注任务"
            />
            <InputNumber
              min={1}
              max={120}
              value={focusMinutes}
              onChange={(value) => {
                const next = Number(value)
                if (Number.isFinite(next)) setFocusMinutes(Math.max(1, Math.min(120, next)))
              }}
              addonAfter="分钟"
            />
          </div>
        )}

        <div className="mnemox-pomodoro-controls">
          {!isRunning && !isPaused ? (
            <>
              <Button type="primary" size="large" icon={<PlayCircleFilled />} onClick={handleStart}>
                开始专注
              </Button>
              <Button size="large" icon={<ReloadOutlined />} onClick={handleTakeBreak}>
                休息 {breakDuration} 分钟
              </Button>
              <InputNumber
                min={1}
                max={60}
                value={breakDuration}
                onChange={(value) => {
                  const next = Number(value)
                  if (Number.isFinite(next)) setBreakDuration(Math.max(1, Math.min(60, next)))
                }}
                addonAfter="休息"
              />
            </>
          ) : (
            <>
              {isPaused ? (
                <Button type="primary" size="large" shape="circle" icon={<PlayCircleFilled />} onClick={resumeTimer} aria-label="继续" />
              ) : (
                <Button size="large" shape="circle" icon={<PauseCircleFilled />} onClick={pauseTimer} aria-label="暂停" />
              )}
              <Button danger size="large" shape="circle" icon={<StopFilled />} onClick={handleStop} aria-label="停止" />
            </>
          )}
        </div>
      </section>

      <Row gutter={[16, 16]} style={{ marginTop: 18 }}>
        <Col xs={12} md={6}>
          <Card size="small"><Statistic title="累计番茄" value={cumulative.totalCount} suffix="个" /></Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small"><Statistic title="累计时长" value={cumulative.totalHours.toFixed(1)} suffix="小时" /></Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small"><Statistic title="日均分钟" value={cumulative.dailyAverageMinutes.toFixed(1)} suffix="分钟" /></Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small"><Statistic title="活跃天数" value={cumulative.activeDays} suffix="天" /></Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={14}>
          <Card size="small" title={<span><BarChartOutlined /> 任务时长分布</span>}>
            {distribution.length === 0 ? (
              <div style={{ textAlign: 'center', color: 'var(--text-tertiary)', padding: '48px 0' }}>暂无数据，先完成一个番茄吧</div>
            ) : (
              <ReactECharts option={pieOption} style={{ height: 300 }} />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card size="small" title="本周趋势">
            <ReactECharts option={weekOption} style={{ height: 300 }} />
          </Card>
        </Col>
      </Row>

      <Modal
        title="停止专注"
        open={stopReasonModalVisible}
        onOk={confirmStop}
        onCancel={() => setStopReasonModalVisible(false)}
        okText="确认停止"
        okButtonProps={{ danger: true }}
      >
        <p style={{ color: 'var(--text-secondary)' }}>请输入提前停止的原因（可选）：</p>
        <Input.TextArea
          value={stopReason}
          onChange={(event) => setStopReason(event.target.value)}
          placeholder="例如：被打断、任务已完成..."
          rows={3}
        />
      </Modal>
    </PageShell>
  )
}
