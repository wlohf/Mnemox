# 更新记录：安全错误摘要与诊断边界

## 本周期目标

- 防止供应商、网络、数据库或工具异常把密钥和完整上游响应写入持久状态、日志或 API。
- 保留足够的错误类别与上下文，使失败仍可排查、可统计、可重试。

## 已完成

### 1. 统一错误安全工具

- 新增 `app/utils/error_safety.py`，提供文本脱敏、有界异常摘要和基于脱敏内容的稳定指纹。
- 覆盖 Authorization/Bearer、API Key/Token/Secret/Password 键值、URL userinfo 与查询密钥、OpenAI/GitHub/Slack/Google/AWS 常见 Token、JWT 和私钥块。
- 脱敏在截断前执行；结果折叠为单行并受调用方字段长度限制，避免长 HTML/JSON 错误污染日志或数据库。

### 2. 持久失败边界

- AgentManager 的失败任务和执行日志只保存异常类型与安全摘要。
- Planner rules fallback 不再把原始供应商异常写入 brief 元数据。
- projection outbox 和资料检索投影的 `last_error` 写入前统一脱敏；重试清理的次级异常同样处理。
- RAG 运行状态、AgentRuntime、Kernel 回收器与 outbox worker 的错误快照和日志采用相同契约。

### 3. API 与日志边界

- 未分类 AI Provider 错误在返回 UI 前统一脱敏；鉴权、模型不存在、限流和服务故障仍优先返回稳定产品文案。
- RAG 测试、资料 AI 操作、Agent/Coach/学习者模型和常用领域错误的 HTTP 详情经过统一脱敏，正常领域消息保持不变。
- 关键 Agent/Coach/AI/RAG/投影路径移除原始异常 traceback 日志，改为安全异常类型与摘要。
- Agent 任务/日志、outbox 与检索投影在读取时再次脱敏，阻止旧错误正文原样经 API 暴露。

## 数据与兼容性

- 本模块不新增 schema，不改变业务状态码、重试次数或回退策略。
- 失败摘要可能从原始 SDK 文本变为 `ExceptionType: 安全摘要`，依赖完整错误字符串做自动化判断的代码应改用稳定错误码或状态字段。
- 更早写入数据库的错误行尚未原地改写；现有读取边界会拦截敏感形态，后续仍需独立、可审计的数据清理方案。

## 验证结果

- 安全错误工具专项：`6 passed`。
- Agent/Coach、画像事务、outbox、AgentKernel 与检索投影聚焦回归：`99 passed, 4 subtests passed`。
- 最终后端全量：`491 passed, 10 skipped, 58 subtests passed`。
- 覆盖明文/JSON Authorization、URL 凭据与查询密钥、常见 Token、私钥、多行/超长错误、AI 响应正文、Agent 持久失败和 outbox 重试失败。

## 已知限制 / 后续事项

- 正则脱敏是纵深防御，不应把真实密钥放入异常、模型 prompt 或业务字段；Provider 客户端仍必须从源头避免记录请求头和请求体。
- 集中式日志保留期限、访问权限、结构化错误码覆盖率和历史错误行清理仍待发布治理阶段收口。
- 下一步执行全量后端/前端回归、文档链接与静态扫描，修复本轮跨模块改动暴露的兼容问题。
