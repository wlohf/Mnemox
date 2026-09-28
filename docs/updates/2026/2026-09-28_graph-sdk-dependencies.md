# Graph SDK 依赖安装与集成核验

用户要求补齐 Graphiti 依赖，并核实 Neo4j、Graphiti 的实际接入范围。

## 修改

- 将 `graphiti-core>=0.30.1,<0.31` 纳入标准 `backend/requirements.txt`，与现有 Neo4j SDK 一起安装；开发依赖、Docker 和桌面构建继承该声明。
- 从 `requirements-spike.txt` 移除重复图 SDK 声明及过时的“禁止进入标准依赖”说明；Qdrant 继续作为额外评测依赖。
- 更新根 README、后端 README 和技术基线，明确安装 SDK、启用图服务、产品流程接入三者的区别。
- 补充功能评估的交付范围：源码自部署可简化账号运营和平台计费，配置、功能一致性和数据恢复仍需保证。

## 功能范围

- Neo4j 已接入 GraphStore、关联查询、Knowledge/Learning Path、用户级投影重建、就绪检查、灰度与 SQL 回退。默认 `GRAPH_BACKEND=sql`，需明确选择 Neo4j 并配置外部图数据库。
- Graphiti 已接入已审核 SQL 记忆声明的时态投影、BM25 current/as-of 查询和 SQL 核验，提供独立认证 API。默认 `GRAPHITI_ENABLED=false`；首次使用及记忆变更后需显式重建，尚未进入聊天、Coach 或前端的自动记忆流程。
- 本次只读核查的既有后端容器处于 exited，选择 SQL，Graphiti 和知识路径等开关关闭；既有 Neo4j 容器正常运行不能证明应用已在使用图功能。
- 本次不修改图开关、不重建现有应用容器、不执行用户数据迁移。既有部署需在后续更新依赖或重建应用后才获得新 SDK。

## 验证

- 在既有后端镜像上使用离线 wheel 安装 Graphiti、pytest 和 pytest-asyncio；`pip check` 无依赖冲突。实测 SDK 为 `graphiti-core 0.30.2`、`neo4j 6.3.0`。
- 使用独立 Docker internal 网络和临时 Neo4j 5.26 实例，SQL 使用临时 SQLite，屏蔽仓库 `.env`，只读挂载当前源码。没有连接已有用户图数据库；Graphiti 测试使用禁止外部 LLM/embedding/reranker 调用的客户端。
- 真实图数据库集成：`test_neo4j_shadow_integration.py`、`test_neo4j_knowledge_path_integration.py`、`test_graphiti_shadow_integration.py`、`test_graphiti_temporal_integration.py`，合计 **6 passed**，1 条上游 Pydantic 弃用警告。
- 后端完整回归：**725 passed、49 skipped、70 subtests passed**，约 296 秒。初评中缺 Graphiti 依赖导致的 4 个失败全部消除；另有 1 项此前跳过的 Graphiti SDK 契约测试开始执行并通过。49 个跳过项保留其外部平台/集成条件，不当作通过；上述 6 项真实图集成另行启用执行。
- Windows 打包/安装和线上部署不在本次验证范围；安装 SDK 不替代这些验收。

临时日志：`/tmp/mnemox-graph-dependency-build.log`、`/tmp/mnemox-graph-dependency-integration.log`、`/tmp/mnemox-graph-dependency-full-tests.log`。临时图容器和网络已清理，未修改既有图数据。
