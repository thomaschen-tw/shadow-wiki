# PulseWiki

> Full SOP: **[docs/SOP.md](docs/SOP.md)** · Architecture: **[docs/architecture.md](docs/architecture.md)** · GitHub setup: **[docs/github-setup.md](docs/github-setup.md)**

A self-updating technical wiki that ingests GitHub PRs, Slack messages, Linear tickets, and local files — distilling them via a hybrid local/cloud LLM pipeline into an Obsidian vault exposed as an MCP server.

## Quick Start

```bash
uv sync                                              # Python 3.12 venv + all deps
cp .env.example .env                                 # fill in your tokens
uv run python test_env.py                            # verify connectivity before starting
uv run python scripts/resource_mgr.py init          # initialise SQLite database
uv run python scripts/distill/worker.py &           # distillation worker (daemon)
uv run python scripts/ingest/github_connector.py &  # GitHub webhook on :9000 (optional)
uv run python scripts/mcp_server.py                 # MCP server (stdio, for Claude Code)
```

Or just: `bash demo.sh`

Debug / study (single-event inline, won't drain the queue): `bash dev_up.sh` · `bash dev_up.sh --help`

## Architecture

```
[GitHub / Slack / Linear / Local Files / Obsidian KB]
           ↓ connectors (ingest/)
    SQLite event queue (db/shadow.db)
           ↓ worker.py  [poll 30s]
    Local LLM (LM Studio / Ollama) — classify, summarize, append
    Cloud LLM (Qwen Cloud / Claude / DeepSeek) — create new pages [USE_CLOUD_LLM=true]
           ↓
    Obsidian wiki files (wiki/{module}.md)
           ↓ mcp_server.py (FastMCP stdio)
    Claude Code → search_wiki / get_module / list_modules / …
```

## Key Files

| File | Purpose |
|------|---------|
| `scripts/config.py` | All settings loaded from `.env` (pydantic-settings) |
| `scripts/db.py` | SQLite: event queue, module index, FTS5 trigram search |
| `scripts/distill/llm_router.py` | Routes tasks to local vs cloud LLM |
| `scripts/distill/worker.py` | Event consumption loop — run as daemon |
| `scripts/wiki/manager.py` | Read/write Obsidian markdown with YAML frontmatter |
| `scripts/mcp_server.py` | FastMCP stdio server — 6 tools |
| `scripts/ingest/knowledge_base_scanner.py` | Scan Obsidian vault `wiki/` → `source=knowledge_base` events |
| `scripts/ingest_diff.py` | CLI: push a diff manually (with AST validation) |
| `scripts/resource_mgr.py` | CLI: init / status / list / cloud / db / dev / compile / llm |
| `test_env.py` | Environment checker — connectivity + credential validation |

## Toggle Commands

```bash
uv run python scripts/resource_mgr.py cloud on|off  # cloud LLM for new pages
uv run python scripts/resource_mgr.py db on|off     # local SQLite vs DATABASE_URL
uv run python scripts/resource_mgr.py dev           # free RAM + pause Docker
uv run python scripts/resource_mgr.py compile       # load model + resume Docker
```

## Switching LLM Backends

Edit **`.env` only** — `scripts/config.py` reads env vars automatically (`LMSTUDIO_MODEL` → `lmstudio_model`). Do not edit Python defaults when changing models.

```env
LOCAL_LLM_BACKEND=auto         # auto (default) | lmstudio | ollama
CLOUD_LLM_BACKEND=qwen_cloud   # claude | qwen_cloud | deepseek
USE_CLOUD_LLM=false            # false = all local; true = cloud for new pages
LMSTUDIO_MODEL=qwen/qwen3.6-27b  # must match id from LM Studio /v1/models
```

Verify: `uv run python scripts/resource_mgr.py llm` · reload worker after changes.

`auto` probes LM Studio (`localhost:1234`) first, then Ollama (`localhost:11434`).

## Claude Code MCP Config

Add to `~/.claude/claude.json`:

```json
{
  "mcpServers": {
    "pulse-wiki": {
      "command": "uv",
      "args": ["run", "python", "/absolute/path/to/pulse-wiki/scripts/mcp_server.py"]
    }
  }
}
```

## Running Tests

```bash
uv run pytest -v    # 49 tests
```

## Knowledge Base (Obsidian daily digest)

Set `KNOWLEDGE_BASE_PATH` in `.env` to your vault's `wiki/` folder. Scanner only walks that path (not `raw/`).

```bash
uv run python scripts/ingest/knowledge_base_scanner.py --dry-run   # preview
uv run python scripts/ingest/knowledge_base_scanner.py --once        # queue events
# worker processes → wiki/knowledge/…
```

Daily automation: `.github/workflows/daily-knowledge-digest.yml` on a self-hosted Mac runner — see `docs/github-actions-setup.md`.

Demo video script: `docs/DEMO.md` · Doc index: `docs/README.md`

## Manual End-to-End Test

```bash
uv run python scripts/resource_mgr.py init
echo "+def login(): pass" | uv run python scripts/ingest_diff.py --diff - --pr 1 --title "Add login"
# wait 30s for worker, then:
uv run python scripts/resource_mgr.py list
```
