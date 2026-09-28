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

SQLite 与 PostgreSQL 使用同一条 Alembic 迁移链。SQLite（桌面版、源码自部署）在应用启动时由 `init_db` 自动执行 Alembic 升级；尚未纳入 Alembic 的旧 SQLite 文件会先用冻结的旧版手写迁移补齐到基线 `20260928_31`，再标记版本并继续升级。PostgreSQL 必须先执行本命令，应用启动时只校验版本。`init_db.py` 保留为同一入口的兼容别名，不能用 `Base.metadata.create_all` 初始化任何库。Docker 镜像会在启动 Uvicorn 前自动运行该命令；入口会用 PostgreSQL advisory lock 串行化多个副本的 schema 检查、baseline stamp 和升级。

**改表约定**：所有 schema 变更只新增 Alembic revision，且同一份 revision 必须能在 SQLite 与 PostgreSQL 上执行（SQLite 需要改约束时使用 `op.batch_alter_table`，`env.py` 已为 SQLite 自动生成 batch 操作）。`app.database._run_lightweight_migrations` 已冻结，只用于旧 SQLite 文件的一次性补齐，`tests/test_sqlite_alembic_runtime.py` 会拒绝对它的修改。SQLite 与 PostgreSQL 的差异集中在 `app/utils/dialect.py`：需要 `ON CONFLICT` 的写入使用 `conflict_insert`，只在 PostgreSQL 需要的跨进程锁用 `is_postgresql` 判断；业务代码不要再直接判断 `dialect.name`。仓库根目录的 `rehearse_postgres_release.sh` 会在不升级源库的前提下完成备份、一次性恢复、当前 head 升级、schema drift 与稳定数据量核对；本地 PostgreSQL 16 历史 dump 恢复演练已通过，正式 PostgreSQL 仍须在发布窗口显式升级和验收。

### 资料检索质量验收

```bash
python evaluate_retrieval.py --backend hybrid --min-recall-at-5 0.75 --summary-only
```

如需复现真实 Qdrant Local 对照，可额外安装可选实验依赖；它不会进入生产依赖或常规启动链路：

```bash
pip install -r requirements-spike.txt
python evaluate_retrieval.py --backend all --include-qdrant --summary-only
```

### 可选图功能（Neo4j / Graphiti）

标准 `requirements.txt` 包含 `neo4j>=6.3,<7` 和 `graphiti-core>=0.30.1,<0.31`；`requirements-dev.txt` 会继承它们，常规测试不再需要额外安装 graph spike 依赖。安装 SDK 不会自动启动图服务或修改运行开关。

- **Neo4j**：默认 `GRAPH_BACKEND=sql`。配置 `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`、`NEO4J_DATABASE` 并显式选择 `GRAPH_BACKEND=neo4j` 后，图投影由 outbox/worker 维护；只有当前用户投影就绪且命中灰度才走 Neo4j。基础查询可回退 SQL，图路径能力另需 `KNOWLEDGE_V2_ENABLED=true` 和 `KNOWLEDGE_PATH_ENABLED=true`。Docker 中的 Neo4j 服务通过 `--profile graph` 启动。
- **Graphiti**：默认 `GRAPHITI_ENABLED=false`。启用时使用上述 Neo4j 连接配置，提供已审核记忆的当前/历史时间点查询，不要求把 `GRAPH_BACKEND` 改为 Neo4j。认证接口为 `GET /api/memory/temporal-graph/status`、`POST /api/memory/temporal-graph/rebuild` 和 `POST /api/memory/temporal-graph/query`。首次使用及记忆变更后需显式重建投影；目前没有接入普通聊天、Coach 或前端页面的自动记忆链路。
- Graphiti 当前切片仅投影已审核 SQL `MemoryDeclaration`，通过 BM25 查询并回到 SQL 核验结果；不自动摄入聊天原文，不调用外部 LLM、embedding 或 reranker，SQL 始终是规范来源。

真实图集成测试必须指向可丢弃的 Neo4j 实例，因为测试会重建和删除合成用户的图数据。`tests/test_neo4j_shadow_integration.py`、`tests/test_neo4j_knowledge_path_integration.py`、`tests/test_graphiti_shadow_integration.py` 和 `tests/test_graphiti_temporal_integration.py` 的文件头列出了各自需要的显式测试环境变量。

### Mnemox V2 Stage 0～3

以下命令只运行现有 Association V1 的临时 SQLite 离线评测，不调用外部模型，也不启用 Claim 或 Association V2：

```bash
python evaluate_knowledge.py --min-explicit-recall-at-5 0.95 --summary-only
```

固定语料位于 `tests/fixtures/knowledge_extraction_eval_cases.json` 与 `tests/fixtures/association_v2_eval_cases.json`。Stage 1 已增加 Source/Revision/Unit/Claim/Evidence SQL 模型；Stage 2 又增加严格共享 Schema、确定性/LLM extractor、Evidence Grounding 与 durable extraction run。`KNOWLEDGE_V2_ENABLED=true` 时，Material/Note 写入登记来源版本并创建本地确定性 run；只有同时打开 `KNOWLEDGE_LLM_EXTRACTION_ENABLED` 才创建 LLM run。所有自动 Claim 均为 `pending`，无法定位 Evidence 的候选不会写入。

Stage 3 新增 exact/alias/既有人工决定优先的 Entity Resolution、pending 词法/向量候选、confirmed ClaimConceptLink、Concept/Claim/Material Unit/Note Unit 的知识专用 Chroma 投影及 compact outbox。知识 embedding consumer 还要求 `KNOWLEDGE_EMBEDDING_ENABLED=true`；关闭或不可用时 exact/alias 和 SQL 审核继续工作。记录式合成 ranking 门禁可离线运行：

```bash
python evaluate_entity_resolution.py --summary-only
```

它不调用真实 provider，不替代真实语料抽验，也不会启用 Association V2 或外部图后端。后续阶段已实现的 Neo4j/Graphiti 可选能力及启用边界见上文。

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
- Agent/Anki：Agent 任务与反馈、按本地自然周生成带来源版本的 copy-only 知识巩固草案、Anki 卡片与复习
- 学习者模型：概念状态与解释、证据分页、人工修正/撤销、单概念/批量重算、投影重放与 outbox 处理
- AI 设置：提供商读取、更新、激活、连通性测试

### 主要待办

- 正式生产 PostgreSQL 升级须按发布窗口执行快照、Alembic 升级、数据量/外键/legacy 回填核对和回滚演练
- 常驻 outbox worker 已接入应用生命周期，DLQ、告警和跨实例聚合指标已收口；仍需在正式 PostgreSQL 发布窗口执行多实例并发验收
- 继续收敛 LLM prompt 安全边界，所有用户资料、笔记、工具结果都应作为不可信上下文传入
- 拆分过大的路由和服务模块，尤其是 learning、analytics、agent 相关实现
- 完善后台任务、结构化日志和失败重试可视化
- RAG 内容结构化（章节、知识点、题目自动入库）仍可继续增强
