# Mnemox 知识层、检索底座与 Agent 架构决策

日期：2026-07-26
状态：已采纳（Adopted），作为 Phase 1 / Phase 2 的设计依据
关联文档：[路线图](../../roadmap.md) · [需求基线](../../requirements.md) · [技术基线](../../technical.md)
前序决策：[2026-06-08 语音/RAG激励/Agent 设计](2026-06-08-voice-rag-motivation-agent-design.md) · [2026-06-15 自主 Coach 设计](2026-06-15-autonomous-coach-agent-design.md) · [2026-06-22 自学习路线图](2026-06-22-search-token-coach-learning-roadmap.md)

本文档回答五个问题：数据底盘要不要重构、知识如何建模关联、检索底座怎么选、Agent 用框架还是自研、自学习怎么落地。每个决策都给出理由和验收标准，后续实现以此为准。

---

## D1. 数据底盘评估：关系型核心保留，做三处增量，不推倒重来

当前 22 个 SQLAlchemy 模型构成的关系型核心是健康的（用户隔离、事件流、目标任务、复习、记忆状态机都已成型），不存在需要重写的结构性问题。需要的是三处增量：

| 增量 | 内容 | 迁移方式 |
| --- | --- | --- |
| 知识层 | 新增 `concepts` 与 `concept_edges` 两张表（见 D2） | Alembic 新增表 |
| 检索统一 | 定义 `ContextStore` 接口，收敛 RAG / 记忆 / 笔记三套割裂检索（见 D3） | 新增服务层接口，不改表 |
| FSRS 调度 | 复习/Anki 表增加 `stability`、`difficulty`、`last_review_at` 等字段，调度算法从手写 SM-2 风格切换为 `py-fsrs` | Alembic 加列，旧字段保留过渡 |

另有一项数据迁移：`wrong_questions.knowledge_point` 目前是自由文本字符串，需回填映射为 `concept_id` 外键（原字符串列保留一个版本周期作为回退）。

## D2. 概念图谱：封闭 schema 的领域图，不采用 Microsoft GraphRAG 管线

### 决策

以"概念（知识点）"为一等实体建立轻量领域图谱，存储在 SQLite 中。**不引入** MS GraphRAG 的开放域实体抽取、社区检测与全局摘要管线，**不引入** Neo4j 等独立图数据库。

理由：学习领域的本体是封闭且已知的；用户自带 API Key，承担不起 GraphRAG 的索引成本；核心查询是 1–2 跳局部遍历，SQL 足够。

### Schema 草案

```text
concepts
  id, user_id, name, name_normalized,  -- 归一化名用于去重合并
  description, mastery FLOAT,          -- 概念级掌握度（由行为数据计算）
  source, created_at, updated_at

concept_edges
  id, user_id, from_concept_id, to_concept_id,
  edge_type,      -- prerequisite_of | related_to
  confidence FLOAT, source, created_at

concept_links    -- 既有实体挂接到概念
  id, user_id, concept_id,
  target_type,    -- chapter | note | question | wrong_question | anki_card
  target_id, link_type,  -- covers | explains | tests | drills
  created_at
```

### 抽取与维护管线

1. **上传时抽取**：资料解析出章节后，每章一次 LLM 调用，输出该章 5–15 个概念、相互关系与先修依赖（JSON schema 约束输出）。
2. **存量回填**：从 `wrong_questions.knowledge_point`、笔记标题/标签批量抽取回填。
3. **概念归一**：以 embedding 相似度 + LLM 复核合并同义概念（"贝叶斯定理" ≈ "贝叶斯公式"）。
4. **降级纪律**：图谱构建失败不阻塞资料上传主流程；图谱不可用时检索退回向量/关键词，行为与现有 RAG 降级一致。

### 图谱之上的两个核心应用

- **联想引擎**：事件触发（保存笔记 / 聊天提及概念 / 学完章节）→ 抽取概念 → 图上 1–2 跳查询邻居及其挂接的旧笔记、旧错题 → 价值判定（新颖度 × 关联强度 × 是否薄弱点）→ 通过 Coach nudge 治理层（冷却/免打扰/每日上限）呈现。低价值联想宁可不发。
- **薄弱点下钻**：错题 → 概念 → 先修缺口 → 定位资料小节 → 生成针对性卡片与最小任务。

## D3. 检索底座：ContextStore 接口先行，OpenViking 为首选实现候选

### 三个事物的关系（消除混淆）

- **概念图谱**：领域数据模型（两张 SQLite 表），**必建**，与任何检索底座兼容，不参与选型。
- **检索底座**：向量化存储与召回的基础设施，**二选一**：OpenViking 或 Chroma+自研。长期不并行运行两套底座（重复索引成本）。
- 两者关系：图谱节点通过 URI/ID 引用底座中的文本块；底座负责"找到相关文本"，图谱负责"知道什么和什么有关"。

### 决策：接口先行

定义薄接口 `ContextStore`（职责：`ingest`（入库+分块+分层摘要）、`retrieve`（混合召回）、`load_tiered`（按 L0/L1/L2 粒度取内容）、`forget`），业务代码只依赖接口。"一步到位"锁定的是**接口与 schema**，不是具体供应商——这是唯一工程上可靠的一步到位。

### OpenViking spike（1–2 天，三道验收关）

OpenViking（火山引擎 2026-01 开源，Apache-2.0）的统一上下文模型（记忆/资料/技能挂 `viking://` 虚拟文件树）与 L0/L1/L2 分层加载，直接命中本项目"检索碎片化"与"token 预算分层"（P1）两个痛点。当前 Chroma 实际使用率低，是更换底座成本最低的窗口。但其开源仅半年且含 C++ 组件，采纳前必须通过：

| # | 验收关 | 通过标准 |
| --- | --- | --- |
| 1 | Windows 桌面打包 | 能随 Electron + venv 分发方式在干净 Windows 环境安装运行，无需用户手动编译 |
| 2 | 无 embedding key 降级 | 用户仅有 chat key 时，入库与检索有可用降级路径（或可接本地 embedding），不破坏现有降级纪律 |
| 3 | 检索质量与成本 | 用一本教材 + 一批笔记实测：召回质量不低于现有 Chroma 栈，token 消耗有可测量下降 |

**通过** → OpenViking 实现 `ContextStore`，资料/笔记/记忆检索逐步迁入；**不通过** → 同一接口下用 Chroma + SQLite 保底实现，损失分层加载但架构不变。两条路径下，概念图谱、联想引擎、Agent 设计均不受影响。

> **Spike 结论（2026-07-26）**：验收关 1（Windows 桌面打包）不通过——约 90 个传递依赖、客户端/服务器架构、安装即改写宿主核心依赖版本。已按保底路径执行，详见 [spike 结论记录](2026-07-26-openviking-spike-result.md)。

## D4. Agent：自研 agentic loop，不引入外部 agent 框架/运行时

### 重申并扩展 2026-06-08 的结论

`earendil-works/pi`（及同类 TS agent 运行时）**继续不引入**。当时的理由（第二运行时、跨进程状态同步、Provider 配置重复、私密笔记权限面扩大）全部仍然成立；若 OpenViking 入选，则"缺的是统一上下文层而非 agent 运行时"这一判断被进一步坐实。LangGraph 等 Python 编排框架同样暂不引入：本项目不需要图状多 Agent 编排，引入只增加依赖重量。

### 为什么自研不可怕：成本结构分析

一个 agent 框架提供三样东西：LLM 循环、工具注册、状态/流式。其中 LLM 循环在既有 Multi-LLM Router 上约数百行代码；工具注册与流式（SSE、AgentJob 表）已存在。而真正昂贵的部分——**领域工具、草案确认写入层、Coach 治理（冷却/免打扰/上限）、自学习闭环**——任何框架都不提供，且本项目已完成大半。结论：**循环自己写，底座用轮子（D3），框架跳过。**

### AgentKernel 目标形态（Phase 2）

```text
loop（上限 N 步，全程流式可见）:
  1. 组装上下文：目标 + ContextStore 检索 + 图谱邻域 + 画像/记忆
  2. LLM 决策：调用工具 / 产出草案 / 结束
  3. 执行工具（只读直接执行；写入类仅生成草案，落 draft 表）
  4. 观察结果，回到 1
终态：行动草案（用户确认后写入，复用既有确认流）+ 过程日志（AgentExecutionLog）
```

配套：引入进程内调度器（APScheduler），支撑三类后台任务——Coach 触发评估（复习到期/任务积压/连续中断）、夜间知识巩固（扫描新概念与新连接，产出知识周报）、画像与记忆维护。调度产生的触达一律经过 Coach 治理层，桌面通知走既有桥接。

## D5. 自学习：四层结构，只学"何时、以何种方式介入"，永不触碰安全规则

| 层 | 内容 | 状态 |
| --- | --- | --- |
| 1. 偏好沉淀 | `agent_learning_profile` 的 traits / do_more / avoid | 已有，继续 |
| 2. 干预效果学习 | 每次触达记录（上下文特征, 所用技能/策略, 结果：展示→点击→执行→行为变化）；先按技能×情境分桶统计采纳率，数据量足够后升级为 bandit 选择（epsilon-greedy 或 Thompson Sampling）决定"此刻用哪个 Coach 技能、是否打扰" | Phase 2 新建 |
| 3. 记忆进化 | 候选 → 确认/锁定/忽略 的人在环流程（已有）；若 OpenViking 入选，叠加其 session 记忆自动进化 | 已有 + 增强 |
| 4. 评测护栏 | 每周离线评测与指标看板：建议执行率、中断恢复时长、复习按时率 | Phase 2 新建 |

**硬边界**：自学习的可调空间仅限干预时机、技能选择、措辞风格与频率；草案确认流程、用户隔离、不可信上下文包装、免打扰规则不在学习空间内，任何策略都不得绕过。

## D6. 集成战略：连接成熟软件，不与其竞争

| 集成 | 方式 | 阶段 |
| --- | --- | --- |
| Obsidian 读 | vault 即本地 md 文件夹：watchdog 监听 + 增量索引，替代一次性导入 | Phase 1 |
| Obsidian 写回 | 复习提示、知识周报、联想发现写入 vault 指定子文件夹 | Phase 2 |
| 复习调度 | `py-fsrs` 替换手写 SM-2 风格调度 | 立即 |
| Anki | 评估 AnkiConnect：Mnemox 决定"复习什么"，Anki 承载"复习界面" | Phase 3 评估 |
| MCP Server | 暴露画像/图谱/错题/复习状态给 Claude Desktop 等 AI 客户端 | Phase 3 |
| 语音 | TTS（edge-tts）→ 按住说话 STT → 全双工，依次推进 | 后置 |
| 音频资源 | 仅本地音频导入 + B 站官方 iframe 嵌入；**不实现任何站点下载功能**（ToS 与仓库合规风险） | 约束 |

配套收缩：**Markdown 编辑器功能冻结**（保留现状供独立使用，不再投入）；新增页面默认冻结，除非能回答"降低了哪个行为的执行阻力"。

## 北极星指标

产品衡量标准从"回答质量"切换为**行为转化**：

1. 建议执行率（Agent/Coach 建议 → 实际执行的比例）
2. 中断恢复时长（番茄中断/断档后回到学习的时间）
3. 复习按时率（到期复习按时完成比例）
4. 每周有效学习时段数

新功能立项前必须回答：它改善上述哪一项？

## 风险与开放问题

- OpenViking Windows 打包与运行足迹未验证（spike 关 1）；失败则走保底路径，不阻塞。
- 概念抽取质量依赖用户所配模型；需要抽取结果的用户可编辑入口（错误概念可改名/合并/删除）。
- 联想引擎的价值判定阈值需要真实使用数据调参；上线初期宁可保守少发。
- FSRS 迁移需处理存量 SM-2 数据的参数换算（py-fsrs 提供默认初始化，存量卡按"已复习历史重放"或"保守重置"择一，spike 时决定）。
