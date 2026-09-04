# Knowledge API

## 职责

知识领域负责 Claim 抽取、Entity Resolution、Claim Relation、Association、Knowledge Path、Graph Runtime/Projection 状态，以及 Knowledge Lab 的审核入口。

## 前端 Service

- `knowledgeApi.ts`：Resolution 等知识治理能力。
- `knowledgeLabApi.ts`：Knowledge Lab 聚合视图、抽取和审核。
- `associationApi.ts`：Association 查询。

## Contract 原则

- SQL canonical 数据仍是事实源；Neo4j / Graphiti 属于可选 projection / temporal slice，不改变前端业务 Contract。
- UI 不根据当前 graph backend 拼不同 endpoint；后端负责 runtime 选择和 fallback。
- Association / Path 的可解释字段属于产品 Contract，不能只返回不可追溯的分数。
- Stage 7 Graphiti / Neo4j 相关诊断接口应视为 **Experimental / Internal**，除非被明确纳入稳定 UI。

具体 request/response 以 `/openapi.json` 和对应 service 类型为准。