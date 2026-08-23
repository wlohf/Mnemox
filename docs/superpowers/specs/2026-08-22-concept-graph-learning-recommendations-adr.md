# 概念图谱与学习推荐闭环决策

> 日期：2026-08-22
>
> 状态：已实现；SQL 为唯一规范来源，Neo4j 不进入当前运行时。

## 1. 问题与边界

统一检索和资料投影已能找到材料，但原有概念图只有节点、关系和挂接，没有稳定别名、可审核来源、人工合并迁移或可信的先修缺口。学习状态能够保存证据，但没有把先修阻塞、FSRS、目标和错误记录组合为用户可解释的下一步行动。

本决策只完成概念图谱与学习推荐两条 Phase 1 主链，不引入 Neo4j、LangGraph、Graphiti、多 Agent、自动写计划或绕过用户确认的执行器。

## 2. SQL 规范数据

Alembic revision `20260822_11` 同时提供 PostgreSQL 迁移与 SQLite lightweight 兼容：

```text
concepts.review_status
concept_edges.review_status

concept_aliases
  user_id, concept_id, alias, alias_normalized, source

concept_source_evidence
  user_id, concept_id, edge_id, source_type, source_id,
  source_version, excerpt, confidence, review_status

concept_audit_events
  user_id, concept_id, operation, actor, payload, created_at

user_concept_state
  attempt_count, correct_count, hint_count
```

概念名称和别名在同一个用户范围内解析到唯一规范概念。关系类型支持 `prerequisite_of`、`part_of`、`related_to`、`example_of` 与 `contradicts`；兼容输入 `prerequisite`。所有关系均校验两端归属，先修关系禁止形成环。

自动抽取只读取现有资料正文，不发起模型请求或网络访问：标题、结构化定义、标记词、括号别名和明确的先修箭头生成 `pending` 候选。只有用户确认概念及其关系后，它们才参与先修缺口与推荐；人工录入的错题知识点是明确的用户输入，因此直接标记 `confirmed`。

## 3. 生命周期与人工治理

```text
资料 SQL 写入 / 更新
  → RetrievalProjection 更新来源版本
  → 本地概念候选、别名、关系和摘录
  → pending
  → 用户确认 / 拒绝
  → confirmed / rejected

资料更新 / 删除
  → 删除旧 source_id + source_version 的图谱证据
  → 清理只属于该资料的自动关系与未确认概念
  → 保留人工确认、其他资料证据及已有学习记录
```

人工操作包括改名、保留旧名为别名、添加别名、合并、拆分、审核及删除。合并会迁移概念挂接、关系、来源证据、学习证据、错题引用、投影队列和操作审计；重复关系和同源证据按自然键去重。删除会解除错题引用并保留不依赖已删除概念外键的删除审计。

错题录入会自动创建或解析用户填写的概念、建立章节/错题挂接，并写入第一次答错的直接证据；错题复习使用与复习中心一致的 **FSRS 优先、SM-2 降级** 调度，并在同一领域事务内回填 `review_result`。删除错题同步清除其来源证据和图谱挂接。

## 4. 学习状态与推荐

直接证据包括答题、回忆、解释、迁移应用、提示依赖和复习结果。学习时长、频率、重复提问、中断及恢复属于间接信号，只允许调整置信度和遗忘风险，不能独立提高掌握度。状态重算同时派生答题、正确和提示计数，保留事件来源、模型版本及回放幂等。

推荐为只读计算，候选类型包括：

- `review_due`：到期或高遗忘风险的 FSRS 复习。
- `prerequisite_gap`：阻碍当前概念的已确认先修知识。
- `retrieval_practice`：掌握度看似较高但直接证据不足。
- `targeted_practice`：最近错误、低分证据或典型误区。
- `continue_goal`：与活跃目标和资料相关的下一段学习。

排序公式固定公开：

```text
0.28 × 遗忘风险
+ 0.20 × 目标相关度
+ 0.24 × 先修阻塞
+ 0.16 × 错误频率
+ 0.12 × 截止 / 复习紧迫度
- 0.12 × 最近重复疲劳
```

每项返回中文原因、建议行动、耗时、分项得分、相关目标、阻塞概念、证据 ID、复习计划与 FSRS 稳定性。接口不创建计划、不修改目标，也不执行未确认动作。

## 5. Neo4j 受控结论

当前用户范围、最多五跳的先修遍历、关系审核、身份合并和推荐均可通过 SQLite/PostgreSQL 完成；专项测试已覆盖先修环、跨用户关系、更新残留、删除残留、人工确认、合并迁移与推荐解释。因此当前没有证明图数据库部署和双写一致性的额外成本可以换来必要收益。

结论：**保留 SQL 图谱，不引入 Neo4j 运行时依赖，也不提前锁定 GraphStore 实现。** 只有真实数据证明多跳查询维护性或性能不足后，才重新开启受控 Spike；任何候选图存储仍必须可以由规范 SQL 重建。

## 6. 验证命令

```bash
cd backend
python -m pytest -q tests/test_concept_graph_closure.py tests/test_learning_recommendations.py
python -m pytest -q tests/test_schema_migration.py
python -m pytest -q

cd ../frontend
npm test
npm run lint
npm run build
```

正式 PostgreSQL 生产升级、真实 Electron 安装验收、真实 Vault 数据验收以及真实学习者 holdout 校准继续独立执行；本决策不把 CI smoke 或合成专项测试冒充生产发布。
