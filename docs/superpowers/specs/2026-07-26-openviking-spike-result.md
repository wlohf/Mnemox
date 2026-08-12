# OpenViking Spike 结论：验收关 1 不通过，走 Chroma+关键词保底路径

日期：2026-07-26
状态：已裁决（Decided）
上游决策：[2026-07-26 架构决策 D3](2026-07-26-knowledge-layer-context-substrate-agent-architecture.md)

## 验收结果

| # | 验收关 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | Windows 桌面打包 | **不通过** | 见下 |
| 2 | 无 embedding key 降级 | 未测（关 1 已否决） | — |
| 3 | 检索质量与成本 | 未测（关 1 已否决） | — |

## 关 1 证据（venv 实测，openviking 0.4.11）

1. **依赖足迹不可承受**：`pip install openviking` 拉入约 90 个传递依赖，包含 scrapy、twisted、litellm、mcp、opentelemetry 全套、volcengine SDK×2、tree-sitter 及 10 种语言解析器、pdfplumber、trafilatura 等。对"Electron + 本地 venv"的桌面分发形态，安装体积、安装时长与失败面均不可接受。
2. **架构模型是客户端/服务器**：Python 包顶层仅暴露 `get_binding_client` / `pyagfs`；`openviking-sdk` 是 HTTP 客户端（`SyncHTTPClient`/`AsyncHTTPClient`）。终端用户机器上需要常驻并管理一个独立服务进程，超出本项目桌面形态的运维预算。
3. **宿主依赖污染实锤**：安装过程直接改写了宿主应用核心依赖版本（openai 2.33→2.30 降级、pydantic→2.12.5、cryptography→49、urllib3→2.7 等），与现有栈存在真实版本冲突。spike 后已卸载并恢复环境（openai 恢复至 ≥2.33）。

## 裁决

按 D3 预案执行**保底路径**：`ContextStore` 接口不变，由 `KeywordContextStore`（已落地，`backend/app/services/context_store.py`）承接统一检索；语义检索继续由现有 LlamaIndex+Chroma 通道提供，后续可在同一接口下增加 Chroma 混合实现。分层加载（L0/L1/L2）语义已在接口与保底实现中保留。

## 重新评估条件（满足其一再开新 spike）

- Mnemox 出现服务器化部署形态（此时独立服务进程与依赖重量可接受）。
- OpenViking 官方提供轻量嵌入模式或大幅裁剪依赖。
- 社区出现可独立分发的精简 server 二进制，且 Windows 分发验证通过。
