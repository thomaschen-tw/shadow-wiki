# Shadow Wiki

> Full SOP (setup, connectors, MCP integration, troubleshooting): **[docs/SOP.md](docs/SOP.md)**

A self-updating technical wiki that ingests GitHub PRs, Slack messages, Linear tickets, and local files — distilling them via a hybrid local/cloud LLM pipeline into an Obsidian vault exposed as an MCP server.

## Quick Start

```bash
uv sync                                      # creates .venv with Python 3.12
cp .env.example .env        # fill in your tokens
uv run python scripts/resource_mgr.py init
uv run python scripts/distill/worker.py &           # distillation worker (daemon)
uv run python scripts/ingest/github_connector.py &  # GitHub webhook on :9000
uv run python scripts/mcp_server.py                 # MCP server (stdio, for Claude Code)
```

## Architecture

```
[GitHub / Slack / Linear / Local Files]
           ↓ connectors
    SQLite event queue (db/shadow.db)
           ↓ worker (scripts/distill/worker.py)
    Local Qwen via LM Studio (default) or Ollama — classify, summarize, append
    Cloud LLM (Claude / Qwen Cloud / DeepSeek) — create new wiki pages
           ↓
    Obsidian wiki files (wiki/{module}.md)
           ↓ MCP server (scripts/mcp_server.py)
    Claude Code reads via search_wiki / get_module / etc.
```

## Key Files

| File | Purpose |
|------|---------|
| `scripts/config.py` | All settings loaded from `.env` |
| `scripts/db.py` | SQLite helpers — event queue, module index, FTS5 search |
| `scripts/distill/llm_router.py` | Routes tasks to local (Qwen) or cloud LLM |
| `scripts/distill/worker.py` | Event consumption loop — run as daemon |
| `scripts/wiki/manager.py` | Read/write Obsidian markdown with YAML frontmatter |
| `scripts/mcp_server.py` | FastMCP stdio server — 6 tools |
| `scripts/ingest_diff.py` | CLI: push a diff manually |
| `scripts/resource_mgr.py` | CLI: init DB, show status, list modules |

## Switching LLM Backends

Edit `.env` only — zero code changes:

```env
LOCAL_LLM_BACKEND=auto         # auto (default) | lmstudio | ollama
CLOUD_LLM_BACKEND=deepseek     # claude (default) | qwen_cloud | deepseek
```

`auto` probes LM Studio (`localhost:1234`) first, then Ollama (`localhost:11434`).

## Claude Code MCP Config

Add to `~/.claude/claude.json`:

```json
{
  "mcpServers": {
    "shadow-wiki": {
      "command": "python",
      "args": ["/absolute/path/to/shadow-wiki/scripts/mcp_server.py"]
    }
  }
}
```

Then in Claude Code: `search_wiki("your query")` or `get_module("auth/session")`.

## Running Tests

```bash
uv run pytest -v
```

## Manual End-to-End Test

```bash
# 1. Init DB
uv run python scripts/resource_mgr.py init

# 2. Push a test diff
echo "+def login(): pass" | uv run python scripts/ingest_diff.py --diff - --pr 1 --title "Add login"

# 3. Run worker once (calls your configured LLM)
uv run python -c "
from scripts.db import init_db, get_pending_events
from scripts.distill.worker import process_event
init_db()
for e in get_pending_events(): process_event(e)
"

# 4. Check results
uv run python scripts/resource_mgr.py list
```
