# Mnemox v1.0.5

发布时间：2026-05-25

## 本次重点更新

### 1. 新增 OpenAI 联网搜索

- 聊天输入区新增“联网搜索”开关，默认关闭。
- 开启后，官方 OpenAI provider 会通过 Responses API 调用内置 `web_search` 工具。
- 普通聊天仍沿用原有 Chat Completions 路径，避免默认增加费用和延迟。

### 2. 明确供应商支持边界

- 第一版联网搜索仅支持官方 OpenAI API。
- OpenAI-compatible 中转、DeepSeek、Qwen、Claude、Gemini 暂不走内置联网搜索。
- 当当前供应商不支持时，SSE 会返回明确错误：请切换到官方 OpenAI。

### 3. 发布与依赖同步

- 后端、桌面端、发布脚本和更新清单版本同步到 `1.0.5`。
- OpenAI Python SDK 最低版本提升到支持 Responses API 的安全版本。
- 更新清单指向 `v1.0.5` Windows 安装包。

## 回归验证

已完成以下验证：

- `backend`
  - `venv\Scripts\python.exe -m pytest`
- `frontend`
  - `npm run build`
- `desktop`
  - `npm test`
  - `powershell -ExecutionPolicy Bypass -File scripts\build_desktop_installer.ps1`

## 对用户的直接影响

- 使用官方 OpenAI key 时，可以在聊天中手动打开联网搜索来查询网页信息。
- 未开启联网搜索或使用其他供应商时，聊天行为保持不变。
- 如果当前供应商不支持内置搜索，界面会收到清晰错误，而不是误以为模型已经联网。
