# Mnemox v1.0.8

发布时间：2026-06-07

## 本次重点更新

### 1. Responses 流式联网搜索修复

- GPT / OpenAI-compatible 中转在开启联网搜索时优先使用 Responses hosted `web_search`。
- 请求形态改为与 Codex 一致的 hosted tool：`tools: [{"type": "web_search"}]`。
- 明确搜索类请求会强制 `tool_choice: {"type": "web_search"}`，避免模型在 `auto` 下不触发联网。
- 保留非实时问题的 `auto` 策略，减少不必要的搜索调用。

### 2. 联网搜索多级回退

- hosted `web_search` 不支持时，自动回退到 Responses function tool。
- Responses function tool 不支持时，再回退到 Chat Completions 流式 tools + Mnemox 本地搜索工具。
- 对 `unsupported parameter: web_search/tools`、`upstream_error` 等中转错误补充识别，避免直接中断聊天。

### 3. 本地搜索兜底增强

- 应用层 `web_search` 从单一 DuckDuckGo HTML 扩展为 DuckDuckGo、Bing RSS、Bing HTML 多级解析。
- DuckDuckGo 返回空结果或非结果页时，会继续尝试 Bing 搜索来源。
- 新增 Bing HTML / RSS 解析测试，提升搜索兜底稳定性。

### 4. 图片上传与番茄背景图

- 新增 `IMAGE_UPLOAD_MAX_MB` 配置，默认图片上传上限为 50MB。
- 请求体限制对资料上传和图片上传分别按配置取最大值，避免图片被 20MB 默认请求体限制拦截。
- 番茄背景图改为通过后端图片接口上传和鉴权访问，不再把大图以 base64 存入浏览器本地状态。

### 5. 统计展示优化

- 统计弹窗中的日均时长改为紧凑 `h` / `m` 格式，例如 `1h 25m`。

## 回归验证

已完成以下验证：

- `backend`
  - `venv\Scripts\python.exe -m pytest`
- `frontend`
  - `npm run build`
- 真实中转 smoke test
  - `https://api.xyleisure.site/v1` + `gpt-5.4`
  - Responses 流式 hosted `web_search`
  - 已确认能触发联网搜索并返回来源 URL

## 对用户的直接影响

- 使用 GPT / OpenAI-compatible 中转时，联网搜索会优先走中转可用的 Responses hosted search，而不是错误地只依赖自定义 function tool。
- 明确要求“联网搜索 / 最新 / 当前”等问题时，联网触发更稳定。
- 搜索兜底在 provider hosted tool 不可用时更可靠。
- 番茄背景图上传支持更大的图片，且刷新后访问更稳定。

## 发布说明

- 本次 GitHub 更新清单先指向 `v1.0.8` Release 页面。
- Windows 安装包资产上传后，再把 `release-manifest/latest.json` 的 `downloads.windows` 补回对应安装包 URL。
