# Knowledge Base 流水线 — 验证与复盘

本文记录一次端到端手动验证（2026-05-29），便于复盘 Shadow Wiki 如何从本地 Obsidian `wiki/` 产出 `shadow-wiki/wiki/knowledge/` 页面。

---

## 前置条件

| 项 | 要求 |
|---|---|
| Python / uv | `uv sync` 已完成 |
| `.env` | `KNOWLEDGE_BASE_PATH` 指向 vault 的 **wiki/** 子目录（不扫 `raw/`） |
| 数据库 | `uv run python scripts/resource_mgr.py init` |
| LLM | 本地 LM Studio / Ollama，或云端 DashScope（见下文回退） |

示例（本机 vault）：

```env
KNOWLEDGE_BASE_PATH=/Users/xiaotongchen/Documents/obsidian/knowledge_base/wiki
KNOWLEDGE_BASE_SIMILARITY_THRESHOLD=0.85
```

vault 目录结构示例：`concepts/`、`comparisons/`、`entities/`、`summaries/`、`index.md`。

---

## 阶段 0 — 文档提交（Task 7）

```bash
git log -1 --oneline
# 13891f4 docs: knowledge base digest — README, SOP, workflow, architecture
```

涉及文件：`README.md`、`CLAUDE.md`、`docs/SOP.md`（§4.5）、`docs/workflow.md`、`docs/architecture.md`。

---

## 阶段 1 — 扫描入队（`--once`）

```bash
uv run python scripts/resource_mgr.py init
uv run python scripts/ingest/knowledge_base_scanner.py --once
uv run python scripts/resource_mgr.py status
```

### 本次实测结果

```
Scan complete: 18 queued, 0 skipped (unchanged), 0 skipped (similar)
Pending : 18
```

18 个 `.md` 全部首次入队（`change_type=new`，similarity=0.00）。

### 可选：仅预览不写库

```bash
uv run python scripts/ingest/knowledge_base_scanner.py --dry-run
```

### 强制全量重扫

```bash
uv run python scripts/ingest/knowledge_base_scanner.py --force --once
```

---

## 阶段 2 — 单条 Distill（处理 1 个 event）

### 方式 A — 正常（本地 LLM）

Worker 常驻时由轮询自动处理；或一次性处理一条：

```bash
uv run python -c "
from scripts.db import init_db, get_pending_events
from scripts.distill.worker import process_event
init_db()
events = get_pending_events(limit=1)
if events:
    process_event(events[0])
"
```

**要求：** LM Studio / Ollama 已启动，且模型能载入内存（本机 35B 约需 ~22GB）。

### 方式 B — 本地 OOM 时用 Qwen Cloud（本次实际采用）

**现象：** LM Studio 返回 HTTP 400，`Model loading was stopped due to insufficient system resources`（`qwen3.6-35b-a3b` 约 21.73GB）。

**说明：** 默认路由下 `CLASSIFY` / `SUMMARIZE` / `APPEND` 始终走本地；`USE_CLOUD_LLM=true` 仅影响 `CREATE_PAGE`。本地不可用时，验证脚本可临时把 `worker.call_llm` 指到云端（仅用于手工验证，非产品默认行为）：

```bash
uv run python -c "
import json
import logging
import scripts.distill.llm_router as lr
import scripts.distill.worker as worker
from scripts.db import init_db, get_connection, get_pending_events
from scripts.distill.worker import process_event

logging.basicConfig(level=logging.INFO)
worker.call_llm = lambda task, prompt, system='You are a helpful assistant.': lr._call_cloud(prompt, system)

init_db()
with get_connection() as conn:
    conn.execute(\"UPDATE events SET status='pending', error=NULL WHERE source='knowledge_base' AND status='failed'\")

e = get_pending_events(limit=1)[0]
raw = json.loads(e['raw_json'])
print('File:', raw.get('relative_path'))
process_event(e)
"
```

`.env` 需配置 `DASHSCOPE_API_KEY`，`CLOUD_LLM_BACKEND=qwen_cloud`（或 `QWEN_CLOUD_*`）。

### 本次实测结果

| 字段 | 值 |
|---|---|
| Event ID | 6 |
| 源文件 | `comparisons/langchain-vs-langgraph-vs-deepagents.md` |
| 标题 | Agent 框架演化对比：LangChain vs LangGraph vs DeepAgents |
| 耗时 | ~63s（3× CLASSIFY/SUMMARIZE/CREATE + 第 2 个 topic 的 CREATE） |
| 产出页面 | `wiki/knowledge/comparisons/ai-agent-frameworks.md` |
| | `wiki/knowledge/ai/llm-development.md` |

LLM 将单篇笔记分类为 **2 个** topic（`topics[:2]` 上限），故一次 event 可生成多页。

查看产出：

```bash
uv run python scripts/resource_mgr.py list
head -30 wiki/knowledge/comparisons/ai-agent-frameworks.md
```

页面结构：`## Overview` · `## Key Concepts` · `## Key Insights` · `## Sources` · `## Related Topics`（与代码 wiki 的 Recent Changes 不同）。

处理完成后：

```
Pending : 17
Modules : 3   # 含历史 auth/session + 2 个 knowledge/*
Last run: 2026-05-29 …
```

---

## 阶段 3 — 去重验证（再次 `--once`）

```bash
uv run python scripts/ingest/knowledge_base_scanner.py --once
```

### 本次实测结果

```
Scan complete: 0 queued, 18 skipped (unchanged), 0 skipped (similar)
```

已处理文件的 MD5 未变 → Stage 1 全部跳过，符合设计。

### 模拟「有意义更新」

```bash
echo "" >> /Users/xiaotongchen/Documents/obsidian/knowledge_base/wiki/concepts/rag-workflow.md
uv run python scripts/ingest/knowledge_base_scanner.py --once
# 预期：仅 rag-workflow 相关 1 条入队；再 distill 后应对已有页 incremental append
```

---

## 阶段 4 — 自动化（可选）

每日 09:00 CST，self-hosted Mac runner：

1. `knowledge_base_scanner.py --once`
2. 批量 `process_event`（workflow 内联 Python）
3. `git add wiki/` → commit → push

见 [github-actions-setup.md](github-actions-setup.md)、`.github/workflows/daily-knowledge-digest.yml`。

---

## 阶段 5 — 回归测试

```bash
uv run pytest -v
# 预期：48 passed
```

---

## 故障对照

| 症状 | 原因 | 处理 |
|---|---|---|
| `KNOWLEDGE_BASE_PATH not set` | `.env` 未配置 | 添加路径并指向 `…/wiki` |
| `KNOWLEDGE_BASE_PATH does not exist` | 路径错误 | 修正为本机 vault 绝对路径 |
| Event `failed` + LM Studio 400 / insufficient memory | 本地模型过大 | `resource_mgr.py dev` 释放内存；换更小模型；或验证时用云端脚本（上方式 B） |
| `Pending` 不减少 | worker 未运行 | 启动 `worker.py` 或用手工 `process_event` |
| 二次扫描仍大量入队 | 首次未 distill 完 / 用了 `--force` | 正常完成处理后再 `--once` |
| 产出路径不是 `knowledge/…` | event `source` 不是 `knowledge_base` | 检查 scanner 的 `push_event` |

---

## 数据流简图

```
Obsidian  vault/wiki/*.md
        │  MD5 + similarity (0.85)
        ▼
knowledge_base_scanner.py  →  SQLite events (source=knowledge_base)
        ▼
worker._handle_knowledge_event()
        │  CLASSIFY → SUMMARIZE → CREATE_PAGE | APPEND
        ▼
shadow-wiki/wiki/knowledge/{category}/{slug}.md
        ▼
MCP search_wiki / Claude Code
```

---

## 本次验证清单

- [x] 文档 Task 7 提交：`13891f4`
- [x] `.env` 配置 `KNOWLEDGE_BASE_PATH`
- [x] `--once` 扫描：18 条入队
- [x] 单条 distill：1 event → 2 个 `wiki/knowledge/` 页面（Qwen Cloud 回退）
- [x] 二次扫描：0 入队 / 18 unchanged
- [ ] 剩余 17 条 pending（需本地 LLM 可用或批量云端验证脚本）
- [ ] GitHub Actions self-hosted runner（按需）

---

## 相关文档

- 实现计划笔记：[docs/1.md](1.md)
- 运维 SOP §4.5：[SOP.md](SOP.md)
- 时序图：[workflow.md](workflow.md)
- Runner 安装：[github-actions-setup.md](github-actions-setup.md)

*记录时间：2026-05-29*
