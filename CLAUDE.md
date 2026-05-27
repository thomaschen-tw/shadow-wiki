# Shadow Wiki

A self-updating technical wiki that ingests GitHub PRs, Slack messages, Linear tickets, and local files — distilling them via a hybrid local/cloud LLM pipeline into an Obsidian vault exposed as an MCP server.

## Quick Start

```bash
cp .env.example .env        # fill in your tokens
python scripts/resource_mgr.py init
python scripts/distill/worker.py &           # distillation worker (daemon)
python scripts/ingest/github_connector.py &  # GitHub webhook on :9000
python scripts/mcp_server.py                 # MCP server (stdio, for Claude Code)
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
LOCAL_LLM_BACKEND=ollama       # lmstudio (default) | ollama
CLOUD_LLM_BACKEND=deepseek     # claude (default) | qwen_cloud | deepseek
```

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
pytest -v
```

## Manual End-to-End Test

```bash
# 1. Init DB
python scripts/resource_mgr.py init

# 2. Push a test diff
echo "+def login(): pass" | python scripts/ingest_diff.py --diff - --pr 1 --title "Add login"

# 3. Run worker once (calls your configured LLM)
python -c "
from scripts.db import init_db, get_pending_events
from scripts.distill.worker import process_event
init_db()
for e in get_pending_events(): process_event(e)
"

# 4. Check results
python scripts/resource_mgr.py list
```
