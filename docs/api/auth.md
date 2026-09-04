# Auth API

## 职责

认证领域负责登录、会话恢复、退出和当前用户身份。浏览器端使用 **HttpOnly Cookie** 承载会话，业务组件不接触 token。

## 前端边界

- Service：`frontend/src/services/authApi.ts`
- Transport：`frontend/src/services/apiClient.ts`
- UI 不读取 JWT，不拼 Authorization header。
- `apiClient` 遇到 401 时统一清理旧本地 token 痕迹并跳转登录页。

## Contract 要点

- 认证失败：401。
- 资源不存在和无权访问通常采用 404，避免泄漏跨用户资源存在性。
- 同源浏览器请求依赖 `credentials: same-origin` 自动携带会话 cookie。

具体字段与 endpoint 以 `/openapi.json` 为准。