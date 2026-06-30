# Mnemox v1.2.0

发布时间：2026-06-30

## 本次重点更新

### 1. 目标驱动 Agent cockpit

- Agent 页新增当前目标上下文、今日最小行动、目标风险信号和证据列表。
- 支持从目标上下文生成行动草案，并记录行动反馈。
- Agent 写入任务、目标、日计划和笔记时会记录结构化学习事件。

### 2. 双层记忆与审核

- 新增短记忆服务，用于整合当前会话、近期事件、目标状态和临时偏好。
- 新增长期记忆候选、Core Profile、确认、锁定、忽略和不准确标记流程。
- 低风险聚合记忆可自动确认，敏感或主观推断进入用户审核。

### 3. 自主 Coach Kernel

- 新增 Coach 事件、nudges、偏好、工作流和技能注册体系。
- 支持低动力、最小下一步、计划救援、复盘提醒、复习债务救援等技能。
- Policy 会结合免打扰、冷却、每日上限、允许渠道和反馈学习统计决定是否提醒。
- 桌面版支持 Coach 通知桥接和点击路由。

### 4. 笔记证据工作流

- 笔记页新增编辑、预览、分屏模式。
- 支持笔记关联 goal、task、material、pomodoro、review schedule 等对象。
- 支持从选中文本生成复习提示、生成任务草案，或构造安全的问 Agent 预览。

### 5. 搜索质量、缓存与 RAG 状态

- 新增搜索结果质量增强和缓存服务，减少重复搜索并改善结果排序。
- RAG 状态按用户记录最近检索状态，设置变更后能提示是否需要重建索引。
- AI 设置页新增重建全部 RAG 索引入口。

### 6. 背景图持久化与上传修复

- 新增背景专用上传接口 `POST /api/images/upload-background`。
- 自定义背景图从 base64/localStorage 改为后端文件 URL 存储。
- 番茄背景同步到桌面偏好，重启后可恢复当前背景。

## 回归验证

已完成以下验证：

- `backend`
  - `.\venv\Scripts\python.exe -m pytest -q`
  - 结果：`146 passed, 53 subtests passed`
- `frontend`
  - `npm test -- --run`
  - 结果：`19 passed files, 60 passed tests`
  - `npm run build`
  - `npm run lint`
- `desktop`
  - `npm test`
  - 结果：`21 passed`
- `git diff --check`

## 已知说明

- 本次 GitHub Release 发布源码、tag 和发布说明。
- 本地 `release/desktop` 只有旧版 `Mnemox-Setup-1.0.9.exe`，没有 v1.2.0 安装包，因此本次不上传陈旧安装器。
- 如需 Windows 安装包，建议从干净的 `v1.2.0` tag 单独构建并验证后再补充上传资产。
