import { Card, Row, Col } from 'antd'

export function Statistics() {
  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>统计分析</h1>
      
      <Row gutter={[16, 16]}>
        <Col span={12}>
          <Card title="学习时间统计">
            <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
              图表将在后续实现
            </div>
          </Card>
        </Col>
        
        <Col span={12}>
          <Card title="掌握程度分析">
            <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
              图表将在后续实现
            </div>
          </Card>
        </Col>
        
        <Col span={12}>
          <Card title="番茄钟统计">
            <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
              图表将在后续实现
            </div>
          </Card>
        </Col>
        
        <Col span={12}>
          <Card title="错题分布">
            <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
              图表将在后续实现
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
