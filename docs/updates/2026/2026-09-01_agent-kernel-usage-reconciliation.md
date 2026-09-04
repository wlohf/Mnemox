# 更新记录：AgentKernel 供应商用量与配置单价对账

## 本周期目标

- 在不削弱调用前预算硬停止的前提下，把供应商返回的真实 Token 与保守估算分开记录。
- 允许用户按自己的 Provider 合同配置输入/输出单价，生成可回放的参考成本。

## 指标与范围

- 对应北极星指标：不直接改变行为指标；降低 Phase 2 灰度的不可观测成本风险。
- 范围：AgentKernel 非流式模型调用、Provider 设置、逐任务/逐日账本和调试展示。
- 明确不做：不内置会过期的供应商价目表，不读取供应商发票，不把参考成本当作结算金额，不扩展到通用多 Agent。

## 已完成

### 1. Provider 用量归一化

- OpenAI-compatible Chat Completions、Claude Messages 和 Gemini GenerateContent 会把供应商 usage 归一化为输入、输出和总 Token。
- Provider 每次调用前清除旧 usage，避免失败请求误复用上一响应数据；Kernel 对未返回 usage 或失败的调用单独累计 `unreconciled_calls`。

### 2. 预算与价格双轨

- 调用前仍用供应商无关的保守估算执行模型调用数和 Token 硬上限；供应商真实 usage 只用于调用后对账，不反向放宽已执行的护栏。
- Provider 设置新增每百万输入/输出 Token 的美元单价。两项齐全才计算 `configured_cost_usd`，缺失时不猜价；0 价格可用于本地或免费模型。
- checkpoint、终态结果和逐用户 UTC 日汇总分别保留本次增量与累计值，续跑不会重复计算历史尝试。

### 3. 前端与迁移

- AI Provider 设置增加两个价格输入，服务端校验有限、非负且有上界的数值。
- Agent 调试区展示供应商真实 Token 和配置单价参考成本，同时保留估算预算进度。
- Alembic `20260901_17` 和 SQLite lightweight migration 增加两个可空价格字段；旧 Provider 默认不配置价格，行为不变。

## 失败、降级与数据变更

- 供应商没有返回 usage：保留估算和未对账调用数，不显示虚构的真实 Token。
- 用户没有配置完整单价：真实 Token 仍记录，成本保持不可用。
- 迁移 / 兼容：新增列均可空，无历史回填；回滚迁移只移除价格列，不修改 AgentJob 历史 JSON。
- 权限与隐私：价格沿用 `AIProviderSetting.user_id` 隔离；账本不保存 Prompt、响应正文或 API Key。

## 验证结果

- 后端聚焦回归：`60 passed`，覆盖三类 Provider usage、价格校验、Kernel 恢复/预算和迁移链。
- 前端聚焦回归：`2 files / 6 tests passed`。
- 前端生产构建：`npm run build` 通过。

## 验收证据与发布

- 当前证据为本地模拟供应商响应和 SQLite/Alembic 结构回归。
- 真实密钥、供应商账单抽样和 PostgreSQL 16 候选升级尚未执行，不标记为远程验收通过。
- 回滚方式：应用回退后新增 JSON 字段会被旧版本忽略；数据库回滚可移除两个价格列。

## 已知限制 / 后续事项

- 部分 OpenAI-compatible 代理可能不返回 usage，或其 Token 口径与上游供应商不同。
- 下一步完成旧 Planner fallback 产品化，并在候选环境做真实账单抽样核对。
