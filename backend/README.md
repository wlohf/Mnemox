# 学习助手后端

基于 FastAPI 的后端服务，提供学习管理、AI 对话、复习调度等功能。

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
python init_db.py
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

## 项目结构

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
│   │   └── note.py          # 笔记
│   ├── routers/             # API 路由（待实现）
│   ├── services/            # 业务逻辑（待实现）
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
- **Qwen** (通义千问) - 待实现

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

## 下一步

- [ ] 实现资料上传和解析 API
- [ ] 实现学习目标和 OKR 拆解 API
- [ ] 实现学习会话和对话 API
- [ ] 实现复习调度算法
- [ ] 实现统计分析 API
- [ ] 实现番茄钟 API
