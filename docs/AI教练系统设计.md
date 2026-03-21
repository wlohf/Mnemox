# AI 学习教练系统 - 完整设计方案

## 📋 目录

1. [核心理念](#核心理念)
2. [系统架构](#系统架构)
3. [数据模型设计](#数据模型设计)
4. [AI 教练引擎](#ai-教练引擎)
5. [实现路线图](#实现路线图)
6. [技术实现](#技术实现)

---

## 🎯 核心理念

### 当前问题
- ✗ 功能孤立，各自为战
- ✗ AI 只能基于资料回答问题
- ✗ 缺乏对用户的深度理解
- ✗ 无法提供个性化指导

### 目标愿景

**打造一个真正懂你的 AI 学习教练**

```
不仅知道你学什么（资料内容）
还知道你怎么学（学习行为）
更知道你是谁（个性特征）
        ↓
提供量身定制的学习指导
```

---

## 🏗️ 系统架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────┐
│                   前端交互层                              │
│  学习页面 | 复习页面 | 错题本 | 统计页面 | AI教练对话    │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────┴─────────────────────────────────┐
│                   API 服务层                              │
│  资料管理 | 学习会话 | 错题管理 | 统计分析 | AI服务       │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────┴─────────────────────────────────┐
│               AI 教练引擎 (核心)                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ 数据聚合 │  │ 用户画像 │  │ 决策引擎 │              │
│  │  模块    │→ │  分析    │→ │  模块    │              │
│  └──────────┘  └──────────┘  └──────────┘              │
│        ↑            ↑            ↓                       │
│        │            │            │                       │
│  ┌─────┴────────────┴────┐  ┌───┴────┐                 │
│  │   全局数据上下文      │  │ 建议生成│                 │
│  └───────────────────────┘  └────────┘                 │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────┴─────────────────────────────────┐
│                  数据存储层                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ 学习资料 │  │ 行为数据 │  │ 用户档案 │              │
│  │ (RAG)    │  │ (时序)   │  │ (画像)   │              │
│  └──────────┘  └──────────┘  └──────────┘              │
└─────────────────────────────────────────────────────────┘
```

### 核心概念

#### 1. 三维数据体系

**维度一：知识维度**（What - 学什么）
- 学习资料内容
- 知识点结构
- 章节关系
- 题目解析

**维度二：行为维度**（How - 怎么学）
- 学习时长分布
- 番茄钟使用情况
- 错题率变化
- 复习频率
- 目标完成度

**维度三：特质维度**（Who - 你是谁）
- 学习风格（视觉型/听觉型/实践型）
- 自控力指数
- 坚持度评分
- 计划执行力
- 最佳学习时段

#### 2. AI 教练的职责

```
传统RAG系统:
    问: "Python装饰器怎么用？"
    答: [基于文档] "装饰器是一种设计模式..."
    
AI教练系统:
    分析上下文:
    - 用户最近在学Python进阶
    - 这个知识点错题率50%
    - 用户通常晚上学习效率高
    - 用户属于"实践型"学习者
    
    个性化回答:
    "根据你的学习记录，装饰器是你的薄弱环节。
    建议今晚8点（你的最佳学习时段）用2个番茄钟：
    1. 先看文档理解概念（15分钟）
    2. 然后做3道练习题巩固（25分钟）
    3. 我帮你准备了相似的错题，明天复习
    
    另外，你最近3天都没完成学习目标了，
    是不是遇到什么困难？要不要调整一下计划？"
```

---

## 📊 数据模型设计

### 1. 学习行为事件表

```python
class LearningEvent(Base):
    """学习行为事件（时序数据）"""
    __tablename__ = "learning_events"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)  # 用户ID（多用户支持）
    event_type = Column(String)  # 事件类型
    event_data = Column(JSON)  # 事件详情
    timestamp = Column(DateTime)
    
    # 事件类型枚举:
    # - study_start: 开始学习
    # - study_end: 结束学习
    # - pomodoro_complete: 完成番茄钟
    # - question_answered: 答题
    # - note_created: 创建笔记
    # - goal_set: 设置目标
    # - goal_achieved: 完成目标
    # - review_session: 复习会话
    # - material_uploaded: 上传资料
```

### 2. 用户画像表

```python
class UserProfile(Base):
    """用户学习画像"""
    __tablename__ = "user_profiles"
    
    user_id = Column(Integer, primary_key=True)
    
    # 基础统计
    total_study_hours = Column(Float, default=0)
    total_pomodoros = Column(Integer, default=0)
    total_questions = Column(Integer, default=0)
    correct_rate = Column(Float, default=0)
    
    # 学习特征
    learning_style = Column(String)  # visual/auditory/kinesthetic
    avg_session_duration = Column(Integer)  # 平均学习时长(分钟)
    preferred_time_slots = Column(JSON)  # 偏好学习时段
    
    # 个性特征评分 (0-100)
    self_control_score = Column(Float, default=50)  # 自控力
    consistency_score = Column(Float, default=50)  # 坚持度
    planning_score = Column(Float, default=50)  # 计划能力
    focus_score = Column(Float, default=50)  # 专注度
    
    # 动态数据
    recent_performance = Column(JSON)  # 近期表现趋势
    weak_points = Column(JSON)  # 薄弱知识点
    strong_points = Column(JSON)  # 擅长领域
    
    # AI 评语
    ai_assessment = Column(Text)  # AI教练的综合评价
    last_updated = Column(DateTime)
```

### 3. 知识点掌握表

```python
class KnowledgePoint(Base):
    """知识点掌握情况"""
    __tablename__ = "knowledge_points"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    material_id = Column(Integer)
    chapter_id = Column(Integer)
    
    knowledge_name = Column(String)  # 知识点名称
    mastery_level = Column(Float)  # 掌握程度 0-100
    
    # 练习统计
    practice_count = Column(Integer)  # 练习次数
    correct_count = Column(Integer)  # 正确次数
    last_reviewed = Column(DateTime)  # 最后复习时间
    
    # 遗忘曲线
    next_review = Column(DateTime)  # 下次复习时间
    review_interval = Column(Integer)  # 复习间隔(天)
    
    # 关联数据
    related_questions = Column(JSON)  # 相关题目ID
    related_notes = Column(JSON)  # 相关笔记ID
```

### 4. 学习目标跟踪表

```python
class GoalTracking(Base):
    """目标完成情况跟踪"""
    __tablename__ = "goal_tracking"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    goal_id = Column(Integer, ForeignKey("goals.id"))
    
    target_date = Column(Date)
    actual_completion = Column(Float)  # 实际完成度
    expected_completion = Column(Float)  # 预期完成度
    
    is_on_track = Column(Boolean)  # 是否按计划进行
    delay_days = Column(Integer)  # 延迟天数
    
    # 行为分析
    daily_progress = Column(JSON)  # 每日进度
    bottlenecks = Column(JSON)  # 瓶颈分析
    timestamp = Column(DateTime)
```

---

## 🤖 AI 教练引擎

### 核心模块

#### 1. 数据聚合模块（Data Aggregator）

```python
class DataAggregator:
    """聚合所有相关数据"""
    
    async def get_learning_context(self, user_id: int) -> dict:
        """获取完整的学习上下文"""
        return {
            # 基础信息
            "user_profile": await self._get_user_profile(user_id),
            
            # 最近活动
            "recent_activities": await self._get_recent_events(user_id, days=7),
            
            # 学习进度
            "goals_progress": await self._get_goals_status(user_id),
            
            # 知识掌握
            "knowledge_map": await self._get_knowledge_mastery(user_id),
            
            # 错题分析
            "error_patterns": await self._analyze_errors(user_id),
            
            # 时间分布
            "time_distribution": await self._get_study_patterns(user_id),
            
            # 资料使用
            "materials_usage": await self._get_materials_stats(user_id),
        }
```

#### 2. 用户画像分析模块（Profile Analyzer）

```python
class ProfileAnalyzer:
    """分析用户特征"""
    
    async def analyze_personality(self, user_id: int) -> dict:
        """分析学习个性"""
        events = await self._get_user_events(user_id)
        
        return {
            # 自控力评分
            "self_control": self._calculate_self_control(events),
            
            # 坚持度评分（是否三天打鱼两天晒网）
            "consistency": self._calculate_consistency(events),
            
            # 计划能力
            "planning": self._calculate_planning_ability(events),
            
            # 学习风格
            "learning_style": self._detect_learning_style(events),
            
            # 最佳学习时段
            "optimal_hours": self._find_optimal_hours(events),
        }
    
    def _calculate_consistency(self, events) -> float:
        """计算坚持度
        
        分析连续学习天数、间断频率
        判断是否"三天打鱼两天晒网"
        """
        # 获取每日学习记录
        daily_study = self._group_by_day(events)
        
        # 计算最长连续学习天数
        max_streak = self._max_continuous_days(daily_study)
        
        # 计算平均连续天数
        avg_streak = self._average_streak(daily_study)
        
        # 计算间断频率
        gap_frequency = self._gap_frequency(daily_study)
        
        # 综合评分 (0-100)
        consistency_score = (
            max_streak * 2 +           # 最长坚持
            avg_streak * 3 +           # 平均坚持
            (100 - gap_frequency * 2)  # 减去间断惩罚
        ) / 6
        
        return min(100, max(0, consistency_score))
```

#### 3. 决策引擎（Decision Engine）

```python
class CoachingEngine:
    """AI教练决策引擎"""
    
    def __init__(self):
        self.aggregator = DataAggregator()
        self.analyzer = ProfileAnalyzer()
        self.llm_provider = get_anythingllm_provider()
    
    async def get_personalized_advice(
        self, 
        user_id: int,
        context: str = ""
    ) -> dict:
        """生成个性化建议"""
        
        # 1. 聚合数据
        context_data = await self.aggregator.get_learning_context(user_id)
        
        # 2. 分析用户特征
        personality = await self.analyzer.analyze_personality(user_id)
        
        # 3. 构建给LLM的提示词
        prompt = self._build_coaching_prompt(
            context_data=context_data,
            personality=personality,
            user_query=context
        )
        
        # 4. 调用LLM生成建议
        response = await self.llm_provider.chat(
            message=prompt,
            mode="chat"
        )
        
        # 5. 结构化响应
        return {
            "advice": response.get("textResponse"),
            "insights": self._extract_insights(context_data),
            "action_items": self._generate_action_items(context_data),
            "warnings": self._detect_problems(context_data),
        }
    
    def _build_coaching_prompt(self, context_data, personality, user_query):
        """构建个性化提示词"""
        
        prompt = f"""你是一位经验丰富的学习教练，现在要为学生提供个性化指导。

【学生档案】
- 总学习时长: {context_data['user_profile']['total_study_hours']} 小时
- 番茄钟完成: {context_data['user_profile']['total_pomodoros']} 个
- 答题正确率: {context_data['user_profile']['correct_rate']}%

【性格特征】
- 自控力: {personality['self_control']}/100
- 坚持度: {personality['consistency']}/100 
  {"⚠️ 注意：该学生有三天打鱼两天晒网的倾向" if personality['consistency'] < 40 else ""}
- 计划能力: {personality['planning']}/100
- 学习风格: {personality['learning_style']}

【近期表现】
- 最近7天学习时长: {self._format_recent_study(context_data['recent_activities'])}
- 目标完成情况: {self._format_goals(context_data['goals_progress'])}
- 薄弱知识点: {', '.join(context_data['knowledge_map']['weak_points'][:3])}

【当前问题】
{user_query if user_query else "请给出当前阶段的学习建议"}

请根据以上信息，作为一位懂他的教练，给出：
1. 对当前学习状态的评价
2. 针对性的改进建议（考虑他的性格特点）
3. 具体的行动计划
4. 鼓励和提醒

注意：
- 如果学生坚持度低，要更多鼓励和设置小目标
- 如果学生自控力强，可以安排更有挑战性的任务
- 根据学习风格推荐合适的学习方法
- 结合最佳学习时段给出时间建议
"""
        return prompt
```

#### 4. 智能提醒系统

```python
class SmartReminder:
    """智能提醒系统"""
    
    async def check_and_remind(self, user_id: int) -> List[dict]:
        """检查并生成提醒"""
        reminders = []
        
        context = await self.aggregator.get_learning_context(user_id)
        
        # 检查学习中断
        if self._is_study_interrupted(context):
            reminders.append({
                "type": "study_break",
                "priority": "high",
                "message": "你已经2天没学习了，是不是遇到什么困难？"
            })
        
        # 检查目标偏离
        if self._is_goal_off_track(context):
            reminders.append({
                "type": "goal_delay",
                "priority": "medium",
                "message": "你的学习进度比计划慢了3天，需要调整计划吗？"
            })
        
        # 检查复习时机
        if self._has_pending_reviews(context):
            reminders.append({
                "type": "review_due",
                "priority": "high",
                "message": "有5个知识点需要复习了，趁还没忘记！"
            })
        
        return reminders
```

---

## 🛣️ 实现路线图

### Phase 1: 数据收集基础（1-2周）

**目标**: 让系统开始收集行为数据

```python
# 1.1 实现事件追踪
class LearningEventTracker:
    """学习事件追踪器"""
    
    async def track_event(self, event_type: str, event_data: dict):
        """记录学习事件"""
        await LearningEvent.create(
            user_id=current_user_id,
            event_type=event_type,
            event_data=event_data,
            timestamp=datetime.now()
        )

# 1.2 在现有功能中埋点
# - 学习会话开始/结束
# - 番茄钟完成
# - 答题记录
# - 资料浏览
# - 笔记创建
```

**具体任务**:
- [x] 创建 `learning_events` 表
- [ ] 实现事件追踪器
- [ ] 在各模块埋点
- [ ] 数据可视化（看到数据在积累）

### Phase 2: 用户画像系统（2-3周）

**目标**: 建立基础的用户分析

```python
# 2.1 每日数据汇总任务
class DailyAggregation:
    """每日数据汇总"""
    
    async def aggregate_daily_data(self, user_id: int):
        """汇总当天的学习数据"""
        events = await self._get_today_events(user_id)
        
        # 计算各项指标
        study_duration = self._calculate_duration(events)
        questions_count = self._count_questions(events)
        correct_rate = self._calculate_accuracy(events)
        
        # 更新用户档案
        await self._update_profile(user_id, {
            "study_duration": study_duration,
            "questions_count": questions_count,
            "correct_rate": correct_rate
        })

# 2.2 性格特征分析
class PersonalityAnalyzer:
    """性格特征分析"""
    
    async def analyze(self, user_id: int):
        """分析用户性格特征"""
        # 计算坚持度（是否三天打鱼两天晒网）
        # 计算自控力（计划执行率）
        # 识别学习风格
        # 找到最佳学习时段
```

**具体任务**:
- [ ] 创建 `user_profiles` 表
- [ ] 实现每日汇总任务
- [ ] 实现性格分析算法
- [ ] 创建用户画像展示页面

### Phase 3: 上下文感知RAG（3-4周）

**目标**: 让RAG问答带上用户上下文

```python
# 3.1 增强版RAG服务
class ContextAwareRAG:
    """上下文感知的RAG服务"""
    
    async def ask_with_context(
        self, 
        user_id: int,
        question: str
    ) -> str:
        """带用户上下文的问答"""
        
        # 获取用户上下文
        context = await self.get_user_context(user_id)
        
        # 增强问题
        enhanced_query = f"""
        【用户背景】
        - 当前学习: {context['current_material']}
        - 薄弱环节: {context['weak_points']}
        - 最近错题: {context['recent_errors']}
        
        【用户问题】
        {question}
        
        【回答要求】
        1. 结合用户的薄弱环节
        2. 引用相关错题
        3. 给出针对性建议
        """
        
        # 调用RAG
        return await self.rag_provider.chat(enhanced_query)
```

**具体任务**:
- [ ] 实现数据聚合器
- [ ] 改造现有 RAG 接口
- [ ] 测试上下文增强效果

### Phase 4: AI教练引擎（4-6周）

**目标**: 实现完整的教练功能

```python
# 4.1 教练对话接口
@router.post("/api/coach/chat")
async def coach_chat(
    message: str,
    user_id: int = Depends(get_current_user)
):
    """与AI教练对话"""
    engine = CoachingEngine()
    return await engine.get_personalized_advice(user_id, message)

# 4.2 智能建议API
@router.get("/api/coach/suggestions")
async def get_suggestions(user_id: int = Depends(get_current_user)):
    """获取个性化建议"""
    engine = CoachingEngine()
    return await engine.generate_suggestions(user_id)

# 4.3 学习报告
@router.get("/api/coach/report")
async def get_report(
    user_id: int = Depends(get_current_user),
    period: str = "week"
):
    """生成学习报告"""
    analyzer = ReportGenerator()
    return await analyzer.generate_report(user_id, period)
```

**具体任务**:
- [ ] 实现教练引擎核心逻辑
- [ ] 设计提示词模板
- [ ] 创建教练对话界面
- [ ] 实现智能提醒
- [ ] 生成学习报告

### Phase 5: 系统整合（2-3周）

**目标**: 打通所有模块

- [ ] 统一数据流
- [ ] 实现功能联动
- [ ] 优化用户体验
- [ ] 性能优化

---

## 💻 技术实现示例

### 示例1: 事件追踪中间件

```python
# backend/app/middleware/event_tracker.py

from fastapi import Request
from app.services.event_tracker import EventTracker

async def track_learning_events(request: Request, call_next):
    """追踪学习事件的中间件"""
    
    # 记录请求开始
    start_time = time.time()
    
    # 执行请求
    response = await call_next(request)
    
    # 判断是否是需要追踪的事件
    if should_track(request.url.path, request.method):
        event_type = extract_event_type(request)
        event_data = await extract_event_data(request, response)
        
        # 异步记录事件（不阻塞响应）
        asyncio.create_task(
            EventTracker.track(event_type, event_data)
        )
    
    return response
```

### 示例2: 教练提示词构建

```python
# backend/app/ai/prompts/coach_prompts.py

class CoachPromptBuilder:
    """教练提示词构建器"""
    
    PERSONALITY_TEMPLATES = {
        "low_consistency": """
        ⚠️ 该学生表现出"三天打鱼两天晒网"的学习模式：
        - 最长连续学习仅{max_streak}天
        - 近30天有{gap_count}次中断
        - 平均每次中断{avg_gap}天
        
        建议策略：
        1. 设置更小的、容易完成的目标
        2. 强调"每天进步一点点"
        3. 多用鼓励，少批评
        4. 帮助建立学习习惯
        """,
        
        "high_self_control": """
        ✅ 该学生展现出优秀的自控力：
        - 目标完成率{completion_rate}%
        - 计划执行准时率{on_time_rate}%
        
        建议策略：
        1. 可以设置更有挑战的目标
        2. 引导深度学习
        3. 培养元认知能力
        """,
    }
    
    def build_prompt(self, context: dict, personality: dict) -> str:
        """构建完整提示词"""
        
        # 选择合适的性格模板
        personality_section = self._select_personality_template(
            personality
        )
        
        # 构建完整提示
        prompt = f"""
{self.SYSTEM_ROLE}

{self._format_user_profile(context)}

{personality_section}

{self._format_recent_data(context)}

{self._format_query(context.get('user_query'))}

{self.RESPONSE_FORMAT}
"""
        return prompt
```

### 示例3: 前端教练对话组件

```typescript
// frontend/src/components/AICoach/CoachChat.tsx

export function CoachChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [userInput, setUserInput] = useState('');
  
  const sendMessage = async () => {
    // 发送给AI教练
    const response = await fetch('/api/coach/chat', {
      method: 'POST',
      body: JSON.stringify({ message: userInput })
    });
    
    const data = await response.json();
    
    // 显示回复
    setMessages([
      ...messages,
      { role: 'user', content: userInput },
      { 
        role: 'coach', 
        content: data.advice,
        insights: data.insights,  // 额外的洞察
        actions: data.action_items  // 行动建议
      }
    ]);
  };
  
  return (
    <div className="coach-chat">
      <div className="messages">
        {messages.map((msg, i) => (
          <ChatMessage key={i} message={msg} />
        ))}
      </div>
      
      {/* 智能建议卡片 */}
      <SmartSuggestions />
      
      {/* 输入框 */}
      <input 
        value={userInput}
        onChange={e => setUserInput(e.target.value)}
        placeholder="向你的AI教练提问..."
      />
    </div>
  );
}
```

---

## 📈 预期效果

### 用户体验升级

**之前**:
```
用户: "Python装饰器怎么用？"
AI: "装饰器是Python中的一种设计模式..."
```

**之后**:
```
用户: "Python装饰器怎么用？"

AI教练: 
"嗨！我注意到你最近在学Python进阶，装饰器确实是个重点。

📊 根据你的学习记录：
- 你在装饰器相关的5道题中错了3道
- 上次学这个知识点是3天前
- 你最擅长通过实践理解概念（你的学习风格）

💡 我的建议：
今晚8-9点（你的最佳学习时段），用1个番茄钟：
1. 先看这个装饰器教程（我帮你找到了）
2. 然后边看边在IDLE里试验
3. 最后做2道练习题

🎯 小目标：
理解3种基本装饰器用法，明天我们聊聊你的理解

⚠️ 友情提醒：
你已经2天没完成学习计划了，今天争取完成这个小目标，
找回学习节奏！💪

需要我详细讲解装饰器的概念吗？"
```

---

## ✅ 总结

### 核心要点

1. **数据是基础** - 必须先收集行为数据
2. **渐进式实现** - 分阶段逐步完善
3. **用户价值驱动** - 每个阶段都要有可见的价值
4. **技术可行** - 全部基于现有技术栈

### 与Obsidian的区别

| 特性 | Obsidian | 我们的系统 |
|------|----------|-----------|
| 核心 | 笔记+双向链接 | 学习+行为分析 |
| AI | 辅助工具 | 核心教练 |
| 数据 | 静态内容 | 动态行为 |
| 目标 | 知识管理 | 学习提升 |

### 下一步行动

1. **立即开始** - Phase 1 的事件追踪
2. **快速迭代** - 每周都有可演示的进展
3. **用户反馈** - 自己用自己的系统学习
4. **持续优化** - 根据实际效果调整

---

<div align="center">

**这就是真正的AI学习教练！**

不只是回答问题，而是真正懂你、陪伴你成长的学习伙伴

</div>
