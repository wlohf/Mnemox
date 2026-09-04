# Error Contract

## 前端统一入口

所有普通 JSON API 错误都由 `frontend/src/services/apiClient.ts` 转换为 `ApiRequestError`。

```ts
ApiRequestError {
  status?: number
  code?: string
  detail?: unknown
  body?: string
}
```

UI 获取用户可读文案时使用 `getApiErrorMessage(error, fallback)`，不要自己解析 `response.json()` 或判断多个后端错误格式。

## 后端兼容格式

`apiClient` 当前兼容：

- `{ "detail": "..." }`
- `{ "detail": { "message": "...", "code": "..." } }`
- `{ "message": "..." }`
- `{ "error": "..." }`

FastAPI 参数校验错误由后端统一 handler 转成用户可读 `detail`。

## 状态码语义

| 状态 | 约定 |
| --- | --- |
| 400 | 请求语义不成立或前置条件不满足 |
| 401 | 会话无效；`apiClient` 统一引导重新登录 |
| 404 | 资源不存在，或为防止跨用户泄漏而隐藏资源存在性 |
| 409 | 明确的状态冲突/并发冲突（适用时） |
| 413 | 上传体积超过限制 |
| 422 | FastAPI/Pydantic 参数校验 |
| 5xx | 服务端失败；只返回安全、脱敏的摘要 |

## 安全规则

API 错误不得返回 API Key、Authorization、数据库口令、provider 原始 secret、完整内部查询或其他用户数据。需要诊断时使用安全 `error_code / error_summary / error_fingerprint` 结构。