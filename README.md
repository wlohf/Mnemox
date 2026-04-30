<div align="center">

# 🧠 Mnemox — AI 驱动的个性化学习教练

**不只是聊天助手，而是真正懂你学习规律的 AI 教练**

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61dafb?logo=react)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-blue?logo=typescript)](https://typescriptlang.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

[快速开始](#快速开始) · [系统架构](#系统架构) · [核心功能](#核心功能) · [此次更新说明](#此次更新说明) · [技术栈](#技术栈)

</div>

---

## 项目背景

市面上的 AI 学习工具大多停留在「问答」层面——你问它答，但它不记得你上次学了什么，不知道你在哪个知识点反复出错，也不知道你最容易在什么时候放弃学习。

这个项目尝试解决一个更核心的问题：**AI 如何基于用户真实的学习行为数据，给出真正个性化的干预？**

出发点来自备考经历中的观察：
- 学习计划制定容易，但三天打鱼两天晒网是常态
- 番茄钟用了，但不知道自己哪个时段效率最高
- 错题本记了，但不知道哪些知识点是真正的薄弱项
- AI 每次对话都是「失忆」状态，无法给出基于历史的建议

---

## 核心问题与解法

| 问题 | 解法 |
|---|---|
| AI 不了解用户 | 用户画像系统：从行为数据自动计算专注度、坚持度、最佳学习时段 |
| AI 对话无记忆 | 双层记忆：Episodic 记忆（对话摘要）+ Semantic 记忆（长期事实提炼）|
| 学习资料利用率低 | RAG 管道：资料自动向量化，AI 回答时自动检索相关内容 |
| 无法追踪学习行为 | 事件追踪系统：记录每一次番茄钟、答题、复习的行为数据 |

---

## 系统架构

```mermaid
graph TB
    subgraph Frontend["前端 (React 18 + TypeScript)"]
        UI["Dashboard / Pomodoro / Goals\nReview / WrongQuestions / Notes"]
        PP["PromptsPage\n自定义 AI 提示词"]
        UP["UserProfilePage\n学习画像可视化"]
    end

    subgraph Backend["后端 (FastAPI + Python)"]
        direction TB
        ET["EventTracker\n学习行为事件追踪"]
        PS["ProfileService\n用户画像计算"]
        MS["MemoryService\nEpisodic + Semantic 记忆"]
        PT["PromptTemplates\n用户自定义 Prompt"]

        subgraph AI["AI 层"]
            LLM["Multi-LLM Router\nOpenAI / Claude / Gemini / DeepSeek"]
            RAG["RAG Service\nLlamaIndex + ChromaDB"]
        end

        subgraph DB["数据层"]
            SQLite[("SQLite / PostgreSQL\nlearning_events · user_profiles\npomodoros · memories · conversations\nwrong_questions · prompt_templates")]
            VDB[("ChromaDB\n向量数据库")]
        end
    end

    Frontend -->|REST API| Backend
    ET --> SQLite
    PS --> SQLite
    MS --> SQLite
    PT --> SQLite
    LLM --> RAG
    RAG --> VDB
    PS -->|画像注入 system prompt| LLM
    MS -->|记忆注入 system prompt| LLM
    PT -->|自定义 prompt 注入| LLM
```

---

## 数据从哪里来

系统通过 `EventTracker` 在每个用户操作节点埋点，将行为数据写入 `learning_events` 表：

```python
# 事件类型举例
EventType.POMODORO_COMPLETE    # 完成一个番茄钟
EventType.POMODORO_INTERRUPT   # 中断番茄钟（专注度信号）
EventType.QUESTION_WRONG       # 答题答错（薄弱点信号）
EventType.STUDY_START / END    # 学习会话开始/结束
EventType.REVIEW_COMPLETE      # 完成一次复习
```

每条事件记录：事件类型、发生时间、持续时长、关联资料/章节、会话 ID。

`ProfileService` 每小时自动从原始事件聚合计算用户画像，结果持久化到 `user_profiles` 表，并在每次 AI 对话时注入 system prompt。

---

## 核心功能

### 1. 学习行为事件系统
- 全链路行为埋点：番茄钟、答题、复习、笔记、AI 交互
- 时序数据存储，支持按时间窗口聚合分析
- 事件分类：`study` / `practice` / `review` / `goal`

### 2. 用户画像自动计算
- **专注度评分**：番茄钟完成率 vs 中断率
- **坚持度评分**：连续学习天数、断档频率（三天打鱼指数）
- **自控力评分**：每日计划执行完成比
- **最佳学习时段**：基于时间段内完成番茄钟数量分布
- **薄弱知识点**：错题本高频知识点 Top 10
- 画像自动注入 AI system prompt，实现真正个性化回复

### 3. AI 教练记忆系统
- **Episodic 记忆**：对话摘要，带时间衰减（久远记忆权重降低）
- **Semantic 记忆**：从对话中提炼长期事实（学习偏好、目标、薄弱点）
- **画像上下文注入**：每次对话携带用户历史画像数据

### 4. RAG 知识库
- 支持 PDF / Word / Markdown 格式资料上传
- LlamaIndex 自动解析 + 章节结构化
- ChromaDB 向量存储，AI 回答自动检索相关章节
- 意图识别：对话中自动判断是否需要检索资料库

### 5. 多 AI 提供商支持
- OpenAI（GPT-4o / GPT-4）
- Anthropic Claude（Claude 3.5 Sonnet）
- Google Gemini
- DeepSeek / Qwen
- 运行时切换，无需重启

### 6. 学习工具集
- **番茄钟**：计时、统计、任务关联、离线同步；停止时记录原因（提前完成 / 临时中断 / 状态不好），自动纳入画像分析
- **间隔复习**：艾宾浩斯遗忘曲线调度
- **错题本**：知识点归类、薄弱点追踪
- **学习目标（OKR）**：目标拆解、7日计划生成、自适应重规划
- **掌握度地图**：章节级学习进度可视化
- **笔记系统**：关联资料章节，支持 Obsidian 导入

### 7. 自定义 Prompt 管理
- 10 种学习场景独立 prompt：AI 教练、费曼学习法、苏格拉底提问、出题、错题分析、复习引导、走神关怀等
- `/prompts` 页面可视化编辑，一键恢复默认
- 聊天时按场景自动切换对应 prompt，用户自定义优先

### 8. 用户画像可视化
- 四维雷达图：自控力 / 专注度 / 坚持度 / 计划执行
- 24 小时学习热力图：直观显示你的高效时段
- 薄弱知识点 Tag 展示
- 一键刷新重新计算画像

### 9. 学习行为 EDA 报告
- `/eda` 页面提供最近 7 / 30 / 90 天学习趋势分析
- pandas + scipy 聚合学习时长、番茄钟完成率、任务完成率、时段效率
- ECharts 展示日趋势、小时分布、周内热力图、停止原因占比、能力雷达
- 自动生成图表解读、关键洞察和建议动作，便于复盘学习节奏

### 10. AI 主动干预
- `/intervention` 页面生成每日学习报告和推送文案
- 根据今日学习时长、待办积压、到期复习、任务完成率评估风险等级
- AI 失败时使用模板兜底，确保干预报告稳定可用

### 11. Anki 风格记忆卡
- `/anki` 页面支持手动创建、CSV 导入导出、AI 批量生成卡片
- 使用 SM-2 风格调度字段：到期时间、间隔天数、简易系数、复习评分
- 已接入 IndexedDB 离线缓存和同步适配器

### 12. 个性化界面与系统设置
- 新增设置面板：主题、背景图、AI 供应商、激励语录、提示词、系统更新
- 支持跟随系统 / 暖色 / 深色主题，自定义背景图和透明度
- 支持应用版本检查与自动检查间隔配置

---

## 技术栈

| 层级 | 技术 |
|---|---|
| 前端框架 | React 18 + TypeScript |
| 前端构建 | Vite |
| UI 组件库 | Ant Design |
| 数据可视化 | ECharts |
| 状态管理 | Zustand |
| 离线缓存 | Dexie / IndexedDB |
| Markdown 编辑 | Toast UI Editor / react-markdown |
| 后端框架 | FastAPI + Python 3.10+ |
| 数据库 ORM | SQLAlchemy 2.0（异步） |
| 数据库 | SQLite（本地）/ PostgreSQL（生产）|
| AI 编排 | 自研 Multi-LLM Router |
| RAG 框架 | LlamaIndex + ChromaDB |
| 向量嵌入 | OpenAI text-embedding-3-small |
| 文件解析 | PyPDF2 + python-docx |
| 容器化 | Docker + Docker Compose |
| 数据库迁移 | Alembic |

---

## 此次更新说明

更新日期：2026-04-30

本次更新围绕「学习数据闭环」补齐了分析、干预、复习和系统设置能力：

- **学习分析**：新增 EDA 报告页面与 `/api/analytics` 接口，支持学习趋势、时段效率、目标完成预测、图表洞察和报告文本生成。
- **主动干预**：新增 `/api/interventions` 与前端干预页面，按学习时长、任务积压、到期复习自动判断风险等级，并生成每日提醒。
- **Anki 记忆卡**：新增 AnkiCard 数据模型、卡片管理接口、AI 生成、CSV 导入导出、SM-2 风格复习调度和离线同步。
- **计划与目标体验**：优化目标拆解、计划页面、今日聚焦动作、离线目标/任务同步和重规划流程。
- **笔记编辑**：新增 Toast UI Markdown 实时编辑器，支持图片上传、任务列表快捷输入、代码高亮和数学公式样式。
- **界面与设置**：重构主布局与页面外观，新增主题切换、自定义背景、系统版本检查、激励语录和统计弹窗。
- **后端稳定性**：完善数据库初始化、Alembic 环境、配置校验、上传目录处理、RAG 自动索引和多 AI 供应商路由。
- **安全与仓库卫生**：示例配置统一使用占位符，移除配置说明中的明文密钥，并忽略本地 `.aionrs/` 会话目录。

---

## 快速开始

### 前置条件

- Node.js 18+
- Python 3.10+
- 至少一个 AI 提供商的 API Key（OpenAI / Claude / Gemini / DeepSeek）

### 方式一：本地手动启动（开发用）

**1. 克隆项目**

```bash
git clone https://github.com/wlohf/RagStudyAssistant.git
cd StudyAssistant
```

**2. 配置环境变量**

```bash
cp backend/env.example backend/.env
# 编辑 backend/.env，填入你的 API Key
```

```env
OPENAI_API_KEY=sk-...
CLAUDE_API_KEY=sk-ant-...
SECRET_KEY=your-secret-key
```

**3. 启动后端**

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

**4. 启动前端**（另开终端）

```bash
cd frontend
npm install
npm run dev
```

**5. 访问应用**

打开浏览器：http://localhost:5173

### 方式二：Docker Compose（生产用）

```bash
cp .env.example .env
# 填写 .env 中的 API Key 和 DB_PASSWORD

docker compose up -d
```

访问：http://localhost

### Windows 一键启动

双击根目录的 `start.bat`，自动启动前后端并打开浏览器。

---

## 项目结构

```
StudyAssistant/
├── backend/
│   ├── app/
│   │   ├── ai/                # Multi-LLM Router + RAG 服务
│   │   │   ├── factory.py     # LLM 提供商工厂
│   │   │   ├── rag_service.py # LlamaIndex + ChromaDB
│   │   │   └── prompts.py     # 系统提示词
│   │   ├── models/            # SQLAlchemy 数据模型（18 张表）
│   │   ├── routers/           # FastAPI 路由（22 个模块）
│   │   ├── services/
│   │   │   ├── event_tracker.py   # 学习行为事件追踪
│   │   │   ├── profile_service.py # 用户画像计算
│   │   │   └── memory_service.py  # AI 记忆管理
│   │   └── main.py
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/             # Dashboard / Anki / EDA / Intervention 等功能页面
│       ├── services/          # API 调用层
│       ├── sync/              # 离线同步引擎与适配器
│       └── stores/            # Zustand 状态
├── data/
│   ├── study.db               # SQLite 数据库
│   └── uploads/               # 上传的学习资料
├── docker-compose.yml
└── README.md
```

---

## 当前状态

### 已完成

- [x] AI 多轮对话（流式输出、会话持久化、项目分组）
- [x] 多 AI 提供商运行时切换
- [x] RAG 知识库（资料上传、向量化、检索注入）
- [x] 学习行为事件追踪系统
- [x] 用户画像自动计算（专注度/坚持度/最佳时段）
- [x] AI 双层记忆系统（Episodic + Semantic）
- [x] 番茄钟计时与统计
- [x] 学习目标与 7 日计划生成
- [x] 掌握度地图
- [x] 错题本
- [x] 间隔复习调度
- [x] 笔记系统 + Obsidian 导入
- [x] Docker 容器化部署
- [x] 番茄钟中断原因分类（提前完成 / 临时中断 / 走神）+ 画像分析
- [x] 自定义 Prompt 管理（10 种场景，可视化编辑）
- [x] 用户画像可视化页面（雷达图 + 24小时热力图 + 薄弱点）
- [x] 学习行为 EDA 分析报告（pandas + scipy + ECharts）
- [x] AI 主动干预推送文案与每日学习报告
- [x] Anki 风格记忆卡（AI 生成 / CSV 导入导出 / SM-2 调度）
- [x] Toast UI Markdown 实时编辑器
- [x] 主题、背景、系统版本检查等设置面板

### 进行中

- [ ] 聊天框场景模式选择器（费曼 / 苏格拉底 / 教练 快速切换）
- [ ] 自动更新包分发与发布清单维护

---

## License

MIT © 2025
