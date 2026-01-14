# 配置中转API指南

本指南说明如何配置 StudyAssistant 和 AnythingLLM 使用您的中转API。

---

## 📋 您的API配置信息

- **API Key**: `sk-rqTCXXlp0rB2inE_rINqZQPJUwvOcKrpoHgYQkpYYbdxtLXOH5AxCXuQJP0`
- **API地址**: `https://api.224442.xyz`
- **模型**: `glm-4.7`

---

## 🔧 配置步骤

### 步骤 1: 配置 StudyAssistant 后端

```bash
# 1. 进入后端目录
cd StudyAssitant/backend

# 2. 复制配置模板
copy .env.中转API配置示例 .env

# 3. 配置已经写好，可以直接使用！
```

**配置文件内容** (`backend/.env`):
```env
# 数据库
DATABASE_URL=sqlite+aiosqlite:///./data/study.db

# AI 配置 - 使用中转API
DEFAULT_AI_PROVIDER=openai
OPENAI_API_KEY=sk-rqTCXXlp0rB2inE_rINqZQPJUwvOcKrpoHgYQkpYYbdxtLXOH5AxCXuQJP0
OPENAI_MODEL=glm-4.7
OPENAI_BASE_URL=https://api.224442.xyz/v1

# AnythingLLM 配置
ANYTHINGLLM_ENABLED=true
ANYTHINGLLM_BASE_URL=http://localhost:3001
ANYTHINGLLM_WORKSPACE=study-materials

# 服务器配置
HOST=0.0.0.0
PORT=8000
DEBUG=true
CORS_ORIGINS=["http://localhost:5173", "http://localhost:3000"]
```

⚠️ **注意**: API地址必须加上 `/v1` 后缀！

---

### 步骤 2: 配置 AnythingLLM

AnythingLLM 需要在 Web 界面中配置。有两种方式：

#### 方式 A: 首次启动时配置（推荐）

1. 启动 AnythingLLM Server:
   ```bash
   cd tools/anything-llm/server
   yarn dev
   ```

2. 访问 http://localhost:3001

3. 首次进入会看到欢迎页面，按以下步骤配置:
   
   **第一步 - 选择 LLM 提供商:**
   - 选择 "OpenAI"
   
   **第二步 - 配置 API:**
   - **API Key**: `sk-rqTCXXlp0rB2inE_rINqZQPJUwvOcKrpoHgYQkpYYbdxtLXOH5AxCXuQJP0`
   - **Base URL** (点击 "Show Advanced"): `https://api.224442.xyz/v1`
   - **Chat Model**: `glm-4.7`
   
   **第三步 - 选择 Embedding 提供商:**
   - 推荐选择 "AnythingLLM Built-in" (免费，本地运行)
   - 或者也选择 "OpenAI" 使用您的中转API

4. 完成配置后即可使用

#### 方式 B: 修改配置文件（高级）

如果 AnythingLLM 已经启动过，可以修改配置文件：

**创建 `tools/anything-llm/server/.env` 文件:**

```env
# LLM 提供商配置
LLM_PROVIDER=openai
OPEN_AI_KEY=sk-rqTCXXlp0rB2inE_rINqZQPJUwvOcKrpoHgYQkpYYbdxtLXOH5AxCXuQJP0
OPEN_MODEL_PREF=glm-4.7
OPEN_AI_BASE_PATH=https://api.224442.xyz/v1

# Embedding 提供商（使用内置的）
EMBEDDING_ENGINE=native
EMBEDDING_MODEL_PREF=nomic-embed-text-v1.5

# 向量数据库
VECTOR_DB=lancedb

# 服务器端口
SERVER_PORT=3001
```

**重启 AnythingLLM Server 使配置生效**

---

### 步骤 3: 启动文档处理服务

```bash
# 新开一个终端
cd tools/anything-llm/collector
yarn dev
```

---

### 步骤 4: 启动 StudyAssistant

```bash
# 新开一个终端
cd StudyAssitant/backend
python -m uvicorn app.main:app --reload
```

---

## 🧪 测试配置

### 1. 测试 StudyAssistant 集成

```bash
cd StudyAssitant/backend
python test_integration.py
```

**期望输出:**
```
✅ AnythingLLM 服务器在线
✅ 文档处理服务在线
✅ 工作空间已就绪
✅ RAG 聊天功能正常
✅ 所有测试通过！
```

### 2. 测试 API 调用

```python
# test_api.py
import requests

# 测试中转API是否可用
response = requests.post(
    "http://localhost:8000/api/materials/upload",
    files={'file': open('test.txt', 'rb')},
    data={
        'title': '测试文档',
        'sync_to_anythingllm': 'true'
    }
)
print(response.json())
```

---

## 🌐 一键启动脚本（已配置API）

创建 `start_configured.bat`:

```batch
@echo off
chcp 65001 >nul
echo ====================================
echo   启动 StudyAssistant (已配置中转API)
echo ====================================
echo.

echo [1/3] 启动 AnythingLLM...
start "AnythingLLM Server" cmd /k "cd tools\anything-llm\server && yarn dev"
timeout /t 3 >nul

start "AnythingLLM Collector" cmd /k "cd tools\anything-llm\collector && yarn dev"
timeout /t 3 >nul

echo [2/3] 启动 StudyAssistant Backend...
start "StudyAssistant Backend" cmd /k "cd StudyAssitant\backend && python -m uvicorn app.main:app --reload"
timeout /t 3 >nul

echo [3/3] 启动 StudyAssistant Frontend (可选)...
start "StudyAssistant Frontend" cmd /k "cd StudyAssitant\frontend && npm run dev"

echo.
echo ====================================
echo   所有服务已启动！
echo ====================================
echo.
echo 📌 使用的配置:
echo   - API: https://api.224442.xyz
echo   - 模型: glm-4.7
echo.
echo 🌐 服务地址:
echo   - AnythingLLM:     http://localhost:3001
echo   - API文档:         http://localhost:8000/docs
echo   - 前端:            http://localhost:5173
echo.
pause
```

---

## ⚙️ AnythingLLM 配置说明

### 环境变量对照表

| 功能 | 环境变量名 | 您的值 |
|------|-----------|--------|
| LLM 提供商 | `LLM_PROVIDER` | `openai` |
| API Key | `OPEN_AI_KEY` | `sk-rqTCXXlp0r...` |
| 模型名称 | `OPEN_MODEL_PREF` | `glm-4.7` |
| API 地址 | `OPEN_AI_BASE_PATH` | `https://api.224442.xyz/v1` |
| Embedding | `EMBEDDING_ENGINE` | `native` (推荐) |

### 可选：创建 AnythingLLM 配置文件

```bash
cd tools/anything-llm/server
echo LLM_PROVIDER=openai > .env
echo OPEN_AI_KEY=sk-rqTCXXlp0rB2inE_rINqZQPJUwvOcKrpoHgYQkpYYbdxtLXOH5AxCXuQJP0 >> .env
echo OPEN_MODEL_PREF=glm-4.7 >> .env
echo OPEN_AI_BASE_PATH=https://api.224442.xyz/v1 >> .env
echo EMBEDDING_ENGINE=native >> .env
echo VECTOR_DB=lancedb >> .env
echo SERVER_PORT=3001 >> .env
```

---

## 📝 配置验证清单

配置完成后，请确认：

- [ ] `StudyAssitant/backend/.env` 文件已创建
- [ ] `.env` 中 API Key 正确
- [ ] `.env` 中 API 地址包含 `/v1` 后缀
- [ ] `.env` 中模型名称为 `glm-4.7`
- [ ] AnythingLLM 已在 Web 界面配置 LLM
- [ ] 运行 `test_integration.py` 测试通过
- [ ] 可以正常上传文档并提问

---

## 🐛 常见问题

### Q1: 提示 "Invalid API Key"

**原因**: API Key 配置错误或中转服务不可用

**解决**:
1. 检查 API Key 是否正确复制
2. 测试中转API是否可用:
   ```bash
   curl -X POST https://api.224442.xyz/v1/chat/completions \
     -H "Authorization: Bearer sk-rqTCXXlp0rB2inE_rINqZQPJUwvOcKrpoHgYQkpYYbdxtLXOH5AxCXuQJP0" \
     -H "Content-Type: application/json" \
     -d '{"model":"glm-4.7","messages":[{"role":"user","content":"你好"}]}'
   ```

### Q2: 模型不存在或无法使用

**原因**: 模型名称错误或中转API不支持该模型

**解决**:
1. 确认模型名称为 `glm-4.7`
2. 联系中转API提供商确认支持的模型列表
3. 如果模型名称不对，修改 `.env` 中的 `OPENAI_MODEL`

### Q3: AnythingLLM 配置不生效

**原因**: 
- 配置文件位置错误
- 需要重启服务

**解决**:
1. 确保 `.env` 在 `tools/anything-llm/server/` 目录
2. 停止并重启 AnythingLLM Server
3. 或在 Web 界面手动配置

### Q4: 中转API连接超时

**原因**: 网络问题或服务不可用

**解决**:
1. 检查网络连接
2. 测试 API 地址是否可访问
3. 联系中转API提供商

---

## 💡 优化建议

### 1. 使用本地 Embedding (节省成本)

AnythingLLM 的 Embedding 使用内置的本地模型，完全免费：

```env
# 在 AnythingLLM 的 .env 中
EMBEDDING_ENGINE=native
EMBEDDING_MODEL_PREF=nomic-embed-text-v1.5
```

### 2. 配置超时时间

如果中转API响应较慢，可以增加超时时间：

修改 `StudyAssitant/backend/app/ai/anythingllm_provider.py`:
```python
async with httpx.AsyncClient(timeout=120.0) as client:  # 增加到120秒
```

### 3. 批量处理

如果要上传多个文档，建议逐个上传，避免并发超限。

---

## 📞 获取帮助

如果遇到问题：

1. 运行诊断脚本: `python test_integration.py`
2. 检查 API Key 是否有效
3. 测试中转API是否可访问
4. 查看服务日志输出

---

## ✅ 配置完成

按照以上步骤配置后，您的 StudyAssistant 将使用中转API提供的 `glm-4.7` 模型！

开始上传资料并体验智能问答吧！ 🚀

---

<div align="center">

**配置文件已准备就绪**

如有问题，随时询问！

</div>
