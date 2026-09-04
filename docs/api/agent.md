# Agent / Coach API

## 职责

Agent 领域负责 Agent Runtime、工具写入草案/执行、预算与状态；Coach 负责干预评估、建议、行动尝试和反馈闭环。

## 前端 Service

- `agentApi.ts`：Agent Runtime、写入草案、执行、状态与指标。
- `coachApi.ts`：Coach 偏好、Nudge、Action Attempt、Feedback。

## Contract 原则

- 高影响写操作优先采用“draft -> 用户确认 -> execute”，UI 不因为导航或展示建议自动写入。
- Runtime 内部 planner/provider 可以变化，但稳定 UI Contract 不暴露内部实现耦合。
- 错误返回只暴露安全摘要；provider 原始异常、prompt、密钥和内部查询不得透出。
- 运维/诊断 endpoint 默认 **Internal**；实验性 planner/graph 能力默认 **Experimental**。

具体 request/response 以 OpenAPI 和 `agentApi.ts` / `coachApi.ts` 类型为准。