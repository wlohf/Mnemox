import { useMemo, useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Row, Col, Statistic, Segmented, Button, Modal, Input, InputNumber, message } from 'antd'
import { PlayCircleFilled, PauseCircleFilled, StopFilled } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { usePomodoroStore, type DateRange } from '../stores/pomodoroStore'
import { PageShell } from '../components/PageShell'

export function PomodoroPage() {
  const navigate = useNavigate()
  const { 
    getStats, getCumulativeStats, getTaskDistribution,
    isRunning, isPaused, duration, remainingTime, timerMode, breakDuration,
    startTimer, startBreakTimer, setBreakDuration, pauseTimer, resumeTimer, completeTimer, resetTimer, tick
  } = usePomodoroStore()
  
  const [range, setRange] = useState<DateRange>('week')
  const [stopReasonModalVisible, setStopReasonModalVisible] = useState(false)
  const [stopReason, setStopReason] = useState('')

  useEffect(() => {
    let timer: number
    if (isRunning && !isPaused) {
      timer = window.setInterval(() => {
        tick()
      }, 1000)
    }
    return () => clearInterval(timer)
  }, [isRunning, isPaused, tick])

  const stats = getStats()
  const cumulative = getCumulativeStats()
  const distribution = getTaskDistribution(range)

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  const handleStart = () => {
    startTimer('专注学习', 25)
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
    // We treat stopping early as completion of elapsed time
    completeTimer(undefined, { startBreak: false })
    message.success('番茄钟已停止')
    setStopReasonModalVisible(false)
    setStopReason('')
  }

  const handleTakeBreak = () => {
    startBreakTimer(breakDuration)
    message.success('开始休息')
  }

  const weekOption = useMemo(() => ({
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const data = params[0]
        const dayData = stats.weeklyData[data.dataIndex]
        const minutes = dayData?.minutes || 0
        return `${['日', '一', '二', '三', '四', '五', '六'][new Date(dayData?.date).getDay()] || ''}<br/>🍅 ${data.value} 个<br/>⏱️ ${minutes.toFixed(1)} 分钟`
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
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
      axisLabel: { color: 'var(--text-secondary)', fontSize: 10 },
    },
    series: [{
      type: 'bar',
      data: stats.weeklyData.map((d) => d.count),
      barWidth: '50%',
      itemStyle: {
        color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'var(--brand-400)' }, { offset: 1, color: 'var(--brand-600)' }] },
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
        return `${params.name}<br/>⏱️ ${display}<br/>🍅 ${params.data.count} 个 (${params.percent}%)`
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

  // Timer SVG logic
  const totalDuration = duration * 60
  const progress = isRunning || isPaused ? Math.max(0, 1 - remainingTime / totalDuration) : 0
  const radius = 120
  const circumference = 2 * Math.PI * radius
  const strokeDashoffset = circumference - progress * circumference

  const isBreak = timerMode === 'break'
  const primaryColor = isBreak ? 'var(--teal-400)' : 'var(--brand-500)'
  const glowColor = isBreak ? 'rgba(45, 212, 191, 0.4)' : 'rgba(99, 102, 241, 0.4)'
  const containerBg = isRunning && !isPaused ? (isBreak ? 'rgba(45, 212, 191, 0.05)' : 'rgba(99, 102, 241, 0.05)') : 'var(--bg-surface)'

  return (
    <PageShell 
      title="番茄专注" 
      onBack={() => navigate('/')} 
      maxWidth={1000}
      rightExtra={
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
      }
    >
      <div style={{ 
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', 
        background: containerBg, borderRadius: 'var(--radius-xl)', padding: '48px 0', marginBottom: 32,
        border: '1px solid var(--border-light)', transition: 'background 0.5s ease', position: 'relative', overflow: 'hidden'
      }}>
        {/* Background glow when running */}
        {isRunning && !isPaused && (
          <div style={{
            position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', width: 400, height: 400, borderRadius: '50%',
            background: primaryColor, filter: 'blur(100px)', opacity: 0.15, animation: 'pulse 4s ease-in-out infinite alternate', pointerEvents: 'none'
          }} />
        )}

        {/* Timer UI */}
        <div style={{ position: 'relative', width: 280, height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 32 }}>
          {/* SVG Progress Ring */}
          <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', transform: 'rotate(-90deg)' }}>
            <circle cx="140" cy="140" r={radius} fill="transparent" stroke="rgba(255,255,255,0.05)" strokeWidth="8" />
            <circle cx="140" cy="140" r={radius} fill="transparent" stroke={primaryColor} strokeWidth="8" strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={strokeDashoffset} style={{ transition: 'stroke-dashoffset 1s linear, stroke 0.3s ease' }} />
          </svg>

          {/* Time Display */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', zIndex: 1, textShadow: `0 0 20px ${glowColor}` }}>
            <div style={{ fontSize: 64, fontWeight: 700, fontFamily: 'Space Grotesk', lineHeight: 1, letterSpacing: '-0.02em', fontVariantNumeric: 'tabular-nums', color: 'var(--text-primary)' }}>
              {formatTime(remainingTime || (25 * 60))}
            </div>
            <div style={{ fontSize: 16, color: 'var(--text-secondary)', marginTop: 8, fontWeight: 500 }}>
              {isRunning || isPaused ? (isBreak ? '休息中' : '专注中') : '准备就绪'}
            </div>
          </div>
        </div>

        {/* Controls */}
        <div style={{ display: 'flex', gap: 24, alignItems: 'center', zIndex: 1 }}>
          {!isRunning && !isPaused ? (
            <>
              <Button type="primary" size="large" shape="round" icon={<PlayCircleFilled />} onClick={handleStart} style={{ height: 52, padding: '0 40px', fontSize: 16 }}>
                开始专注
              </Button>
              <Button size="large" shape="round" onClick={handleTakeBreak} style={{ height: 52, padding: '0 32px' }}>
                休息一下 ({breakDuration}m)
              </Button>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-secondary)', fontSize: 13 }}>
                <span>休息时长</span>
                <InputNumber
                  min={1}
                  max={60}
                  size="small"
                  value={breakDuration}
                  onChange={(value) => {
                    if (value !== null && value >= 1) setBreakDuration(value)
                  }}
                  style={{ width: 76 }}
                />
                <span>分钟</span>
              </div>
            </>
          ) : (
            <>
              {isPaused ? (
                <Button type="primary" size="large" shape="circle" icon={<PlayCircleFilled />} onClick={resumeTimer} style={{ width: 64, height: 64, fontSize: 28 }} />
              ) : (
                <Button size="large" shape="circle" icon={<PauseCircleFilled />} onClick={pauseTimer} style={{ width: 64, height: 64, fontSize: 28, background: 'rgba(255,255,255,0.1)', border: '1px solid var(--border-light)', color: 'var(--text-primary)' }} />
              )}
              <Button danger size="large" shape="circle" icon={<StopFilled />} onClick={handleStop} style={{ width: 64, height: 64, fontSize: 24, background: 'rgba(251, 113, 133, 0.1)', border: 'none', color: 'var(--error)' }} />
            </>
          )}
        </div>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Card size="small"><Statistic title="累计番茄" value={cumulative.totalCount} suffix="个" valueStyle={{ color: 'var(--text-primary)' }} /></Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small"><Statistic title="累计时长" value={cumulative.totalHours.toFixed(1)} suffix="小时" valueStyle={{ color: 'var(--text-primary)' }} /></Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small"><Statistic title="日均分钟" value={cumulative.dailyAverageMinutes.toFixed(1)} suffix="分钟" valueStyle={{ color: 'var(--text-primary)' }} /></Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small"><Statistic title="活跃天数" value={cumulative.activeDays} suffix="天" valueStyle={{ color: 'var(--text-primary)' }} /></Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={14}>
          <Card size="small" title="任务时长分布">
            {distribution.length === 0 ? (
              <div style={{ textAlign: 'center', color: 'var(--text-tertiary)', padding: '48px 0' }}>暂无数据，先完成一个番茄吧</div>
            ) : (
              <ReactECharts option={pieOption} style={{ height: 320 }} />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card size="small" title="本周趋势">
            <ReactECharts option={weekOption} style={{ height: 320 }} />
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
          onChange={(e) => setStopReason(e.target.value)}
          placeholder="例如：被打断、任务已完成..."
          rows={3}
        />
      </Modal>
    </PageShell>
  )
}
