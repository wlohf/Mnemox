import { Card, Row, Col, Statistic, Calendar } from 'antd'
import {
  BookOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  ExceptionOutlined,
} from '@ant-design/icons'

export function Dashboard() {
  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>仪表盘</h1>
      
      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="今日学习时间"
              value={0}
              suffix="分钟"
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="今日完成番茄"
              value={0}
              suffix="个"
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="待复习项"
              value={0}
              suffix="项"
              prefix={<BookOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="待处理错题"
              value={0}
              suffix="道"
              prefix={<ExceptionOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* 学习日历 */}
      <Card title="学习日历" style={{ marginBottom: 24 }}>
        <Calendar fullscreen={false} />
      </Card>

      {/* 今日任务 */}
      <Card title="今日任务">
        <p style={{ color: '#999' }}>暂无任务</p>
      </Card>
    </div>
  )
}
