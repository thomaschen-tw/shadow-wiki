# PulseWiki — 录屏流程文件（Hackathon Demo）

> **项目一句话：** PulseWiki 把 PR、Slack、Linear、代码 diff 和知识库笔记自动蒸馏成**结构化、可检索的活文档**，并通过 **MCP** 让 Cursor 直接查 wiki，而不是暴力 grep 全仓库。  
> **录屏主命令：** `bash dev_up.sh`（单条事件、不拖垮队列）  
> **建议时长：** 4–6 分钟  
> **口播语言：** 中文（屏幕可英文）

---

## 一、项目解决什么问题

### 1.1 痛点（录屏开头 20–30 秒口播）

| 痛点 | 具体表现 |
|------|----------|
| **文档一次性写完就腐烂** | README / Confluence 在第一次提交后很少更新，与真实系统脱节 |
| **知识碎片化** | 架构决策在 PR 评论、Slack 线程、Linear 工单、工程师脑子里，没有单一真相源 |
| **新人/on-call 成本高** | 接手模块要翻几十条 PR、搜 Slack，Senior 反复讲同一件事 |
| **AI 编码助手上下文不足** | Cursor / Copilot 只能扫代码，看不到「为什么当时这么设计」 |

### 1.2 PulseWiki 的解法（对应画面：架构图）

```
多源事件（GitHub / Slack / Linear / diff / Obsidian）
        ↓ 连接器写入队列
   SQLite 事件队列 + FTS5 全文索引
        ↓ worker 每 30s（或 dev_up 内联一次）
   本地 LLM：分类 → 摘要 → 追加到已有页面
   云端 LLM：仅「首次见到的模块」创建新页面（控成本）
        ↓
   wiki/{module}.md（YAML + Overview / Recent Changes / …）
        ↓ MCP（6 个工具）
   Cursor：search_wiki / get_module / …
```

**和「普通 RAG」的区别：** 不是扔一堆文档进向量库，而是**按模块持续追加变更史**，且默认本地处理、隐私可控。

---

## 二、录屏前准备（开录前完成，不要拍进正片）

### 2.1 环境检查清单

| # | 操作 | 预期效果 | 失败时 |
|---|------|----------|--------|
| 1 | 打开 **LM Studio**，加载 `qwen/qwen3.6-27b`（与 `.env` 一致），点 **Start Server** | `localhost:1234` 可访问 | 录屏改用仓库里已有 `wiki/`，跳过 live distill |
| 2 | `cd pulse-wiki && uv sync` | 依赖安装完成 | — |
| 3 | `cp .env.example .env` 并填 `LMSTUDIO_MODEL`、`GITHUB_TOKEN`（可选） | 配置就绪 | — |
| 4 | `uv run python test_env.py` | 末尾 `23 passed`，LM Studio 相关为 PASS | 看 FAIL 项逐项修 |
| 5 | `uv run python scripts/resource_mgr.py llm` | `qwen/qwen3.6-27b ✓`，Pipeline 指向 lmstudio | 改 `.env` 与 LM Studio 模型 id 一致 |
| 6 | `uv run python scripts/resource_mgr.py status` | 了解 `Pending` 数量；**录制主路径建议 Pending &lt; 5** | 过多则勿跑 `demo.sh`，只用 `dev_up.sh` |
| 7 | Cursor 已启用 MCP（项目内 `.cursor/mcp.json` → Settings → MCP → pulse-wiki） | 录屏后半可调用 `search_wiki` | 用终端 `uv run python -c "…search_wiki…"` 代替 |

### 2.2 录屏时不要用的命令

| 命令 | 原因 |
|------|------|
| `bash demo.sh` | 会起后台 worker 并可能处理**整队** pending（含大量 knowledge 事件），耗时长、易失败 |
| `bash dev_up.sh --daemon` | 会持续吃队列，镜头要等很久 |
| `bash dev_up.sh --cloud` | 除非 DashScope 已付费；免费 tier 可能 403 |

---

## 三、正片流程（推荐分镜）

### 场景 A — 问题与方案（0:00 – 0:45）【无终端】

| 步骤 | 画面 | 口播要点 |
|------|------|----------|
| A1 | 标题页：**Context-Aware Documentation Agents (PulseWiki)** | 参加 Hackathon 的项目名 |
| A2 | 三张示意图或 bullet：PR 评论 / Slack / 过期 Wiki | 「文档写一次就错一辈子」 |
| A3 | 打开 `README.md` 滚到 **Architecture** Mermaid 图 | 多源 ingest → 队列 → 本地/云 LLM → wiki → MCP |

**此阶段系统无操作。**

---

### 场景 B — 环境可信（0:45 – 1:15）【终端】

#### 步骤 B1：`uv run python scripts/resource_mgr.py llm`

**执行后效果：**

- 终端打印 `.env` 里配置的 `LMSTUDIO_MODEL`、`OLLAMA_MODEL`、`QWEN_CLOUD_MODEL`
- 显示 **Pipeline will use → lmstudio / qwen/qwen3.6-27b**
- 若 LM Studio 正常：模型名后有 **✓**
- 评委看到：不是黑盒，模型与配置可对齐

**内部无写文件。**

---

#### 步骤 B2：`uv run python scripts/resource_mgr.py status`（可选）

**执行后效果：**

```
Pending : N
Failed  : M
Last run: 时间戳
Modules : K
```

- **Pending**：等待蒸馏的事件数（SQLite `events` 表）
- **Modules**：已索引的 wiki 模块数
- 口播：「系统有队列健康度，不是静默失败」

---

### 场景 C — 核心演示：一条 PR diff 变成活文档（1:15 – 3:00）【终端 + 编辑器】

#### 步骤 C1：`bash dev_up.sh`

**脚本内部顺序与每步效果：**

| 子步骤 | 脚本做什么 | 你屏幕上看到 | 系统实际效果 |
|--------|------------|--------------|--------------|
| C1.1 | `uv sync` | `✓ Dependencies ready` | 确保 venv 依赖齐全 |
| C1.2 | `test_env.py` | 绿字 PASS / 黄字 WARN | 校验 LM Studio、DB 目录、GitHub token 等 |
| C1.3 | `resource_mgr.py init` | `Database initialized.` | 创建/确认 `db/shadow.db` 表结构 |
| C1.4 | `resource_mgr.py status` | Pending/Modules 数字 | 若 Pending 很多，会出现**黄色警告**（不会 drain 全队列） |
| C1.5 | `ingest_diff.py` 推送测试 diff | `Queued event #XX` + `Raw backup : raw/commit_*.md` | SQLite **新增 1 条** `source=manual` 事件；`raw/` 存 diff 备份 |
| C1.6 | **内联** `process_event`（非后台 worker） | 日志：`Local LLM call backend=lmstudio model=…` | 见下表「蒸馏三阶段」 |
| C1.7 | `resource_mgr.py list` | 列出模块路径与摘要 | 终端显示如 `auth/session` |
| C1.8 | `find wiki …` | 最新 `.md` 文件列表 | 确认 wiki 目录有输出 |

**蒸馏三阶段（针对本条 code 事件，约 1–4 分钟，视 LLM 速度）：**

| 阶段 | LLM 任务 | 效果 |
|------|----------|------|
| 1. CLASSIFY | 本地模型 | 判断 diff 影响哪些模块，如 `["auth/session"]` |
| 2. SUMMARIZE | 本地模型 | 生成结构化摘要（改了什么、影响组件） |
| 3a. 模块已存在 | APPEND | 在 `wiki/auth/session.md` 的 **## Recent Changes** 顶部**插入**新条目（含日期、PR 号） |
| 3b. 模块不存在 | CREATE_PAGE（仅当 `USE_CLOUD_LLM=true` 走云） | 新建 `wiki/{module}.md` 含 Overview 等章节 |

**本演示 diff 内容：** 增加 `create_session` / `validate_session`（Redis session 相关）。  
**预期文件变化：** `wiki/auth/session.md` 的 `last_updated` 变为今天，`recent_prs` 增加 `#dev-…`，Recent Changes 多一段。

**成功标志：** 终端 `RESULT status=done`，脚本以 `Dev bring-up complete` 结束（非 daemon 模式）。

**失败标志：** `RESULT status=failed` — 常见原因：LM Studio OOM、模型名不匹配。  
**Plan B：** 不切镜头，直接打开**已提交**的 `wiki/auth/session.md` 讲解结构，口播「刚才 live 蒸馏与此相同」。

---

#### 步骤 C2：在编辑器打开 `wiki/auth/session.md`

**给观众看：**

| 区域 | 说明 |
|------|------|
| YAML frontmatter | `module`, `last_updated`, `recent_prs`, `tags` |
| `## Overview` | 模块职责（首次创建时由 LLM 写，后续 append 不一定改） |
| `## Recent Changes` | **今天日期 + PR 号 + 变更 bullet**（本次演示的核心产出） |
| `## Known Issues` / `## Related Modules` | 可提及为扩展位 |

**口播：** 「没有人手写这篇文档，是 worker 从 diff 蒸馏出来的；以后每个 PR 都会 append 到这里。」

---

### 场景 D — AI 编码助手消费上下文（3:00 – 4:15）【Cursor 或终端】

#### 步骤 D1：Cursor 中调用 MCP（推荐）

在 Cursor 对话中输入（按顺序）：

```
请用 pulse-wiki 搜索：redis session token
```

**预期效果：** Cursor 调用 `search_wiki`，返回 `auth/session` 等模块及高亮 snippet。

```
请读取 auth/session 模块全文
```

**预期效果：** Cursor 调用 `get_module("auth/session")`，返回 frontmatter + 正文。

```
根据 wiki，我们项目的 session 是怎么创建和校验的？
```

**预期效果：** Cursor 基于 wiki 回答（Redis、SHA-256、TTL 等），**无需** `grep -r session` 全仓库。

**口播：** 「PulseWiki 是 Cursor 的上下文层，不是替代 IDE。」

---

#### 步骤 D2：终端验证 MCP（Cursor MCP 未配置时的备选）

```bash
uv run python -c "
from scripts.mcp_server import search_wiki, get_module
print('=== search ===')
print(search_wiki('redis session', 3))
print('=== module (first 500 chars) ===')
print(get_module('auth/session')[:500])
"
```

**执行后效果：**

- `search_wiki`：FTS5 命中 `auth/session`，snippet 含 `<b>session</b>` 高亮
- `get_module`：打印 YAML + Markdown 正文前 500 字

**内部：** 读 `wiki/auth/session.md` + 查 `db/shadow.db` 的 `wiki_fts` 表。

---

### 场景 E — 差异化与商业/责任（4:15 – 5:00）【幻灯片或 .env】

| 步骤 | 画面 | 口播 | 效果 |
|------|------|------|------|
| E1 | `.env` 中 `USE_CLOUD_LLM=false`、`LOCAL_LLM_BACKEND=lmstudio` | 默认本地、隐私友好 | 无执行 |
| E2 | 架构图「Cloud 仅 CREATE_PAGE」 | 控云成本 | 无执行 |
| E3 | （可选）`wiki/knowledge/concepts/ai-agents.md` | 同一套管道支持 Obsidian 知识库 | 展示团队+个人知识统一检索 |
| E4 | Responsible AI | 敏感 diff 可不出网；ingest 过滤在 roadmap | 无执行 |

---

### 场景 F — 收尾（5:00 – 5:30）

```bash
uv run pytest -q
```

**执行后效果：** `49 passed` — 证明不是纯 demo 脚本，有自动化测试。

**口播：** 仓库地址、`bash dev_up.sh` 一键复现、文档 `docs/README.md`。

---

## 四、可选加分镜头（时间充裕再做）

### 镜头 G：`github_poller` 拉真实 PR（需 `GITHUB_TOKEN`）

```bash
uv run python scripts/distill/worker.py &
uv run python scripts/ingest/github_poller.py --limit 3
# 等待约 30–60 秒
uv run python scripts/resource_mgr.py list
```

| 步骤 | 效果 |
|------|------|
| poller | 从 GitHub API 拉最近 PR diff，**批量** `push_event` 到 SQLite |
| worker | 每 30s 处理最多 10 条 pending，写入/更新 `wiki/` |
| list | 出现与仓库真实路径相关的 module 名 |

**注意：** 比 `dev_up.sh` 慢，适合「规模感」镜头，不适合 5 分钟主线。

---

### 镜头 H：知识库路径 `bash dev_up.sh --knowledge`

| 步骤 | 效果 |
|------|------|
| scanner `--once` | 扫描 `KNOWLEDGE_BASE_PATH` 下变更的 `.md` |
| 内联 distill 1 条 | 生成或更新 `wiki/knowledge/.../*.md`（Overview / Key Insights 结构） |

需 `.env` 配置 `KNOWLEDGE_BASE_PATH`。

---

## 五、逐步对照表（录制时打印/第二屏）

| 顺序 | 命令 / 动作 | 耗时参考 | 观众应看到的结果 |
|------|-------------|----------|------------------|
| 0 | 问题口播 + 架构图 | 45s | 理解痛点与数据流 |
| 1 | `resource_mgr.py llm` | 10s | 模型 ✓，pipeline=lmstudio |
| 2 | `bash dev_up.sh` | 2–4min | event queued → LLM 日志 → done |
| 3 | 打开 `wiki/auth/session.md` | 30s | Recent Changes 有新条目 |
| 4 | Cursor `search_wiki` + `get_module` | 60s | AI 能答 session 设计 |
| 5 | `pytest -q` | 5s | 49 passed |
| 6 | 结尾口播 | 15s | TW 场景、开源地址 |

---

## 六、故障与口播补救

| 现象 | 原因 | 录屏补救 |
|------|------|----------|
| `dev_up` 立刻 `failed` | LM Studio 未开 / 模型名错 / OOM | 打开已有 `wiki/auth/session.md` + 终端只跑 `search_wiki` |
| `403 FreeTierOnly` | 用了 `--cloud` 且 DashScope 免费额度用尽 | 改本地 `dev_up.sh`，勿用 `--cloud` |
| Pending 很多 | 之前跑过 knowledge scanner | 口播「队列可积压，生产用 worker 异步处理」；演示只用 `dev_up` 单条 |
| MCP 无 pulse-wiki | `.cursor/mcp.json` 未配置 | 用本文「步骤 D2」终端命令 |
| CLASSIFY 分到奇怪模块 | 小模型幻觉 | 口播「可加人工 review 队列」指向 `docs/architecture-roadmap.md` |

---

## 七、相关文档

- [docs/README.md](README.md) — 文档总索引  
- [workflow.md](workflow.md) — 数据流时序图  
- [knowledge-base-verification.md](knowledge-base-verification.md) — 知识库 E2E 测试  
- [architecture-roadmap.md](architecture-roadmap.md) — 生产级演进 backlog  

---

*录屏流程版本：2026-05-29 · 主路径已用 `dev_up.sh` + 本地 LM Studio 27B 验证通过*
