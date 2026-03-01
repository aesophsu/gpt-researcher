# ARCHITECTURE (for Codex + Maintainers)

> 目标：给代码助手与维护者一个“先看即用”的项目地图，减少误改和重复探索。

## 1) 顶层目录职责

| 路径 | 职责 | 备注 |
|---|---|---|
| `gpt_researcher/` | 核心通用库（研究、检索、抓取、写作、配置、提示词） | Python SDK 主体，`GPTResearcher` 在这里 |
| `backend/` | FastAPI 服务层（HTTP/WebSocket/API 编排、报告导出、医疗扩展） | 通过 `gpt_researcher` 执行业务 |
| `frontend/nextjs/` | Next.js 前端（主 UI、WebSocket 客户端、历史记录、移动端布局） | 默认本地跑在 `:3000` |
| `multi_agents/` | LangGraph 多智能体流程（规划-研究-写作-发布） | 后端 `report_type=multi_agents` 时走这套 |
| `multi_agents_ag2/` | AG2 版本多智能体示例/实验实现 | 与 `multi_agents/` 平行，非主默认链路 |
| `docs/` | 文档站、示例、说明、博客 | 不参与线上运行时路径 |
| `scripts/` | 运维/导入/健康检查脚本 | 本仓库本地流程辅助 |
| `tests/` + `evals/` | 单测与评测 | `evals` 偏研究质量评估 |
| `data/` | 本地数据（如报告存储、医疗索引） | 默认 JSON 持久化 |
| `outputs/` | 生成物（md/pdf/docx/images） | 服务会挂载静态访问 |
| `mcp-server/` | MCP 相关示例/说明 | 与主流程通过 `gpt_researcher/mcp` 连接 |
| `terraform/` | 基础设施 IaC | 部署相关，不影响本地开发主闭环 |

## 2) 公共库位置与模块

公共库主位置：`gpt_researcher/`

核心模块（按职责）：

| 模块 | 作用 | 关键文件 |
|---|---|---|
| Agent 编排 | 研究主入口与生命周期 | `gpt_researcher/agent.py` |
| Skills | 研究、写作、上下文管理等可组合能力 | `gpt_researcher/skills/researcher.py`, `writer.py`, `context_manager.py`, `deep_research.py` |
| Actions | 原子动作（检索、查询规划、报告生成、流式输出） | `gpt_researcher/actions/` |
| Prompts | Prompt family 与报告模板 | `gpt_researcher/prompts.py` |
| Retrievers | 各搜索源适配层（tavily/pubmed/semantic/mcp...） | `gpt_researcher/retrievers/` |
| Scraper | 网页/文档抓取实现 | `gpt_researcher/scraper/` |
| Document | 本地与在线文档加载器 | `gpt_researcher/document/` |
| Vector Store | 向量库封装与 LangChain 适配 | `gpt_researcher/vector_store/vector_store.py` |
| Config | 默认配置 + 环境变量合并 | `gpt_researcher/config/` |
| Utils | 枚举、LLM 调用、日志、成本统计等 | `gpt_researcher/utils/` |
| MCP 客户端 | MCP 研究与工具选择链路 | `gpt_researcher/mcp/` |

后端公共能力（可复用）位置：

| 模块 | 作用 | 关键文件 |
|---|---|---|
| 依赖注入容器 | Manager + Service + Repository 装配 | `backend/server/dependencies.py` |
| 报告持久化 | JSON 存储与仓储接口 | `backend/server/storage/json_report_storage.py`, `repositories/report_repository.py` |
| 报告导出 | Markdown -> PDF/DOCX | `backend/utils.py` |
| WebSocket 协调 | 任务启动、日志/流式报告回传 | `backend/server/websocket_manager.py` |
| 报告类型编排 | Basic/Detailed/Multi-agent 路由到核心库 | `backend/report_type/` |

## 3) 推荐调用方式（按稳定性与维护成本）

### A. 本地开发（推荐）

1. 进入 Nix 环境：`make nix-shell`
2. 安装依赖：`make bootstrap`
3. 终端 A：`make backend-dev`
4. 终端 B：`make frontend-dev`

说明：这是仓库维护的主路径，前后端契约最完整（HTTP + WebSocket + 导出 + 历史记录）。

### B. Python SDK（嵌入式调用）

```python
from gpt_researcher import GPTResearcher
from gpt_researcher.utils.enum import Tone

researcher = GPTResearcher(
    query="你的问题",
    report_type="research_report",
    report_source="hybrid",
    tone=Tone.Formal,
)
await researcher.conduct_research()
report = await researcher.write_report()
```

适用：在你自己的 Python 服务/脚本里直接复用研究核心。

### C. HTTP / WebSocket API（前后端分离）

- HTTP：`/report/`, `/api/reports`, `/api/chat` 等（见 `backend/server/routers/`）
- WS：`/ws`，通过 `start {json}` 启动研究（见 `backend/server/websocket_manager.py`）

适用：自定义前端或外部系统对接。

### D. CLI（快速离线生成）

```bash
python cli.py "你的问题" --report_type research_report --tone formal --report_source hybrid
```

适用：批处理和脚本自动化。

## 4) Nix 环境结构

当前仓库只有 1 套 flake：

- `flake.nix`（根目录）
- `flake.lock`（锁定依赖）

`flake.nix` 中的 inputs：

- `nixpkgs` -> `nixos-24.11`
- `flake-utils`

`devShell`：

- `devShells.default`（唯一）
- 包含工具：`python311`, `uv`, `nodejs_22`, `git`, `just`
- shellHook：关闭 Next telemetry，并给出 backend/frontend 启动提示

结论：

- 目前没有多 flake / 多 devShell 分层。
- 环境分层是“单 shell + Makefile 任务分工”。

## 5) RAG / LangGraph / gpt-researcher 集成点

### 5.1 gpt-researcher 主链路（核心）

入口：`gpt_researcher/agent.py` 的 `GPTResearcher`

执行路径：

1. `conduct_research()` -> `skills/researcher.py`
2. 根据 `report_source` 分流：`web | local | hybrid | langchain_documents | langchain_vectorstore | azure`
3. 检索：`actions/retriever.py` 选择 `retrievers/*`
4. 抓取与压缩：`scraper/*` + `skills/context_manager.py`
5. 写作：`skills/writer.py` + `actions/report_generation.py` + `prompts.py`
6. 导出：后端 `backend/utils.py` 转 `pdf/docx`

### 5.2 RAG 集成点

RAG 主要在以下接口收敛：

- 文档加载：`gpt_researcher/document/*`
- 向量库封装：`gpt_researcher/vector_store/vector_store.py`
- 向量检索路径：`report_source=langchain_vectorstore` -> `ResearchConductor._get_context_by_vectorstore()`
- 混合检索路径：`report_source=hybrid`（本地文档上下文 + web 上下文拼接）
- 医疗本地优先检索（Qdrant）：`backend/server/websocket_manager.py` + `backend/server/medical_service.py`

实践建议：

- 业务要可控时优先 `hybrid`，并设置 `query_domains`。
- 需要强私有知识时优先 `langchain_vectorstore` 或医疗本地检索链路。

### 5.3 LangGraph 集成点

内置 LangGraph 多智能体在 `multi_agents/`：

- 图构建：`multi_agents/agents/orchestrator.py`（`StateGraph` 节点：`browser/planner/human/researcher/writer/publisher`）
- 任务入口：`multi_agents/main.py::run_research_task`
- 后端接入点：`backend/server/websocket_manager.py` 中 `report_type == "multi_agents"` 分支

前端另有“外部 LangGraph Cloud”入口：

- `frontend/nextjs/components/Langgraph/Langgraph.js`
- 使用 `@langchain/langgraph-sdk` 直连远端 host（与内置 `multi_agents` 是两条链路）

### 5.4 三者关系总结

- `gpt_researcher`：默认与主干执行引擎（单体可复用库）。
- `RAG`：`gpt_researcher` 的一种输入增强方式（文档/向量/混合/医疗本地）。
- `LangGraph`：可替代编排层（用于多智能体流程），通过 `multi_agents` 或外部 LangGraph SDK 接入。

## 6) 对 Codex 的修改建议（工作约定）

- 优先改 `gpt_researcher/`，把逻辑保持在库层，后端只做编排。
- 改接口契约时同时检查：
  - `frontend/nextjs/hooks/useWebSocket.ts`
  - `backend/server/websocket_manager.py`
  - `backend/server/models.py` / `types/data.ts`
- 任何“默认行为”调整，至少同步三处：
  - `gpt_researcher/config/variables/default.py`
  - 前端默认设置（`app/page.tsx` + 移动端回退）
  - 文档（本文件或 README）

## 7) 快速入口索引

- 后端应用入口：`main.py`, `backend/server/app.py`
- 前端入口：`frontend/nextjs/app/page.tsx`
- 核心 SDK 入口：`gpt_researcher/agent.py`
- WebSocket 协议处理：`backend/server/server_utils.py`, `backend/server/websocket_manager.py`
- 多智能体入口：`multi_agents/main.py`
- Nix 环境：`flake.nix`

