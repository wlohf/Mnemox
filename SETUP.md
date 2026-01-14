# 学习助手 - 快速启动指南

## 📋 前置要求

请确保你的电脑已安装：
- ✅ **Python 3.10+** - [下载链接](https://www.python.org/downloads/)
- ✅ **Node.js 18+** - [下载链接](https://nodejs.org/)
- ✅ **Git** - 已安装（你已经有了）

检查版本：
```bash
python --version   # 应该显示 Python 3.10 或更高
node --version     # 应该显示 v18 或更高
npm --version      # 应该显示 9 或更高
```

---

## 🚀 第 1 步：配置后端

### 1.1 创建数据目录

在项目根目录下创建 `data` 文件夹（用于存放数据库和上传的文件）：

```bash
mkdir data
mkdir data\uploads
```

### 1.2 配置环境变量

在 `backend` 目录下创建 `.env` 文件：

```bash
cd backend
type nul > .env
```

然后用记事本或 VS Code 打开 `backend/.env`，粘贴以下内容：

```env
# Database
DATABASE_URL=sqlite+aiosqlite:///./data/study.db

# AI Provider Configuration
DEFAULT_AI_PROVIDER=claude

# Claude (你的配置)
CLAUDE_API_KEY=sk-Ur1hxI8iaqHCUtmlwDxejC6hm26G6qfgh4AQWtMljCO4pVbJ
CLAUDE_MODEL=claude-opus-4-5-20251101
CLAUDE_BASE_URL=https://wzw.pp.ua

# Server
HOST=0.0.0.0
PORT=8000
DEBUG=True

# CORS
CORS_ORIGINS=["http://localhost:5173", "http://localhost:3000"]
```

保存文件。

### 1.3 安装 Python 依赖

在 `backend` 目录下运行：

```bash
pip install -r requirements.txt
```

⏱️ 这个过程需要 2-5 分钟，取决于网速。

### 1.4 初始化数据库

```bash
python init_db.py
```

✅ 如果看到 "🎉 数据库初始化完成！"，说明成功了。

### 1.5 启动后端服务

```bash
python -m app.main
```

✅ 如果看到：
```
✅ 数据库初始化完成
INFO:     Uvicorn running on http://0.0.0.0:8000
```

说明后端启动成功！

📖 访问 http://localhost:8000/docs 可以看到 API 文档。

**保持这个终端窗口打开**，不要关闭。

---

## 🎨 第 2 步：配置前端

### 2.1 打开新的终端

**重要**：不要关闭后端的终端，打开一个新的终端窗口。

### 2.2 进入前端目录

```bash
cd frontend
```

### 2.3 安装 Node.js 依赖

```bash
npm install
```

⏱️ 这个过程需要 3-10 分钟，取决于网速。

如果安装很慢，可以使用淘宝镜像：
```bash
npm install --registry=https://registry.npmmirror.com
```

### 2.4 启动前端服务

```bash
npm run dev
```

✅ 如果看到：
```
  VITE v5.x.x  ready in xxx ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
```

说明前端启动成功！

---

## 🎉 第 3 步：测试系统

### 3.1 打开浏览器

访问：http://localhost:5173

你应该能看到学习助手的界面，包括：
- 侧边栏导航（仪表盘、资料管理、学习空间等）
- 仪表盘页面显示统计卡片

### 3.2 测试 AI 连接

打开浏览器开发者工具（按 F12），在控制台（Console）中运行：

```javascript
fetch('http://localhost:8000/health')
  .then(r => r.json())
  .then(console.log)
```

✅ 如果看到 `{status: "ok"}`，说明后端正常。

---

## ❓ 常见问题

### Q1: pip install 失败？

**问题**：`pip install` 时提示找不到某些包。

**解决**：
```bash
# 升级 pip
python -m pip install --upgrade pip

# 使用清华镜像加速
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Q2: 端口被占用？

**问题**：提示 "Address already in use" 或 "端口 8000/5173 被占用"。

**解决**：
- 后端：修改 `backend/.env` 中的 `PORT=8000` 为其他端口（如 8001）
- 前端：修改 `frontend/vite.config.ts` 中的 `port: 5173` 为其他端口

### Q3: 数据库初始化失败？

**问题**：`init_db.py` 运行失败。

**解决**：
1. 确保 `data` 目录存在：`mkdir data`
2. 检查 `.env` 文件中的 `DATABASE_URL` 配置是否正确
3. 删除 `data/study.db` 文件后重试

### Q4: npm install 很慢？

**解决**：使用淘宝镜像
```bash
npm config set registry https://registry.npmmirror.com
npm install
```

### Q5: Python 版本太低？

**问题**：提示需要 Python 3.10+。

**解决**：从 [python.org](https://www.python.org/downloads/) 下载最新版本。

---

## 📞 需要帮助？

如果遇到问题：

1. **截图错误信息**，包括完整的错误堆栈
2. **告诉我你在哪一步**（配置后端？安装依赖？启动服务？）
3. **把错误信息发给我**，我会帮你解决

---

## 🎯 下一步

启动成功后，我们可以开始实现功能：

1. ✅ 资料上传和解析
2. ✅ AI 对话学习
3. ✅ 学习目标和 OKR 拆解
4. ✅ 错题管理和复习调度

准备好了就告诉我！🚀
