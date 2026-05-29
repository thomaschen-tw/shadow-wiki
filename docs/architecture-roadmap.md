# Shadow Wiki — 架构缺口清单与演进路线图

> **文档性质：** 首席架构师评审（DevOps / KM / LLM Ops / MCP）  
> **评审基准：** 当前代码库（`worker.py`、`db.py`、`llm_router.py`、`mcp_server.py`、ingest 连接器、knowledge_base 流水线）+ 原「Knowledge Base Daily Digest」实现计划  
> **风格：** 只谈会崩的地方，不谈「架构优雅」。

---

## 0. 与原 Knowledge Base Digest 实现计划的对照

原计划在对话中定义的是 **Obsidian 知识库每日蒸馏** 子系统（Tasks 1–7）。截至当前 main 分支，状态如下：

| 原计划项 | 状态 | 评审备注 |
|----------|------|----------|
| Task 1 `KNOWLEDGE_BASE_PATH` 等配置 | ✅ 已落地 | `.env` 为唯一配置源；`resource_mgr.py llm` 可校验模型 id |
| Task 2 `knowledge_base_scanner.py` | ✅ 已落地 | MD5 + 相似度门控有效；**仅扫描器级去重，无队列级合并** |
| Task 3 Knowledge prompts | ✅ 已落地 | 与 code prompts 分流正确 |
| Task 4 `worker` 按 `source` 分发 | ✅ 已落地 | **无 compaction、无分类纠错回路** |
| Task 5 GitHub Actions daily digest | ✅ 已落地 | 依赖 self-hosted；**无队列 SLA 监控** |
| Task 6 Runner 文档 | ✅ 已落地 | `docs/github-actions-setup.md` |
| Task 7 README / SOP / workflow 文档 | ✅ 已落地 | 另增 `dev_up.sh`、`knowledge-base-verification.md` |
| **原计划未覆盖的企业级能力** | ❌ 未做 | 下文 P0–P2 即为与原计划的差分 |

**结论：** 原计划把 Shadow Wiki 从「仅代码事件」扩展到「个人知识库摄入」，完成度良好；但原计划 **刻意声明不改动** `db.py` 核心语义、**未设计** 多 worker、重试、向量检索、权限与可观测性——这些正是从「本地玩具」到「团队生产工具」的鸿沟。本文件取代原聊天式计划稿，作为 **架构债与演进 backlog** 的单一事实来源。

---

## 1. 异步事件队列与状态机鲁棒性（Queue & State Machine Resiliency）

### P0

#### 【原子 Claim / 租约（Lease）机制】

**架构痛点分析：**  
`get_pending_events()` + `mark_event_processing()` 是 **两次独立连接、无事务、无 `UPDATE … RETURNING`**。启动第二个 `worker.py` 或 Actions 批处理与本地 worker 并行时，同一 event 会被双消费；崩溃在 `processing` 中间态的事件 **永久僵尸**（SOP 里用手工 SQL 救场——这说明设计已承认会崩）。SQLite 写锁 + 单线程串行 distill（每 event 多次 LLM、分钟级）时，摄取突发（大 monorepo 一夜 200 PR、Slack 爆栈）会让 `pending` 指数堆积，**摄取层无背压**，只有磁盘和耐心在扛。

**推荐的生产级实现方案：**  
- 短期（仍 SQLite）：`UPDATE events SET status='processing', lease_owner=?, lease_until=? WHERE id IN (SELECT id FROM events WHERE status='pending' … LIMIT N) RETURNING *`；租约过期自动回 `pending`。  
- 中期：PostgreSQL（`DATABASE_URL` 已预留）+ `SKIP LOCKED`；或 Redis / NATS JetStream 作队列，SQLite 只存 wiki 索引。  
- 摄取侧：`push_event` 前按 `(source, dedupe_key)` 唯一约束合并（见下条）。

#### 【事件去重键与摄取背压（Dedupe Key + Ingest Backpressure）】

**架构痛点分析：**  
`knowledge_base_scanner` 有 MD5/相似度门控，但 **GitHub/Slack/Linear 路径没有等价的 `dedupe_key`**（同一 PR `synchronize` 五次 = 五条 pending）。Connector 永不反压：Webhook 返回 200 即可，worker 跟不上时 **只有队列变长**。30s 轮询 + `limit=10` 意味着理论吞吐上限约 **20 event/分钟**，且每条 code event 常触发 3+ 次 LLM 调用——数学上必爆仓。

**推荐的生产级实现方案：**  
- 表字段：`dedupe_key TEXT UNIQUE`（如 `github:pr:owner/repo:42`、`slack:channel:ts`）。  
- `push_event` → `INSERT OR IGNORE` / upsert 刷新 `raw_json` 与 `updated_at`。  
- 配置：`MAX_PENDING_EVENTS`、`INGEST_PAUSE_WHEN_PENDING_GT`；connector 在超阈值时 503 + 告警。  
- PR 风暴：**Debounced ingest**（5–15 分钟内同 PR 只保留最新 diff）。

#### 【结构化重试 + 死信队列（Retry / DLQ）】

**架构痛点分析：**  
`mark_event_failed` 是一锤子买卖：**无 `retry_count`、无 `next_retry_at`、无错误分类**（OOM vs 429 vs 400 模型名错误全一样）。本地 Ollama OOM 后整条 event 进 `failed`，只能人肉 `UPDATE status='pending'`（SOP 已记录——这是运维债）。无 DLQ 意味着无法对「永久失败」做统计、告警、人工回放。

**推荐的生产级实现方案：**  
- 状态机扩展：`pending → processing → done | retry_wait | dead`。  
- `llm_router.call_llm` 外包一层：可重试异常（超时、429、5xx、OOM）指数退避 + jitter；不可重试（401、模型不存在、AST 失败）直接 `dead`。  
- DLQ 表或 `status='dead'` + `error_class`；`resource_mgr.py replay --dead --limit N`。  
- 与 `dev_up.sh --cloud` 的临时 patch 脱钩，做成正式 **fallback policy**（`LOCAL_LLM_FALLBACK=cloud|skip`）。

---

### P1

#### 【按源优先级与公平调度（Fair Scheduling）】

**架构痛点分析：**  
`ORDER BY created_at` 纯 FIFO。Knowledge 18 条 pending 会 **饿死** 实时 GitHub webhook；反之亦然。单队列无法表达「P0 生产 PR > P2 个人笔记」。

**推荐的生产级实现方案：**  
- `priority INT` + `source` 权重；worker 每轮 `LIMIT` 按加权拉取。  
- 或物理分队列：`events_code` / `events_knowledge`，独立 worker 进程与并发预算。

#### 【Worker 水平扩展与 LLM 并发预算】

**架构痛点分析：**  
「单 worker」= 单点 + 单并发。LM Studio 本身不支持高并发；盲目多进程只会 **把 OOM 从偶发变必然**。需要 **全局 semaphore**（如 Redis 或本地文件锁）限制同时在飞的 LLM 请求数 = 1（本地）或 N（云端）。

**推荐的生产级实现方案：**  
- 本地：`MAX_INFLIGHT_LOCAL=1`；云端：`MAX_INFLIGHT_CLOUD=4`。  
- Taskiq / Celery 仅当队列迁出 SQLite 后引入；否则先 **单进程 + 异步 IO 无意义**（瓶颈在 GPU）。

#### 【SQLite 生产边界文档化】

**架构痛点分析：**  
FTS5 + 事件表 + 多 connector 同写：**WAL 模式下尚可单机**，NFS/网络盘上的 Obsidian + DB 同目录是灾难。团队每人一台 Mac 跑 worker = **N 个分裂队列**，不是分布式系统。

**推荐的生产级实现方案：**  
- 单机个人：SQLite + WAL + `busy_timeout` 显式配置。  
- 团队：中央 Postgres + 对象存储上的 `wiki/` + Git 作为真相源（见维度 4）。

---

### P2

#### 【分布式任务队列（Celery / Taskiq / Temporal）】

**架构痛点分析：**  
只有队列深度上千、要多机 worker、要 cron 编排 compaction 时才值得。现在上 Celery = **用复杂度换想象中的扩展性**。

**推荐的生产级实现方案：**  
- 触发条件：`pending > 500` 持续 1h 或 明确要多 region runner。  
- 首选 **Temporal** 编排长事务 distill（多步 LLM + 补偿）；Celery 适合无脑异步。

---

## 2. LLM 蒸馏精度与知识「熵增」控制（LLM Distillation & Anti-Entropy）

### P0

#### 【模块页 Compaction / Consolidation Worker】

**架构痛点分析：**  
`append_to_section` **无限 prepend**（`wiki/manager.py` 注释已写明 newest-first）。同一 `auth/session.md` 经 50 个 PR 后：  
1）文件超过本地模型上下文 → append 阶段的 LLM **看不见历史**；  
2）FTS snippet 失真；  
3）MCP `get_module` 把垃圾喂给 Claude Code → **上下文污染**。  
Knowledge 路径仅有「前 40 字符去重」，**无段落级归档、无过期策略**。这是 **熵增死结**，不是优化问题。

**推荐的生产级实现方案：**  
- 新任务类型 `TaskType.CONSOLIDATE`（云端或强模型）：当 `module` 的 `Recent Changes` / `Key Insights` 超 N 行或 M token，折叠为「季度摘要」+ 归档区（`## Archive` 只保留链接）。  
- 触发：cron worker 或 `modules.token_count` 阈值。  
- 保留结构化 frontmatter + 最近 K 条原子变更；旧条目压缩为 bullet summary。  
- Knowledge 与 code 分流策略（code 保留 PR 号可追溯）。

#### 【分类结果校验与模块绑定锁（Classification Guardrails）】

**架构痛点分析：**  
本地 Qwen 把 PR 分到 `auth/session` 还是 `scripts/random_utils` **零校验**；错误分类一次，错误 append 永久留在错误页面（**交叉污染**）。`CLASSIFY` 输出 JSON 无 schema 强制、无 confidence、无 second-pass。Knowledge 路径 `topics[:2]` 更会 **一页变两页双倍幻觉**。

**推荐的生产级实现方案：**  
- 结构化输出：Pydantic + JSON schema mode（云端 fallback 校验）。  
- **路径白名单**：分类结果必须匹配 `modules` 表已有路径或 `ALLOWED_MODULE_PREFIXES`。  
- 低 confidence → `status='needs_review'` 而非直接写 wiki。  
- 可选：用 diff 路径启发式（`+++ b/` 文件列表）与 LLM 分类 **交叉验证**，不一致则 flag。

---

### P1

#### 【Human-in-the-Loop 审核队列（Review Queue）】

**架构痛点分析：**  
全自动 = 全自动出错。企业/wiki 场景需要「可驳回、可合并、可锁定」。

**推荐的生产级实现方案：**  
- 新状态 `pending_review` + 极简 UI（Streamlit / Obsidian 侧车）或 CLI `resource_mgr.py review list|approve|reject`。  
- 审核通过才 `append_to_section`；拒绝写 `classification_feedback` 表供 few-shot 提示词迭代。

#### 【提示词与模型版本化（Prompt / Model Registry）】

**架构痛点分析：**  
`prompts.py` 改一字，历史 wiki **语义断裂**；无法 A/B 或回滚。

**推荐的生产级实现方案：**  
- `prompt_version`、`model_id` 写入 event 处理记录或 frontmatter `distilled_by`。  
- 重大 prompt 变更触发 **re-distill 策略**（仅新 event，非全量重跑除非显式 `--rebuild`）。

#### 【Append 幂等与内容寻址（Idempotent Append）】

**架构痛点分析：**  
Worker 重试会导致 **重复 bullet**（除非人工 diff）。Knowledge 的 `i.lower()[:40]` 太脆。

**推荐的生产级实现方案：**  
- 每条 append 带 `event_id` / `content_hash` 写入隐藏 HTML 注释或 frontmatter `entries[]`。  
- 重试时检测 hash 已存在则 skip。

---

### P2

#### 【跨模块综合（Synthesize）与知识图谱】

**架构痛点分析：**  
`TaskType.SYNTHESIZE` 在 router 已定义但 **无 worker 调用路径**。无法回答「auth 与 billing 交界发生了什么」。

**推荐的生产级实现方案：**  
- 定时或手动触发：对 `related_modules` 聚类做 cloud synthesize 生成 `wiki/meta/cross-cutting-*.md`。  
- 长期：模块间 `[[wikilink]]` + 图索引（Neo4j 过重；先用 SQLite 边表）。

---

## 3. MCP 深度性能优化（MCP Server Productionization）

### P0

#### 【混合检索 Hybrid Search（FTS5 + 向量）】

**架构痛点分析：**  
`search_modules_fts` 仅 trigram FTS。「会话超时」「哪里 revoke token」类 **语义问法** 召回率极差；中文/中英混合更惨。Claude Code 会以为 wiki 没内容，然后 **退回全仓库 grep**——Shadow Wiki 价值归零。

**推荐的生产级实现方案：**  
- 本地轻量：**sqlite-vec** / LanceDB embedded / Chroma persistent；chunk 级（按 `##` 分段）embedding。  
- 查询：`0.7 * cosine + 0.3 * FTS rank`（Reciprocal Rank Fusion 亦可）。  
- 复用 distill 同一 embedding 模型（`bge-small` 本地）控制成本。  
- MCP `search_wiki` 增参 `mode=keyword|semantic|hybrid`（默认 hybrid）。

---

### P1

#### 【检索结果结构化与上下文预算（RAG Response Shaping）】

**架构痛点分析：**  
当前返回 `module + snippet`，无 **相关性分数、无 chunk 边界、无 freshness**。Agent 无法决定要不要 `get_module` 全文。

**推荐的生产级实现方案：**  
- 返回：`{path, score, section, snippet, last_updated, token_estimate}`。  
- 可选第四工具 `get_module_section(path, section)` 减少全文加载。

#### 【MCP 工具事实勘误】

**架构痛点分析：**  
评审问题中提到 `list_recent_changes` 缺失——**代码里已有**（`mcp_server.py`），但 **无模块级 diff、无依赖图**。真正缺的是让 Agent 「少调用、调得准」的工具，不是堆数量。

**推荐的生产级实现方案（按 ROI 排序）：**  
| 工具 | 用途 |  
|------|------|  
| `get_module_changelog(path, since)` | 仅返回 Recent Changes 段 |  
| `search_wiki` hybrid | 已述 |  
| `get_module_graph(path, depth)` | 基于 frontmatter `related` + import 静态分析（code 模块） |  
| `explain_pipeline_event(event_id)` | 调试 distill 来源 |  
| `get_classification_candidates(diff)` | 只分类不写库（dry-run） |  

不必急着上 20 个 tool；**超过 10 个 tool 会降低 Claude 选择正确率**。

#### 【MCP 鉴权与传输】

**架构痛点分析：**  
stdio MCP 假定 **单用户本机**。远程团队共用 wiki 时，stdio 不够。

**推荐的生产级实现方案：**  
- 可选 SSE/HTTP MCP + API key；只读 role / 读写 role 分离。  
- 与维度 4 RBAC 统一。

---

### P2

#### 【查询扩展（Query Expand）生产化】

**架构痛点分析：**  
`query_expand_prompt` 存在但 **未接入 MCP 检索路径**（dead code 气味）。

**推荐的生产级实现方案：**  
- `search_wiki` 内：本地 LLM 或规则扩展中英同义词 → 多查询 RRF 合并。  
- 记录 expand 日志供观测。

---

## 4. 团队级多用户协同与并发冲突（Concurrency & Team Collaboration）

### P0

#### 【Wiki 真相源：Git + PR 合并流（Git-as-SoT）】

**架构痛点分析：**  
`wiki/*.md` 直接 `write_text`，**无锁、无 merge、无 CRDT**。两人各跑 worker、或 GHA daily commit 与本地 worker 同时写 → **后写覆盖先写**，Git 冲突在 push 时才爆炸。Obsidian 同步（iCloud/Git）+ 自动化 commit = **冲突地狱**。

**推荐的生产级实现方案：**  
- **唯一写入者**：仅 CI bot 或仅中央 worker 写 `wiki/`；开发者机器只读 MCP。  
- 或：写前 `git pull --rebase`、写后 `git commit`；冲突文件 → `status=merge_required` 暂停自动 distill。  
- 文件锁（Redis `SETNX wiki:lock:{path}`）适合 **短临界区**，不能替代 Git。

#### 【数据源 ACL / 摄取过滤（Ingest ACL）】

**架构痛点分析：**  
Slack 全频道、Linear 全团队、GitHub 全 repo 进同一 wiki — **#finance、#hr、private repo** 会泄漏到 Claude Code 可检索的平面。这是 **合规雷**，不是功能偏好。

**推荐的生产级实现方案：**  
- `.env` + DB 表：`INGEST_ALLOW_SLACK_CHANNELS`、`INGEST_DENY_LINEAR_TEAMS`、`GITHUB_ALLOWED_PATHS`。  
- Connector 入口强制过滤；审计日志 `ingest_audit`。  
- MCP 侧：**敏感 module 前缀不可搜索**（`confidential/*` 不进 FTS/向量索引）。

---

### P1

#### 【多租户 / 命名空间（Tenant Namespace）】

**架构痛点分析：**  
单 flat `wiki/{module}.md` 无法服务多团队共用一套 Shadow Wiki 实例。

**推荐的生产级实现方案：**  
- `wiki/{team}/{module}.md` + event 表 `tenant_id`。  
- MCP 请求带 `tenant` context（HTTP header）。

#### 【Obsidian 与 shadow-wiki 目录边界】

**架构痛点分析：**  
`KNOWLEDGE_BASE_PATH` 读个人 vault，`WIKI_DIR` 写 repo 内 wiki — **两套宇宙**。团队不清楚哪个是 SSOT。

**推荐的生产级实现方案：**  
- 文档与架构图明确：**产出 SSOT = git 管理的 `shadow-wiki/wiki/`**；vault 只作输入。  
- 可选单向 sync 脚本，禁止双向自动写 vault。

---

### P2

#### 【中央文件锁服务】

**架构痛点分析：**  
纯 Git 足够时不需要锁服务；多非 Git 写入者才需要。

**推荐的生产级实现方案：**  
- Redis 锁 + 30s TTL；仅包在 `create_module` / `append_to_section` 外。

---

## 5. 运维监控与可观测性（Observability & Ops）

### P0

#### 【流水线 SLI + 告警（Pipeline SLOs）】

**架构痛点分析：**  
`resource_mgr.py status` 只有 pending/failed/last_run — **看不见 ingest 延迟、看不见 LLM 耗时、看不见队列年龄 P99**。系统挂三天没人知道，直到 Claude 答错。

**推荐的生产级实现方案：**  
- 表 `metrics_snapshots` 或 Prometheus exporter：`queue_depth`、`oldest_pending_age_sec`、`events_processed_total`、`llm_failures_by_class`、`llm_latency_histogram`。  
- 告警规则：`oldest_pending_age > 3600`、`failed_rate > 5%/h`、`worker_heartbeat missing`。  
- Worker 启动写 `heartbeat` 行；systemd / launchd 保活。

#### 【LLM 成本与 Token 计量（FinOps）】

**架构痛点分析：**  
`USE_CLOUD_LLM` 开启后 **CREATE_PAGE 烧云额度无上限**；本地无成本但有机会成本（GPU 时间）。Knowledge 双 topic 加倍调用 —— 你在用 2× 换不确定质量。

**推荐的生产级实现方案：**  
- 每次 `call_llm` 记录：`task_type, backend, model, prompt_tokens, completion_tokens, latency_ms, event_id`。  
- 日汇总 CLI：`resource_mgr.py costs --since 7d`。  
- 硬顶：`DAILY_CLOUD_TOKEN_BUDGET` 超限则 skip CREATE 改本地或 queue。

---

### P1

#### 【结构化日志与追踪（Structured Logging / Trace）】

**架构痛点分析：**  
当前 `logging.info` 文本行 — **无法把一次 event 的 classify→summarize→append 串成 trace**。排障靠肉眼 grep。

**推荐的生产级实现方案：**  
- `structlog` + `event_id` 贯穿；可选 OpenTelemetry span per LLM call。  
- 失败时 `error` 列存 stack + `error_class`。

#### 【轻量 Dashboard】

**架构痛点分析：**  
CLI 不够给经理看，Grafana 太重给个人用。

**推荐的生产级实现方案：**  
- `scripts/dashboard.py`（Streamlit 单页）：队列、失败列表、最近 wiki 变更、token 花费。  
- 或 Obsidian 仪表盘笔记自动更新（meta widget）。

#### 【健康检查端点（Health Check）】

**架构痛点分析：**  
`github_connector` FastAPI 无 `/health`；worker 无探针。K8s 化时必补。

**推荐的生产级实现方案：**  
- `GET /health`：DB ping + LM Studio `/models` + 可选 queue depth 阈值。  
- Worker：`resource_mgr.py health` exit code 非 0 给监控。

---

### P2

#### 【混沌与回归评测（Evals）】

**架构痛点分析：**  
49 个 pytest **不测 LLM 质量**，只测 plumbing。分类幻觉上线无告警。

**推荐的生产级实现方案：**  
- 黄金集：20 条固定 diff + 期望 `module_path`；每周 CI 跑 cloud 评测 F1。  
- Knowledge：snapshot 测试 markdown 结构，不测措辞。

---

## 6. 优先级总表（执行顺序建议）

| 优先级 | 机制 | 维度 |
|--------|------|------|
| **P0** | 原子 claim + 租约 | 队列 |
| **P0** | dedupe_key + 摄取背压 | 队列 |
| **P0** | 重试 / DLQ / 错误分类 | 队列 |
| **P0** | Compaction worker | 反熵增 |
| **P0** | 分类校验 + 低置信审核 | 反熵增 |
| **P0** | Hybrid FTS + 向量 | MCP |
| **P0** | Git-as-SoT / 单写入者 | 协同 |
| **P0** | Ingest ACL | 安全 |
| **P0** | SLI 指标 + heartbeat | 可观测 |
| **P0** | Token / 成本计量 | 可观测 |
| **P1** | 公平调度 / 分队列 | 队列 |
| **P1** | LLM 全局并发预算 | 队列 |
| **P1** | HITL review 队列 | 反熵增 |
| **P1** | Append 幂等 | 反熵增 |
| **P1** | MCP 检索结果结构化 | MCP |
| **P1** | 扩展 MCP 工具（changelog/graph） | MCP |
| **P1** | 结构化日志 + trace | 可观测 |
| **P1** | Streamlit dashboard | 可观测 |
| **P2** | Celery/Temporal | 队列 |
| **P2** | Synthesize 跨模块 | 反熵增 |
| **P2** | MCP HTTP + 鉴权 | MCP |
| **P2** | 多租户 | 协同 |
| **P2** | LLM Evals 黄金集 | 可观测 |

---

## 7. 与当前原型匹配的「最小生产化」路径（90 天现实主义）

若资源有限，**不要先上 Celery**。按序做：

1. **P0 队列：** `dedupe_key` + 原子 `UPDATE … RETURNING` + `retry_count` / `dead`（仍 SQLite）。  
2. **P0 反熵增：** `CONSOLIDATE` cron（每周扫超长 module）。  
3. **P0 MCP：** sqlite-vec hybrid `search_wiki`。  
4. **P0 协同：** wiki 仅 GHA bot 写入；本地 worker 只写 DB preview 或 fork 分支。  
5. **P0 运维：** `metrics` 表 + `resource_mgr.py health` + 成本日志。

完成这五步后，才值得招第二个 worker 进程或换 Postgres。

---

## 8. 参考：当前已实现能力（避免重复造轮子）

| 能力 | 位置 | 评审意见 |
|------|------|----------|
| FTS5 trigram | `db.py` `wiki_fts` | 保留，作 hybrid 一路 |
| `get_recent_changes` | `mcp_server.py` | **已有**；需加强 module 维度 |
| `get_pipeline_status_tool` | MCP | 太薄，升级为 metrics |
| Knowledge 相似度门控 | `knowledge_base_scanner.py` | 好；推广到 GitHub PR |
| `dev_up.sh` 单条 inline distill | 根目录 | 好；与 DLQ replay 互补 |
| `resource_mgr.py llm` | CLI | 好；加入告警联动 |
| Cloud 仅 CREATE_PAGE | `llm_router.py` | 好；加 budget 硬顶 |
| FastAPI webhook | `github_connector.py` | 好；加 `/health` + 背压 |

---

*文档版本：2026-05-29 · 取代原 chat 式 Knowledge Base Digest 计划稿 · 维护者：架构评审 backlog*
