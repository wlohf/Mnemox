# Mnemox v1.3.0

发布时间：2026-07-11

## 本次重点更新

### 1. 聊天笔记上下文

- 聊天会从当前用户的笔记中按关键词、标题、标签和更新时间检索最多三条相关摘录。
- 检索到的笔记会作为参考证据加入聊天上下文，帮助回答衔接用户已有的学习记录。
- 前端会提示本轮对话已参考的笔记标题，不展示整篇笔记内容。

### 2. 安全与兼容性

- 笔记摘录通过不可信上下文包装后才进入模型 Prompt，不能覆盖系统指令、工具权限或写入确认流程。
- 笔记检索严格按当前用户过滤；检索失败会自动跳过，不影响流式聊天、联网搜索、记忆注入或对话持久化。
- 笔记上下文限制为 1,800 字符预算，避免挤占主聊天上下文。

### 3. 本地演示与项目维护

- 新增 `scripts/seed_showcase_account.py`，用于准备本地演示账号、目标、笔记、记忆、Coach nudge 和学习事件数据。
- 新增需求、技术、进度三份项目基线文档，并接入文档导航。

## 回归验证

- `backend`
  - `.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`
  - 结果：`152 passed, 53 subtests passed`
- `frontend`
  - `npm.cmd test`
  - 结果：`19 passed files, 60 passed tests`
  - `npm.cmd run build`
  - `npm.cmd run lint`
- `desktop`
  - `npm.cmd test`
  - 结果：`21 passed`
- `git diff --check`

## 发布资产

- Windows 安装包：`Mnemox-Setup-1.3.0.exe`
- 自动更新清单：`latest.yml`
- 差分更新文件：`Mnemox-Setup-1.3.0.exe.blockmap`
