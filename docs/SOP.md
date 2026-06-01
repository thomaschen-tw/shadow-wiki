# PulseWiki — Standard Operating Procedure

> **What it does:** Watches GitHub PRs, Slack channels, Linear tickets, and local code files. Distills them into a module-level Obsidian wiki via a local Qwen model (LM Studio / Ollama) for routine updates and a cloud model (Claude / Qwen Cloud / DeepSeek) for new-page synthesis. Exposes the wiki as a FastMCP server so Claude Code can search it without scanning the full codebase.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Installation](#2-installation)
3. [Configuration (.env)](#3-configuration)
4. [Data Source Setup](#4-data-source-setup)
5. [Starting the System](#5-starting-the-system)
6. [Claude Code MCP Integration](#6-claude-code-mcp-integration)
7. [Daily Operations](#7-daily-operations)
8. [Switching LLM Backends](#8-switching-llm-backends)
9. [MCP Tool Reference](#9-mcp-tool-reference)
10. [Architecture Reference](#10-architecture-reference)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12 | pinned via `.python-version`; `uv` downloads it automatically |
| uv | latest | `pip install uv` or `brew install uv` |
| LM Studio **or** Ollama | latest | local LLM backend |
| Qwen 3 model (e.g. 27B) | any quant | loaded in LM Studio or pulled in Ollama |
| Git | any | for the project itself |
| GitHub repo (optional) | — | for webhook ingestion |
| Slack workspace (optional) | — | Bot + App tokens needed |
| Linear workspace (optional) | — | API key needed |

**Minimum to run:** Python 3.12 + uv + LM Studio with Qwen loaded. Everything else is optional.

---

## 2. Installation

```bash
# Clone / enter the project
cd /path/to/pulse-wiki

# Create venv with Python 3.12 and install all deps (uv downloads Python if needed)
uv sync

# Copy config template
cp .env.example .env

# Initialise the database
uv run python scripts/resource_mgr.py init
```

Expected output from `init`:
```
Database initialized.
```

Verify with:
```bash
uv run python scripts/resource_mgr.py status
```
```
Pending : 0
Failed  : 0
Last run: never
Modules : 0
```

---

## 3. Configuration

All configuration lives in **`.env`** (never commit it — gitignored). `scripts/config.py` loads each variable automatically (`LMSTUDIO_MODEL` → `lmstudio_model`, etc.). Change models and API keys in `.env` only; restart the worker after edits. Verify with `uv run python scripts/resource_mgr.py llm`.

### 3.1 LLM Backend Selection

```env
# Which local backend to use for classify / summarize / append tasks
LOCAL_LLM_BACKEND=auto          # auto (default) | lmstudio | ollama
# auto = probe LM Studio (localhost:1234) first, fall back to Ollama

# Which cloud backend to use for create-page / synthesize tasks
CLOUD_LLM_BACKEND=claude        # claude (default) | qwen_cloud | deepseek
```

**Cost profile:** 99 % of operations go to the local model (free). Cloud is called only when a brand-new wiki module is created for the first time.

### 3.2 Local LLM

**LM Studio (default):**
```env
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LMSTUDIO_MODEL=qwen/qwen3.6-27b # exact id from GET http://localhost:1234/v1/models
```
Start the LM Studio server before launching the worker. The default port is 1234.

**Ollama (alternative):**
```env
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen3.6:27b
```
Pull the model first: `ollama pull qwen3.6:27b`

### 3.3 Cloud LLM

Fill in only the backend you intend to use.

```env
# Claude (Anthropic)
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-6

# Qwen Cloud (DashScope — OpenAI-compatible)
DASHSCOPE_API_KEY=sk-...
QWEN_CLOUD_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_CLOUD_MODEL=qwen-plus

# DeepSeek (OpenAI-compatible)
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

### 3.4 Data Sources

```env
# GitHub
GITHUB_TOKEN=ghp_...            # Personal Access Token with repo read scope
GITHUB_REPO=owner/repo          # e.g. myorg/backend
GITHUB_WEBHOOK_SECRET=...       # Set this when configuring the GitHub webhook

# Slack
SLACK_BOT_TOKEN=xoxb-...        # Bot User OAuth Token
SLACK_APP_TOKEN=xapp-...        # App-Level Token (for Socket Mode)
SLACK_CHANNELS=C12345,C67890    # Comma-separated channel IDs to monitor

# Linear
LINEAR_API_KEY=lin_...          # Personal API Key from Linear settings

# Local file scan
LOCAL_SCAN_PATHS=./src,./docs   # Comma-separated directories to watch
LOCAL_SCAN_EXTENSIONS=.py,.ts,.tsx,.md,.go

# Obsidian knowledge base (vault wiki/ subfolder — never uploaded to this repo)
KNOWLEDGE_BASE_PATH=/path/to/your/obsidian/vault/wiki
KNOWLEDGE_BASE_SIMILARITY_THRESHOLD=0.85   # skip LLM if >85% token overlap with last run
```

### 3.5 LLM Behaviour

```env
# Request timeout in seconds — set higher for large local models (default: 300)
LLM_TIMEOUT=300

# Disable Qwen3 thinking mode — keeps pipeline responses direct and fast
ENABLE_THINKING=false
```

`ENABLE_THINKING=false` passes `{"enable_thinking": false}` in the API `extra_body`. Set to `true` only if you want the model to reason step-by-step (slower, more tokens).

### 3.6 System Paths

```env
WIKI_DIR=./wiki         # Where Obsidian .md files are written
DB_PATH=./db/shadow.db  # SQLite database location
RAW_DIR=./raw           # Raw event JSON backups (for debugging)
```

---

## 4. Data Source Setup

### 4.1 GitHub Webhook

1. In your GitHub repo → **Settings → Webhooks → Add webhook**
2. Payload URL: `http://your-server:9000/webhook/github`
3. Content type: `application/json`
4. Secret: the value you set in `GITHUB_WEBHOOK_SECRET`
5. Events: **Pull requests**, **Pull request review comments**
6. Start the connector: `python scripts/ingest/github_connector.py`

> For local development, use [ngrok](https://ngrok.com) or [smee.io](https://smee.io) to expose port 9000.

### 4.2 Slack Bot

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From scratch**
2. **Socket Mode** → Enable → Generate App-Level Token (scope: `connections:write`) → save as `SLACK_APP_TOKEN`
3. **OAuth & Permissions** → Bot Token Scopes: `channels:history`, `channels:read`, `groups:history`
4. Install to workspace → copy Bot User OAuth Token → save as `SLACK_BOT_TOKEN`
5. **Event Subscriptions** → Enable → Subscribe to bot events: `message.channels`
6. Invite the bot to the channels you want to monitor: `/invite @pulse-wiki`
7. Set `SLACK_CHANNELS` to the channel IDs (visible in the URL when you open the channel in a browser)
8. Start the connector: `python scripts/ingest/slack_connector.py`

### 4.3 Linear

1. Linear → **Settings → API → Personal API keys → Create key**
2. Save as `LINEAR_API_KEY`
3. Start the connector: `python scripts/ingest/linear_connector.py`

The connector polls every 5 minutes (default). No webhook setup needed.

### 4.4 Local File Scanner

No external setup. Configure `LOCAL_SCAN_PATHS` and `LOCAL_SCAN_EXTENSIONS` in `.env`, then:

```bash
python scripts/ingest/local_scanner.py
```

The scanner runs a full pass at startup and then every 2 minutes (default). On first run it will queue all matching files as `file_change` events.

### 4.5 Knowledge Base (daily digest)

Distills your personal Obsidian vault's **wiki/** subfolder (`concepts/`, `comparisons/`, `entities/`, `summaries/`) into structured pages under `wiki/knowledge/…` in this repo. Raw clippings under `raw/` are not scanned — only curated wiki notes.

**One-time setup:**

1. Set `KNOWLEDGE_BASE_PATH` in `.env` to your vault's wiki folder, e.g.  
   `/Users/you/Documents/obsidian/knowledge_base/wiki`
2. Install a [self-hosted GitHub Actions runner](github-actions-setup.md) on your Mac (the vault stays local; only distilled output is committed).

**Manual run:**

```bash
# Preview what would be queued (no DB writes)
uv run python scripts/ingest/knowledge_base_scanner.py --dry-run

# Queue changed notes
uv run python scripts/ingest/knowledge_base_scanner.py --once

# Process events (worker must be running, or run inline)
uv run python scripts/distill/worker.py &
# …or process a batch once:
uv run python -c "
from scripts.db import init_db, get_pending_events
from scripts.distill.worker import process_event
init_db()
for e in get_pending_events(limit=200):
    process_event(e)
"

uv run python scripts/resource_mgr.py list   # expect wiki/knowledge/… paths
```

**Automated daily run:** Workflow `.github/workflows/daily-knowledge-digest.yml` runs at 09:00 CST on the self-hosted runner: scan → distill → `git commit` `wiki/` → push. Trigger manually from GitHub → Actions → **Daily Knowledge Digest** → Run workflow.

**Dedup:** Stage 1 skips files whose MD5 is unchanged. Stage 2 skips files whose token overlap with the last processed snapshot exceeds `KNOWLEDGE_BASE_SIMILARITY_THRESHOLD` (default 0.85). Re-queue everything once with `--force --once`.

**Worker routing:** Events with `source=knowledge_base` use knowledge-specific prompts (Overview / Key Insights / Sources) and incremental append — new insights only, no full page rewrite when the topic page already exists.

---

## 5. Starting the System

Each component runs as a separate process. Start them in order:

### Step 1 — Ensure local LLM is running

**LM Studio:** Open LM Studio → load your model (e.g. Qwen3.6-27B) → **Start Server**. Verify: `uv run python scripts/resource_mgr.py llm`

**Ollama:** `ollama serve` (usually starts automatically).

### Step 2 — Init DB (first time only)

```bash
python scripts/resource_mgr.py init
```

### Step 3 — Start the distillation worker

```bash
python scripts/distill/worker.py
```

This is the core process. It polls the event queue every 30 seconds, calls the LLM, and writes wiki files.

### Step 4 — Start the connectors (whichever you need)

```bash
# GitHub webhook server (port 9000)
python scripts/ingest/github_connector.py &

# Slack Socket Mode listener
python scripts/ingest/slack_connector.py &

# Linear polling (every 5 min)
python scripts/ingest/linear_connector.py &

# Local file scanner (every 2 min)
python scripts/ingest/local_scanner.py &
```

### Step 5 — Start the MCP server (for Claude Code)

```bash
python scripts/mcp_server.py
```

This runs in stdio mode. Claude Code manages its lifecycle — you don't need to keep it running manually.

### Minimal Setup (no cloud keys, demo only)

```bash
# 1. Start LM Studio server
# 2.
python scripts/resource_mgr.py init
python scripts/distill/worker.py &
# 3. Push a test diff
echo "+def hello(): pass" | python scripts/ingest_diff.py --diff - --pr 1 --title "Test"
# 4. Watch the worker log — wiki/general.md should appear within 30s
```

---

## 6. Claude Code MCP Integration

### 6.1 Register the MCP server

Add to `~/.claude/claude.json`:

```json
{
  "mcpServers": {
    "pulse-wiki": {
      "command": "python",
      "args": ["/absolute/path/to/pulse-wiki/scripts/mcp_server.py"]
    }
  }
}
```

Replace `/absolute/path/to/pulse-wiki` with the real path (e.g. `/Users/you/pulse-wiki`).

Restart Claude Code. Verify: `/mcp` → `pulse-wiki` should appear in the list.

### 6.2 Using the wiki in Claude Code

Once connected, Claude Code can call:

```
search_wiki("session token")        → find relevant modules
get_module("auth/session")          → read full module page
list_modules()                      → browse all modules
get_recent_changes("7d")            → what changed this week
get_pipeline_status_tool()          → check queue health
update_module("auth/session", "Known Issues", "- token refresh race condition")
```

Claude Code uses these automatically when context about the codebase is needed. You can also invoke them explicitly with natural language:

> "Check pulse-wiki for anything related to authentication before I change this file."

---

## 7. Daily Operations

### Check pipeline health

```bash
python scripts/resource_mgr.py status
```

```
Pending : 0
Failed  : 2
Last run: 2026-05-27 14:32:11
Modules : 47
```

If `Failed > 0`, check the events table:
```bash
python -c "
from scripts.db import get_connection, init_db
init_db()
with get_connection() as conn:
    rows = conn.execute(\"SELECT id, source, error FROM events WHERE status='failed'\").fetchall()
    for r in rows: print(r['id'], r['source'], r['error'])
"
```

### Browse indexed modules

```bash
python scripts/resource_mgr.py list
```

### Push a diff manually

```bash
# From a file
python scripts/ingest_diff.py --diff changes.patch --pr 142 --title "Add Redis caching"

# From stdin (e.g. git diff output)
git diff HEAD~1 | python scripts/ingest_diff.py --diff - --pr 143 --title "Refactor auth"
```

### Re-process failed events

```bash
python -c "
from scripts.db import get_connection, init_db
init_db()
with get_connection() as conn:
    conn.execute(\"UPDATE events SET status='pending', error=NULL WHERE status='failed'\")
print('Done — failed events reset to pending')
"
```

### View a wiki module

Open the `wiki/` directory in Obsidian (it's already a vault). Or:
```bash
cat wiki/auth/session.md
```

---

## 8. Switching LLM Backends

Only two `.env` variables need changing. The worker picks them up on the next restart.

| Scenario | Change |
|---|---|
| Auto-detect local backend (default) | `LOCAL_LLM_BACKEND=auto` |
| Force LM Studio | `LOCAL_LLM_BACKEND=lmstudio` |
| Switch local to Ollama | `LOCAL_LLM_BACKEND=ollama` |
| Use Qwen Cloud for new pages | `CLOUD_LLM_BACKEND=qwen_cloud` |
| Use DeepSeek for new pages | `CLOUD_LLM_BACKEND=deepseek` |
| Use a different local model | `LMSTUDIO_MODEL=your-model-name` |
| Increase timeout for slow models | `LLM_TIMEOUT=600` |
| Enable Qwen3 step-by-step reasoning | `ENABLE_THINKING=true` |

After editing `.env`, restart the worker:
```bash
# kill existing worker, then:
uv run python scripts/distill/worker.py
```

### LLM task routing (what gets called when)

| Task | Backend | Trigger |
|---|---|---|
| Identify which module a diff affects | Local | Every event |
| Extract structured change summary | Local | Every event |
| Generate changelog entry for existing module | Local | Module already exists |
| Understand MCP search query | Local | Every MCP search |
| Create a full new wiki module page | **Cloud** | Module seen for first time |
| Cross-PR synthesis (future) | **Cloud** | Manual trigger |

---

## 9. MCP Tool Reference

All tools are available in Claude Code once the MCP server is registered.

### `search_wiki(query, limit=5)`
Full-text search across all wiki content. Uses FTS5 trigram with an OR-token fallback for multi-word queries.

```
search_wiki("redis session token")
→ [{"module": "auth/session", "snippet": "...handles Redis <b>session</b> <b>token</b>..."}]
```

### `get_module(path)`
Returns the full markdown content plus YAML frontmatter metadata for a module.

```
get_module("auth/session")
→ "---\n{\"module\": \"auth/session\", ...}\n---\n\n## Overview\n..."
```

### `list_modules(tag=None)`
Lists all indexed modules with summaries. Optional tag filter.

```
list_modules()
→ [{"path": "auth/session", "summary": "...", "last_updated": "2026-05-27"}]

list_modules(tag="redis")
→ modules tagged with "redis" only
```

### `get_recent_changes(since="7d")`
Returns processed events from the last N days or hours.

```
get_recent_changes("24h")   → events from last 24 hours
get_recent_changes("30d")   → events from last 30 days
```

### `update_module(path, section, content)`
Appends content to a named section of an existing module. New entries are prepended (newest first).

```
update_module("auth/session", "Known Issues", "- token refresh race condition under high load")
→ {"status": "ok", "module": "auth/session", "section": "Known Issues"}
```

### `get_pipeline_status_tool()`
Returns queue health snapshot.

```
get_pipeline_status_tool()
→ {"pending": 0, "failed": 0, "last_processed": "2026-05-27T14:32:11"}
```

---

## 10. Architecture Reference

```
┌─────────────────────────────────────────────────────────┐
│                     DATA SOURCES                        │
│  GitHub │ Slack │ Linear │ Local │ Obsidian KB │
└──────────┬──────────┴────────┬─────────┴───┬────┴───┬───┘
           │                   │             │        │
           ▼                   ▼             ▼        ▼
┌──────────────────────────────────────────────────────────┐
│                  INGESTION CONNECTORS                    │
│  github_connector.py  slack_connector.py  local_scanner  │
│  (FastAPI :9000)        (Socket Mode)       (poll 120s)    │
└────────────────────────────┬─────────────────────────────┘
                             │  push_event(source, type, json)
                             ▼
┌──────────────────────────────────────────────────────────┐
│              SQLite EVENT QUEUE  db/shadow.db            │
│  events (status: pending → processing → done/failed)     │
│  modules (path, summary, last_updated)                   │
│  wiki_fts (FTS5 trigram full-text index)                 │
└────────────────────────────┬─────────────────────────────┘
                             │  get_pending_events()
                             ▼
┌──────────────────────────────────────────────────────────┐
│              DISTILLATION WORKER  worker.py              │
│                                                          │
│  ┌─────────────────────────┐  ┌────────────────────────┐ │
│  │  LOCAL LLM (high-freq)  │  │  CLOUD LLM (low-freq)  │ │
│  │  LM Studio / Ollama     │  │  Claude / Qwen / DS    │ │
│  │  classify, summarize,   │  │  create_page,          │ │
│  │  append                 │  │  synthesize            │ │
│  └─────────────────────────┘  └────────────────────────┘ │
└────────────────────────────┬─────────────────────────────┘
                             │  write .md files
                             ▼
┌──────────────────────────────────────────────────────────┐
│              OBSIDIAN WIKI  wiki/{module}.md             │
│  YAML frontmatter: module, last_updated, recent_prs,     │
│  owners, known_issues, slack_threads, tags               │
│  Sections: Overview │ Recent Changes │ Known Issues      │
│            Related Modules                               │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│              MCP SERVER  mcp_server.py (stdio)           │
│  search_wiki │ get_module │ list_modules                 │
│  get_recent_changes │ update_module │ get_pipeline_status│
└────────────────────────────┬─────────────────────────────┘
                             │  MCP protocol
                             ▼
                    ┌─────────────────┐
                    │   Claude Code   │
                    │  (developer     │
                    │   terminal)     │
                    └─────────────────┘
```

### Project Structure

```
pulse-wiki/
├── .env                        ← sole config source (never commit)
├── .env.example                ← config template (commit this)
├── .python-version             ← pins Python 3.12 for uv / pyenv
├── pyproject.toml              ← uv project file + pytest config
├── requirements.txt            ← legacy pip fallback
├── CLAUDE.md                   ← developer quick-start
├── README.md                   ← project overview and quick start
├── docs/SOP.md                 ← this file
├── wiki/                       ← generated Obsidian pages (wiki vault root)
├── db/shadow.db                ← SQLite (events + module index + FTS5)
├── raw/                        ← raw event JSON backups (debug)
├── scripts/
│   ├── config.py               ← pydantic-settings Settings class
│   ├── db.py                   ← SQLite CRUD + FTS helpers
│   ├── distill/
│   │   ├── llm_router.py       ← call_llm() dispatcher + client cache
│   │   ├── prompts.py          ← all system prompts + builders
│   │   └── worker.py           ← event consumption loop (daemon)
│   ├── ingest/
│   │   ├── github_connector.py ← FastAPI webhook (port 9000)
│   │   ├── slack_connector.py  ← Slack Socket Mode
│   │   ├── linear_connector.py ← Linear GraphQL poll
│   │   ├── local_scanner.py    ← MD5 hash change detection
│   │   └── knowledge_base_scanner.py ← Obsidian vault wiki/ scanner
│   ├── wiki/
│   │   └── manager.py          ← read/write Obsidian .md files
│   ├── mcp_server.py           ← FastMCP stdio server
│   ├── ingest_diff.py          ← CLI: push diff manually
│   └── resource_mgr.py         ← CLI: init / status / list / cloud / db / dev / compile / llm
├── demo.sh                     ← MVP one-shot demo
├── dev_up.sh                   ← debug bring-up (single-event; see README)
└── tests/                      ← 49 tests (uv run pytest)
    ├── conftest.py             ← tmp_db fixture (isolates DB per test)
    ├── test_config.py
    ├── test_db.py
    ├── test_llm_router.py
    ├── test_wiki_manager.py
    ├── test_worker.py
    ├── test_github_connector.py
    ├── test_mcp_server.py
    └── test_integration.py     ← end-to-end: event → LLM → wiki → MCP search
```

---

## 11. Troubleshooting

### Worker exits immediately / no log output

Check that `db/shadow.db` exists:
```bash
python scripts/resource_mgr.py init
```

### LLM call fails: `Connection refused`

- **LM Studio:** Open LM Studio and click **Start Server**. Default port is 1234.
- **Ollama:** Run `ollama serve` in a separate terminal. Default port is 11434.
- Verify: `curl http://localhost:1234/v1/models`

### LLM call fails: `Model not found`

The `LMSTUDIO_MODEL` / `OLLAMA_MODEL` value must exactly match the model id from the server. Check:
```bash
uv run python scripts/resource_mgr.py llm
# or: curl http://localhost:1234/v1/models | python -m json.tool | grep '"id"'
```

`dev` / `compile` use **Ollama keep_alive** when `LOCAL_LLM_BACKEND=ollama`, and **LM Studio chat warm-up** when `lmstudio` or `auto` resolves to LM Studio. They no longer send `LMSTUDIO_MODEL` to the Ollama API.

### FTS search returns no results

The FTS index is updated every time a module is written. If you manually edited a `.md` file, rebuild:
```bash
python -c "
from scripts.db import init_db, update_fts
from scripts.wiki.manager import read_module
from scripts.db import get_connection
init_db()
with get_connection() as conn:
    paths = [r['path'] for r in conn.execute('SELECT path FROM modules').fetchall()]
for path in paths:
    post = read_module(path)
    if post:
        update_fts(path, post.content)
        print(f'Reindexed {path}')
"
```

### GitHub webhook returns 403

Either the `GITHUB_WEBHOOK_SECRET` in `.env` does not match what you set on GitHub, or `GITHUB_WEBHOOK_SECRET` is empty (which disables signature checking). Set them to the same value on both sides.

### Slack connector exits silently

Socket Mode requires both `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN`. Confirm both are set and that Socket Mode is enabled in your Slack app settings.

### `ModuleNotFoundError: No module named 'scripts'`

Run the scripts from the project root, not from inside `scripts/`:
```bash
cd /path/to/pulse-wiki
python scripts/distill/worker.py   # correct
```

Or use the `sys.path` insert in `ingest_diff.py` / `resource_mgr.py` — those can be run directly.

### Events stuck in `processing` status

The worker crashed mid-event. Reset them:
```bash
python -c "
from scripts.db import get_connection, init_db
init_db()
with get_connection() as conn:
    n = conn.execute(\"UPDATE events SET status='pending' WHERE status='processing'\").rowcount
print(f'Reset {n} stuck events')
"
```

### Tests fail after updating code

Run the full suite to identify regressions:
```bash
uv run pytest -v
```

The `conftest.py` fixture creates an isolated temporary DB per test, so tests are independent of any real `db/shadow.db`.

---

*Last updated: 2026-05-28 | PulseWiki v1.1*
