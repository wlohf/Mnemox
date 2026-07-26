# 文档导航（Documentation Index）

> 更新日期：2026-07-26

本索引用于减少文档分散与重复说明。文档分为四类：**现行基线**（描述当前与下一步，持续维护）、**架构决策**（superpowers/specs，按日期归档，新决策覆盖旧决策）、**历史参考**（不再维护，仅供理解演进过程）、**持续记录**（按周期追加）。

## ✅ 现行基线（先看这些，按顺序）

| 文档 | 回答的问题 |
| --- | --- |
| [需求基线](requirements.md) | 产品定位、北极星指标、已交付/下一阶段需求、非目标 |
| [路线图](roadmap.md) | **接下来做什么、按什么顺序做**（阶段顺序、完成标准、冻结清单的唯一权威来源） |
| [技术基线](technical.md) | 当前代码里已存在的实现、约定与技术债；§9 为未实现的演进方向 |
| [进度文档](progress.md) | 当前版本状态、验证结果与执行快照 |

## 🧭 架构决策（superpowers/specs）

| 日期 | 文档 | 状态 |
| --- | --- | --- |
| 2026-07-26 | [知识层 / 检索底座 / Agent 架构决策](superpowers/specs/2026-07-26-knowledge-layer-context-substrate-agent-architecture.md)（D1 数据底盘 · D2 概念图谱 · D3 ContextStore/OpenViking · D4 自研 AgentKernel · D5 自学习 · D6 集成战略） | **当前有效** |
| 2026-06-23 | [目标驱动 Agent 记忆实施计划](superpowers/specs/2026-06-23-goal-driven-agent-memory-implementation-plan.md) | 已实现（v1.2.0） |
| 2026-06-22 | [搜索 / Token / Coach 自学习路线图](superpowers/specs/2026-06-22-search-token-coach-learning-roadmap.md) | 部分被 07-26 决策吸收 |
| 2026-06-15 | [自主 Coach Agent 工程设计](superpowers/specs/2026-06-15-autonomous-coach-agent-design.md) | 已实现（Coach Kernel） |
| 2026-06-08 | [语音 / RAG 激励 / Agent 设计](superpowers/specs/2026-06-08-voice-rag-motivation-agent-design.md) | 部分实现；拒绝 pi 的结论由 07-26 决策 D4 重申 |

决策变更约定：任何选型或架构变化（如 OpenViking spike 结论）必须新增或修订本目录下的决策文档，不允许只改代码不改文档。

## 🚀 启动与运行

- 启动指南（主文档）：`/启动指南.md`
- 后端说明：`/backend/README.md`
- 前端说明：`/frontend/README.md`
- 部署与安全提示：根 `README.md` 的「安全与部署提示」章节

## 🗂 持续记录

- 功能更新维护说明：[updates/README.md](updates/README.md)
- 更新文档模板：[updates/_template.md](updates/_template.md)
- 周期记录目录：`updates/2026/`

## 📦 历史参考（不再维护）

以下文档保留用于理解演进过程，内容可能与现状不符，请勿作为实现依据：

**规划/方案类**（方向性内容已被 07-26 架构决策与路线图吸收）

- 早期总体设计：`/docs/system-design.md`
- AI 教练系统设计：`/docs/AI教练系统设计.md`
- AI 教练快速开始：`/docs/AI教练-快速开始.md`
- 从 RAG 到 AI 教练完整方案：`/从RAG到AI教练-完整方案.md`
- 语音 / 笔记联想 / 个性化激励方案评估：`/docs/voice-rag-motivation-plan-2026-06-08.md`
- 中期产品力提升实施方案：`/docs/midterm-product-power-plan-2026-06-22.md`

**UI/体验优化记录**

- UI 更新说明：`/UI-UPDATE.md`、`/UI-UPDATE-V2.md`
- UI 优化方案：`/docs/ui-optimization-plan.md`、`/docs/ui-optimization-plan-v2.md`

**根目录旧启动/说明文件**

- `/SETUP.md`、`/快速配置说明.txt`：内容已并入 `/启动指南.md` 与根 `README.md`
- `/release-notes-v*.md`：各版本发布说明，随版本归档

## ⚠️ 安全与配置

- 请勿在文档或脚本中存放真实 API Key，统一使用占位符。
- 示例配置一律使用占位符；真实密钥仅存在于本地 `.env` 或设置页加密存储。
