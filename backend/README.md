# Mnemox 后端

基于 FastAPI 的后端服务，提供学习管理、AI 对话、复习调度和学习画像等功能。

## 快速开始

### 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `env.example` 为 `.env` 并填入你的 API Key：

```bash
cp env.example .env
```

编辑 `.env` 文件，至少配置一个 AI 提供商的 API Key：

```env
DEFAULT_AI_PROVIDER=openai
OPENAI_API_KEY=your_api_key_here
```

### 3. 初始化数据库

```bash
python run_migrations.py
```

SQLite 开发环境会创建本地表并执行轻量兼容迁移；PostgreSQL 必须通过 Alembic 执行版本化迁移。`init_db.py` 保留为同一入口的兼容别名，不能再用 `Base.metadata.create_all` 初始化生产库。Docker 镜像会在启动 Uvicorn 前自动运行该命令；入口会用 PostgreSQL advisory lock 串行化多个副本的 schema 检查、baseline stamp 和升级。当前 Alembic head 为 `20260823_12`，SQLite lightweight migration 已覆盖 Vault、资料检索投影、可审核概念来源、学习状态计数，以及时态记忆事实键、冲突关系、历史回填和当前事实唯一约束；正式 PostgreSQL 仍须先快照，并在发布窗口执行当前 head 升级、schema 核对和多实例 Outbox 验收。

### 资料检索质量验收

```bash
python evaluate_retrieval.py --backend hybrid --min-recall-at-5 0.75 --summary-only
```

如需复现真实 Qdrant Local 对照，可额外安装可选实验依赖；它不会进入生产依赖或常规启动链路：

```bash
pip install -r requirements-spike.txt
python evaluate_retrieval.py --backend all --include-qdrant --summary-only
```

### 4. 启动服务

```bash
python -m app.main
```

或者使用 uvicorn：

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. 访问 API 文档

服务启动后，访问：
- API 文档（Swagger UI）: http://localhost:8000/docs
- API 文档（ReDoc）: http://localhost:8000/redoc

## 项目结构（当前）

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # 配置管理
│   ├── database.py          # 数据库连接
│   ├── models/              # 数据模型
│   │   ├── material.py      # 学习资料
│   │   ├── goal.py          # 学习目标
│   │   ├── session.py       # 学习会话
│   │   ├── question.py      # 题目和错题
│   │   ├── pomodoro.py      # 番茄钟
│   │   ├── note.py          # 笔记
│   │   └── learner_model.py # 学习证据、概念状态与投影 outbox
│   ├── routers/             # API 路由（已包含 chat/materials/pomodoro/plans 等）
│   ├── services/            # 业务逻辑（material/event_tracker 等）
│   └── ai/                  # AI 服务适配层
│       ├── base.py          # 基类
│       ├── openai_provider.py    # OpenAI
│       ├── claude_provider.py    # Claude
│       ├── gemini_provider.py    # Gemini
│       ├── factory.py       # AI 提供商工厂
│       └── prompts.py       # Prompt 模板
├── requirements.txt
├── env.example
├── init_db.py              # 数据库初始化脚本
└── README.md
```

## AI 提供商

支持以下 AI 提供商（配置对应的 API Key 即可切换）：

- **OpenAI** (GPT-4, GPT-3.5)
- **Anthropic Claude** (Claude 3 Opus/Sonnet)
- **Google Gemini** (Gemini Pro)
- **Qwen** (通义千问)

## 开发

### 添加新的路由

在 `app/routers/` 目录下创建新的路由文件，然后在 `app/main.py` 中引入：

```python
from app.routers import materials
app.include_router(materials.router, prefix="/api/materials", tags=["资料管理"])
```

### 添加新的业务逻辑

在 `app/services/` 目录下创建服务类，实现具体的业务逻辑。

### 测试 AI 服务

```python
from app.ai.factory import AIProviderFactory

# 创建 AI 提供商实例
provider = AIProviderFactory.create_provider("openai")

# 发送消息
response = await provider.chat([
    {"role": "user", "content": "解释一下费曼学习法"}
])
print(response)
```

## 当前状态与待办

### 已实现接口（post-v1.3 主线基线，尚未作为新安装版本发布）

- 资料：上传、创建、列表、详情、删除、RAG 分析/提问
- 对话：流式聊天、会话 CRUD、项目 CRUD、项目资料关联
- 番茄：开始、完成、最近记录、统计、批量同步
- 计划：按日期读写、按区间查询
- 目标/任务：目标 CRUD、任务 CRUD、任务树、周计划生成
- 学习会话：开始、结束、按任务查询、当前活跃会话
- 错题：列表、创建、更新、复习、删除、复习计划联动
- 笔记/记忆/画像：笔记 CRUD、AI 辅助、记忆管理、用户画像
- Analytics/EDA/干预：进度、掌握度、行为分析、主动干预
- Agent/Anki：Agent 任务与反馈、Anki 卡片与复习
- 学习者模型：概念状态与解释、证据分页、人工修正/撤销、单概念/批量重算、投影重放与 outbox 处理
- AI 设置：提供商读取、更新、激活、连通性测试

### 主要待办

- 正式生产 PostgreSQL 升级须按发布窗口执行快照、Alembic 升级、数据量/外键/legacy 回填核对和回滚演练
- 常驻 outbox worker 已接入应用生命周期，DLQ、告警和跨实例聚合指标已收口；仍需在正式 PostgreSQL 发布窗口执行多实例并发验收
- 继续收敛 LLM prompt 安全边界，所有用户资料、笔记、工具结果都应作为不可信上下文传入
- 拆分过大的路由和服务模块，尤其是 learning、analytics、agent 相关实现
- 完善后台任务、结构化日志和失败重试可视化
- RAG 内容结构化（章节、知识点、题目自动入库）仍可继续增强
