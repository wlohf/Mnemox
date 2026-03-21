# 学习助手系统设计文档

## 1. 项目概述

### 1.1 目标
构建一个基于认知科学学习方法的个人学习助手，通过 AI 辅导实现：
- **费曼学习法** - 用自己的话解释知识点
- **间隔复习** - 基于艾宾浩斯遗忘曲线
- **主动回忆** - 苏格拉底式提问
- **OKR 目标拆解** - 将大目标分解为可执行任务
- **番茄工作法** - 时间管理和统计
- **进度可视化** - 学习效果追踪

### 1.2 核心理念
- **逼迫输出** > 被动输入
- **间隔复习** > 集中突击
- **能力反馈** > 行为打卡
- **对症下药** > 盲目刷题

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     前端 (React + TypeScript)                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ 学习界面  │ │ 对话交互  │ │ 进度看板  │ │ 笔记编辑  │        │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                     │
│  │ 错题本   │ │ 复习日历  │ │ 番茄钟    │                     │
│  └──────────┘ └──────────┘ └──────────┘                     │
└─────────────────────────┬───────────────────────────────────┘
                          │ REST API
┌─────────────────────────▼───────────────────────────────────┐
│                  后端 (Python FastAPI)                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                    API 路由层                        │    │
│  │  /materials  /goals  /study  /review  /pomodoro     │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ 资料管理  │ │ 学习引擎  │ │ 复习调度  │ │ 进度统计  │        │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────────┐     │
│  │ 错题管理  │ │ 番茄钟   │ │      AI 服务适配层       │     │
│  └──────────┘ └──────────┘ └──────────────────────────┘     │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                      数据层                                  │
│  ┌──────────────────┐  ┌──────────────────────────────┐     │
│  │  SQLite 数据库    │  │  文件存储（学习资料）         │     │
│  └──────────────────┘  └──────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 数据库设计

### 3.1 核心表结构

#### materials (学习资料)
```sql
CREATE TABLE materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    file_path TEXT,
    file_type TEXT,          -- pdf, docx, md, txt
    content TEXT,            -- 解析后的文本内容
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### chapters (章节/知识点)
```sql
CREATE TABLE chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER REFERENCES materials(id),
    parent_id INTEGER REFERENCES chapters(id),  -- 支持层级结构
    title TEXT NOT NULL,
    content TEXT,
    order_index INTEGER,
    mastery_level REAL DEFAULT 0,  -- 掌握程度 0-100
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### goals (学习目标)
```sql
CREATE TABLE goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER REFERENCES materials(id),
    title TEXT NOT NULL,
    description TEXT,
    target_level TEXT,       -- 目标掌握程度
    deadline DATE,
    status TEXT DEFAULT 'active',  -- active, completed, paused
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### tasks (OKR 任务)
```sql
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id),
    chapter_id INTEGER REFERENCES chapters(id),
    title TEXT NOT NULL,
    task_type TEXT,          -- learn, review, practice, summarize
    planned_date DATE,
    status TEXT DEFAULT 'pending',
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### study_sessions (学习会话)
```sql
CREATE TABLE study_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER REFERENCES chapters(id),
    task_id INTEGER REFERENCES tasks(id),
    session_type TEXT,       -- new_learning, review, practice
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    summary TEXT,            -- 用户总结
    ai_feedback TEXT,        -- AI 反馈
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### conversations (对话记录)
```sql
CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES study_sessions(id),
    role TEXT,               -- user, assistant
    content TEXT,
    message_type TEXT,       -- review, explain, feynman, socratic, quiz
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### questions (题目)
```sql
CREATE TABLE questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER REFERENCES chapters(id),
    question_type TEXT,      -- choice, fill_blank, short_answer, essay
    content TEXT NOT NULL,
    options JSON,            -- 选择题选项
    answer TEXT,
    explanation TEXT,
    difficulty INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### quiz_records (答题记录)
```sql
CREATE TABLE quiz_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER REFERENCES questions(id),
    session_id INTEGER REFERENCES study_sessions(id),
    user_answer TEXT,
    is_correct BOOLEAN,
    time_spent INTEGER,      -- 答题耗时（秒）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### wrong_questions (错题本)
```sql
CREATE TABLE wrong_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER REFERENCES questions(id),
    first_wrong_at TIMESTAMP,
    last_wrong_at TIMESTAMP,
    wrong_count INTEGER DEFAULT 1,
    mastery_status TEXT DEFAULT 'not_mastered',
    next_review_at TIMESTAMP,
    review_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### review_schedule (复习计划 - SM-2算法)
```sql
CREATE TABLE review_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type TEXT,          -- chapter, question
    item_id INTEGER,
    scheduled_date DATE,
    interval_days INTEGER,   -- 当前间隔天数
    ease_factor REAL DEFAULT 2.5,  -- SM-2 难度因子
    repetitions INTEGER DEFAULT 0,
    last_quality INTEGER,    -- 上次复习质量 0-5
    status TEXT DEFAULT 'pending',
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### pomodoros (番茄钟记录)
```sql
CREATE TABLE pomodoros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES study_sessions(id),
    chapter_id INTEGER REFERENCES chapters(id),
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    duration INTEGER DEFAULT 25,  -- 分钟
    completed BOOLEAN DEFAULT FALSE,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### notes (笔记)
```sql
CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER REFERENCES materials(id),
    chapter_id INTEGER REFERENCES chapters(id),
    title TEXT,
    content TEXT,            -- Markdown 内容
    note_type TEXT,          -- general, summary, review
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### daily_stats (每日统计)
```sql
CREATE TABLE daily_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE UNIQUE,
    study_time INTEGER DEFAULT 0,         -- 总学习时间（分钟）
    pomodoro_count INTEGER DEFAULT 0,
    questions_attempted INTEGER DEFAULT 0,
    questions_correct INTEGER DEFAULT 0,
    chapters_reviewed INTEGER DEFAULT 0,
    new_chapters_learned INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. 学习流程设计

### 4.1 完整学习流程

```
开始学习会话
    │
    ▼
┌─────────────────┐
│ 1. 复习检查      │ ← 检查是否有到期需复习的内容
└────────┬────────┘
         │ 有复习任务
         ▼
┌─────────────────┐
│ 2. 间隔复习      │ ← AI 提问之前学过的知识点
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 3. 新知识引入    │ ← 介绍本章主题，建立联系
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 4. 概念讲解      │ ← AI 用大白话解释新概念
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 5. 费曼输出      │ ← 用户用自己的话解释
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 6. 苏格拉底提问  │ ← 深入追问，检验理解
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 7. 练习题       │ ← 根据知识点生成题目
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 8. 错题分析     │ ← 记录错题，安排复习
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 9. 当日总结     │ ← 用户用几句话总结
└────────┬────────┘
         │
         ▼
结束会话，更新进度
```

### 4.2 间隔复习算法 (SM-2)

```python
def calculate_next_review(quality: int, repetitions: int, ease_factor: float, interval: int):
    """
    SM-2 间隔复习算法（Anki 使用的算法）
    
    quality: 回答质量 0-5
        0 - 完全不记得
        1 - 错误，但看到答案后想起来
        2 - 错误，但答案感觉熟悉
        3 - 正确，但很费力
        4 - 正确，有些犹豫
        5 - 正确，很轻松
    """
    if quality < 3:
        # 回答不合格，重置
        repetitions = 0
        interval = 1
    else:
        # 回答合格，增加间隔
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 6
        else:
            interval = int(interval * ease_factor)
        repetitions += 1
    
    # 更新难度因子
    ease_factor = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease_factor = max(1.3, ease_factor)  # 最小值 1.3
    
    return {
        'interval': interval,
        'repetitions': repetitions,
        'ease_factor': ease_factor,
        'next_review_date': today + timedelta(days=interval)
    }
```

---

## 5. AI 服务适配层

### 5.1 统一接口设计

```python
from abc import ABC, abstractmethod
from typing import List, AsyncIterator

class AIProvider(ABC):
    """AI 提供商统一接口"""
    
    @abstractmethod
    async def chat(self, messages: List[dict], system_prompt: str = None) -> str:
        """同步对话"""
        pass
    
    @abstractmethod
    async def chat_stream(self, messages: List[dict], system_prompt: str = None) -> AsyncIterator[str]:
        """流式对话"""
        pass
```

### 5.2 支持的 AI 提供商

```python
class OpenAIProvider(AIProvider):
    """OpenAI (GPT-4, GPT-3.5)"""
    pass

class ClaudeProvider(AIProvider):
    """Anthropic Claude"""
    pass

class GeminiProvider(AIProvider):
    """Google Gemini"""
    pass

class QwenProvider(AIProvider):
    """阿里通义千问"""
    pass
```

### 5.3 Prompt 模板设计

```python
PROMPTS = {
    "review": """你是一位学习助手，现在要帮助用户复习之前学过的内容。
请提出 2-3 个简短问题，检测用户是否还记得相关知识点。
问题应该简洁，能快速回答。""",
    
    "explain": """你是一位善于用大白话解释复杂概念的老师。
请用简单易懂的语言解释知识点，使用类比和例子。
避免使用过于专业的术语。""",
    
    "feynman": """用户刚学完一个知识点，现在需要用自己的话解释。
请评估用户的解释：
1. 是否抓住了核心概念
2. 是否有理解错误
3. 是否遗漏重要内容
如果有问题，用引导性问题帮助用户思考，不要直接告诉答案。""",
    
    "socratic": """请用苏格拉底式提问法，通过追问帮助用户深入思考。
不要直接给答案，而是通过问题引导用户发现答案。""",
    
    "quiz": """根据学习资料生成练习题。
题目要有区分度，能检验用户是否真正理解了知识点。
题型可以是选择题、填空题、简答题等。""",
    
    "summary": """引导用户总结今天所学，帮助他提炼关键点。
如果用户的总结有遗漏，温和地提醒。"""
}
```

---

## 6. API 设计

### 6.1 资料管理 API
```
POST   /api/materials              上传资料
GET    /api/materials              获取资料列表
GET    /api/materials/{id}         获取资料详情
DELETE /api/materials/{id}         删除资料
POST   /api/materials/{id}/parse   解析资料（提取章节）
```

### 6.2 学习目标 API
```
POST   /api/goals                  创建学习目标
GET    /api/goals                  获取目标列表
PUT    /api/goals/{id}             更新目标
POST   /api/goals/{id}/generate-okr AI 生成 OKR 拆解
GET    /api/goals/{id}/progress    获取目标进度
```

### 6.3 学习会话 API
```
POST   /api/sessions               开始学习会话
GET    /api/sessions/{id}          获取会话详情
POST   /api/sessions/{id}/chat     发送消息（AI 对话）
PUT    /api/sessions/{id}/summary  提交学习总结
POST   /api/sessions/{id}/end      结束会话
```

### 6.4 复习 API
```
GET    /api/review/today           获取今日复习任务
POST   /api/review/{id}/complete   完成复习，更新调度
GET    /api/review/calendar        获取复习日历
```

### 6.5 错题本 API
```
GET    /api/wrong-questions        获取错题列表
GET    /api/wrong-questions/by-type     按题型分类
GET    /api/wrong-questions/by-chapter  按章节分类
PUT    /api/wrong-questions/{id}/master 标记已掌握
```

### 6.6 番茄钟 API
```
POST   /api/pomodoro/start         开始番茄钟
PUT    /api/pomodoro/{id}/complete 完成番茄钟
PUT    /api/pomodoro/{id}/cancel   取消番茄钟
GET    /api/pomodoro/statistics    番茄钟统计
```

### 6.7 统计分析 API
```
GET    /api/statistics/overview    总览数据
GET    /api/statistics/mastery     掌握程度分析
GET    /api/statistics/time        时间统计
GET    /api/statistics/weakness    薄弱点分析
```

---

## 7. 前端页面设计

### 7.1 页面列表

1. **仪表盘 (Dashboard)**
   - 今日学习计划
   - 待复习项提醒
   - 整体进度概览
   - 学习日历

2. **学习空间 (Study)**
   - AI 对话界面
   - 学习资料阅读
   - 番茄钟计时器
   - 快捷操作

3. **复习中心 (Review)**
   - 今日待复习列表
   - 复习卡片（类似 Anki）
   - 复习质量反馈

4. **错题本 (Wrong Questions)**
   - 错题列表
   - 按章节/题型筛选
   - 针对性练习

5. **统计分析 (Statistics)**
   - 学习时间统计
   - 掌握程度热力图
   - 错题分布图
   - 薄弱点分析

6. **资料管理 (Materials)**
   - 资料列表
   - 上传新资料
   - 目标设定

7. **笔记 (Notes)**
   - Markdown 编辑器
   - 笔记列表
   - 关联知识点

8. **设置 (Settings)**
   - AI 提供商配置
   - 番茄钟时长
   - 复习提醒

---

## 8. 开发计划

### Phase 1: 基础框架 (MVP)
- [ ] 后端项目搭建（FastAPI + SQLite）
- [ ] 数据库模型和表创建
- [ ] AI 服务适配层（先支持 OpenAI）
- [ ] 前端项目搭建（React + TypeScript）
- [ ] 基础页面框架

### Phase 2: 核心学习功能
- [ ] 资料上传和解析
- [ ] 学习目标设定和 OKR 拆解
- [ ] 学习会话流程（复习→讲解→费曼→练习→总结）
- [ ] 错题记录和管理
- [ ] 基础进度展示

### Phase 3: 复习系统
- [ ] SM-2 间隔复习算法
- [ ] 复习日历和提醒
- [ ] 复习卡片界面

### Phase 4: 进度和统计
- [ ] 番茄钟功能
- [ ] 学习统计可视化
- [ ] 薄弱点分析

### Phase 5: 完善和优化
- [ ] 更多 AI 提供商支持
- [ ] Markdown 笔记编辑器
- [ ] UI/UX 优化
- [ ] 性能优化

---

## 9. 技术栈总结

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端框架 | React 18 + TypeScript | 类型安全，组件化开发 |
| 前端构建 | Vite | 快速开发体验 |
| UI 库 | Ant Design | 功能全，文档好 |
| 图表库 | ECharts | 进度可视化 |
| Markdown | @uiw/react-md-editor | 笔记编辑 |
| 后端框架 | FastAPI | 现代、高性能、类型友好 |
| ORM | SQLAlchemy | Python 主流 ORM |
| 数据库 | SQLite | 轻量、无需安装 |
| AI SDK | 官方 SDK | openai, anthropic, google-generativeai |

---

*文档版本: 1.0*  
*最后更新: 2026-01-11*
