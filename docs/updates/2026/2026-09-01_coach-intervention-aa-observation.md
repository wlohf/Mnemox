# 更新记录：Coach 干预效果 A/A 观察与成熟归因

## 本周期目标

- 在改变任何 Coach 策略前，先验证稳定分桶、不可变埋点、归因窗口和覆盖率统计是否可信。
- 让“自学习”保持可审计、默认关闭且不可自动调参。

## 已完成

### 1. 确定性 A/A 分桶

- `COACH_INTERVENTION_EXPERIMENT_ENABLED` 默认 `false`；开启后，用实验 ID、分配版本和用户 ID 的 SHA-256 结果生成 0–9999 稳定桶。
- 桶按配置比例映射到 control/shadow，但 v0 两组执行完全相同的 Coach 策略；每条 assignment 都明确 `mode=aa_observation`、`policy_applied=false`。
- 实验 ID 或版本变化会形成新分配空间，不静默复用旧实验。

### 2. 不可变、最小化的生命周期埋点

- Coach 建议创建时将实验 ID、分配版本、桶号、组别和模式写入 explainability，并在 created/shown/accepted/started/completed/abandoned 等不可变学习事件中保持同一 assignment。
- 事件载荷只接受固定字段、类型和长度；不包含用户 ID、建议标题、正文或反馈自由文本。
- feature flag 关闭时不新增 assignment，既有 Coach 行为完全不变。

### 3. 用户级成熟归因报告

- `/api/analytics/coach-experiment` 只查询当前登录用户，并按 7 天归因窗统计接受、开始、完成、真实领域事件完成、放弃和拒绝。
- 未走完整窗口的曝光单列为 pending；旧的未埋点曝光单列为 uninstrumented，不混入成熟率分母。
- 报告固定 `policy_behavior_changed=false`、`decision_readiness.ready=false`，明确相关性不能证明因果。
- Agent 页只在开关启用时显示 A/A 分组、成熟曝光和归因中数量，并明确不会自动调整建议。

## 数据、回滚与非目标

- 本模块不新增 schema；规范来源继续是现有 `learning_events` 不可变账本与 Coach nudge explainability。
- 回滚只需关闭 feature flag；历史事件保留以供审计，不影响现有策略。
- 当前不做真实 A/B、bandit、跨用户可见报表、自动阈值调整或自动写入。

## 验证结果

- 后端聚焦回归：`36 passed, 4 subtests passed`，覆盖稳定分桶、两组可达、关闭无埋点、事件隐私、成熟/pending/未埋点分母和真实领域完成归因。
- 前端服务测试：`13 passed`。
- 前端生产构建：`npm run build` 通过。

## 后续事项

- 只在明确的测试/灰度环境打开开关，先验证 A/A 两组覆盖与指标近似，再考虑任何策略差异。
- 真人样本、最小样本量、停止条件和独立决策文档齐全前，保持 `ready=false`。
- 下一模块推进知识巩固与周报的来源追溯、去重和可回滚草案。
