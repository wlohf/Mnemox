# Mnemox v1.1.0

发布时间：2026-06-22

## 本次重点更新

### 1. Tavily 高质量联网搜索

- 新增持久化联网搜索设置，可在 AI 设置页配置 Tavily API Key。
- Tavily 默认使用 `advanced` 搜索深度，并支持结果数量、每来源 chunks 和超时时间配置。
- 搜索设置支持测试按钮，便于先验证 Key 和搜索链路再用于聊天。

### 2. DuckDuckGo / Bing 最终兜底

- 没有配置 Tavily Key 时，仍可使用 DuckDuckGo / Bing 作为无需 Key 的本地兜底搜索。
- Tavily、Grok/专用搜索、Responses hosted web search 或工具搜索失败时，会降级到应用层搜索。
- 搜索结果会在 SSE 事件中带上来源 provider、评分和发布时间等元信息，方便前端展示与排查。

### 3. AI token 预算设置

- AI Provider 设置新增上下文 token 上限和输出 token 上限。
- OpenAI、Claude、Gemini 请求会使用配置的输出 token 上限。
- 聊天请求会按上下文 token 预算裁剪较旧历史，保留当前问题和最近上下文，降低长对话溢出风险。

### 4. 后续自学习能力路线图

- 新增 `docs/superpowers/specs/2026-06-22-search-token-coach-learning-roadmap.md`。
- 文档详细拆分了搜索质量、token 预算、Coach 自学习循环、策略统计和隐私边界。

## 回归验证

已完成以下验证：

- `backend`
  - `python -m pytest -q`
  - 结果：`104 passed, 4 subtests passed`
- `frontend`
  - `npm run build`

## 已知说明

- 本次 GitHub Release 先发布源码和说明。
- Windows 安装包建议从干净的 `v1.1.0` tag 单独构建后再上传，避免当前本地未提交的桌面实验改动混入安装器。
