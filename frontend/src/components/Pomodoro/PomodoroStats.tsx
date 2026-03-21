import ReactECharts from 'echarts-for-react'
import { usePomodoroStore } from '../../stores/pomodoroStore'

export function PomodoroStats() {
    const { getStats } = usePomodoroStore()
    const stats = getStats()

    const chartOption = {
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(255, 255, 255, 0.9)',
            borderColor: 'rgba(0, 0, 0, 0.1)',
            borderWidth: 1,
            textStyle: {
                color: '#1d1d1f',
                fontSize: 12,
            },
            formatter: (params: any) => {
                const data = params[0]
                const date = new Date(data.name)
                const dayName = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][date.getDay()]
                const minutes = stats.weeklyData[data.dataIndex]?.minutes || 0
                return `${dayName}<br/>🍅 ${data.value} 个番茄<br/>⏱️ ${minutes.toFixed(1)} 分钟`
            },
        },
        grid: {
            top: 10,
            right: 10,
            bottom: 20,
            left: 30,
        },
        xAxis: {
            type: 'category',
            data: stats.weeklyData.map((d) => {
                const date = new Date(d.date)
                return ['日', '一', '二', '三', '四', '五', '六'][date.getDay()]
            }),
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: {
                color: '#86868b',
                fontSize: 10,
            },
        },
        yAxis: {
            type: 'value',
            minInterval: 1,
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: {
                lineStyle: {
                    color: 'rgba(0, 0, 0, 0.05)',
                },
            },
            axisLabel: {
                color: '#86868b',
                fontSize: 10,
            },
        },
        series: [
            {
                type: 'bar',
                data: stats.weeklyData.map((d) => d.count),
                barWidth: '50%',
                itemStyle: {
                    color: {
                        type: 'linear',
                        x: 0,
                        y: 0,
                        x2: 0,
                        y2: 1,
                        colorStops: [
                            { offset: 0, color: '#d4a373' },
                            { offset: 1, color: '#e9c46a' },
                        ],
                    },
                    borderRadius: [4, 4, 0, 0],
                },
            },
        ],
    }

    return (
        <div className="glass-card">
            <div className="glass-card-header">
                <span className="glass-card-title">
                    <span>📊</span>
                    番茄统计
                </span>
            </div>
            <div className="glass-card-body">
                {/* Today Stats */}
                <div className="stats-grid" style={{ marginBottom: 16 }}>
                    <div className="stat-item">
                        <div className="stat-value">{stats.todayCount}</div>
                        <div className="stat-label">今日番茄</div>
                    </div>
                    <div className="stat-item">
                        <div className="stat-value">{stats.todayMinutes.toFixed(1)}</div>
                        <div className="stat-label">专注分钟</div>
                    </div>
                    <div className="stat-item">
                        <div className="stat-value">{stats.weekCount}</div>
                        <div className="stat-label">本周番茄</div>
                    </div>
                    <div className="stat-item">
                        <div className="stat-value">{(stats.weekMinutes / 60).toFixed(1)}</div>
                        <div className="stat-label">本周小时</div>
                    </div>
                </div>

                {/* Weekly Chart */}
                <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 8 }}>
                        本周趋势
                    </div>
                    <ReactECharts
                        option={chartOption}
                        style={{ height: 120 }}
                        opts={{ renderer: 'svg' }}
                    />
                </div>
            </div>
        </div>
    )
}
