# PulseWiki

> Architecture: [docs/architecture.md](docs/architecture.md) · Full SOP: [docs/SOP.md](docs/SOP.md) · GitHub setup: [docs/github-setup.md](docs/github-setup.md) · Roadmap: [docs/architecture-roadmap.md](docs/architecture-roadmap.md)

A self-updating technical wiki that ingests GitHub PRs, Slack messages, and local files — distilling them via a hybrid local/cloud LLM pipeline into an Obsidian vault exposed as an MCP server.

## Essential Commands

```bash
uv sync                                 # install deps (Python 3.12 required)
uv run pytest -v                        # run all 66 tests
uv run python test_env.py              # verify env/connectivity before starting
uv run python scripts/resource_mgr.py init   # initialise SQLite (db/shadow.db)
uv run python scripts/distill/worker.py &    # distillation daemon (polls every 30s)
bash demo.sh                            # full demo (init + ingest + worker + MCP)
bash dev_up.sh                          # single-event inline debug (won't drain queue)
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full diagram. Data flow in brief:

```
Connectors (ingest/) → SQLite event queue (db/shadow.db)
  → worker.py [classify → summarize → create/append]
  → wiki/{module}.md (Obsidian markdown + YAML frontmatter)
  → mcp_server.py (FastMCP stdio) → MCP clients (VS Code / Claude Code / Cursor)
```

Event status lifecycle: `pending` → `processing` → `done` | `failed`

## Key Files

| File | Purpose |
|------|---------|
| `scripts/config.py` | Pydantic-settings: all config from `.env` |
| `scripts/db.py` | SQLite: `push_event`, `get_pending_events`, FTS5 search, `upsert_module` |
| `scripts/distill/llm_router.py` | Routes `TaskType` enum to local (LM Studio/Ollama) or cloud LLM |
| `scripts/distill/worker.py` | Event loop: `_handle_code_event` vs `_handle_knowledge_event` dispatch |
| `scripts/distill/prompts.py` | All LLM prompt templates |
| `scripts/wiki/manager.py` | Read/write wiki `.md` files via `python-frontmatter` |
| `scripts/mcp_server.py` | 7 FastMCP tools exposed over stdio |
| `scripts/ingest_diff.py` | CLI: push diff manually (AST syntax validation gate) |
| `scripts/resource_mgr.py` | CLI: init / status / list / cloud / db / dev / compile / llm |
| `test_env.py` | Connectivity + credential validation |

## Conventions & Pitfalls

### Config
- **Never edit Python defaults** to change models/backends — edit `.env` only. `scripts/config.py` maps `LMSTUDIO_MODEL` → `lmstudio_model` (case-insensitive pydantic-settings).
- Settings are a cached singleton. Call `reload_settings()` (or `cfg._settings = None`) after changing `.env` at runtime.
- `LOCAL_LLM_BACKEND=auto` probes LM Studio (`localhost:1234`) first, then Ollama (`localhost:11434`). LRU-cached after first probe — restart worker to re-probe.

### Database
- All DB access goes through functions in `scripts/db.py` — never write raw SQL in other files.
- `upsert_module()` preserves the old summary when new summary is `None`.
- FTS5 search does phrase match first; falls back to OR across tokens if no results.

### Worker / LLM
- `CLASSIFY`, `SUMMARIZE`, `APPEND`, `QUERY` → always local LLM. `CREATE_PAGE`, `SYNTHESIZE`, `RUNBOOK` → cloud when `USE_CLOUD_LLM=true`.
- `source=knowledge_base` events use different prompts and write to `wiki/knowledge/`. All other sources write to `wiki/{module}/`.
- LLM outputs are often JSON strings — use `_parse_json_list()` and `_safe_json()` helpers in `worker.py` rather than bare `json.loads()`.
- Module paths are slugified: lowercase, non-word chars removed, max 60 chars (see `_slugify()`).
- Slack `thread_reply` events and GitHub `pr_review`/`pr_comment` events are handled by dedicated functions (`_handle_slack_thread_reply`, `_handle_review_event`).
- Every 5 appends to `## Recent Changes` triggers a `SYNTHESIZE` call to refresh `## Overview`.
- When `## Known Issues` reaches 2+ entries and `## Runbooks` is absent, a `RUNBOOK` call generates the section automatically.

### Wiki / Frontmatter
- Wiki files live at `wiki/{module_path}.md` where `module_path` uses `snake_case/with_slashes` (e.g. `auth/session`, `knowledge/ai/rag-vs-kag`).
- Frontmatter keys: `module`, `last_updated`, `recent_prs`, `recent_events`, `owners`, `known_issues`, `slack_threads`, `tags`.
- Standard sections: `## Overview`, `## Recent Changes`, `## Known Issues`, `## Related Modules`, `## Runbooks`; KB pages use `## Key Insights`.
- `append_to_section()` top-prepends a `### {YYYY-MM-DD} ({pr_number})` subsection.

### Tests
- All tests use the `tmp_db` fixture (in `tests/conftest.py`) which monkeypatches `DB_PATH` and `WIKI_DIR` and resets `cfg._settings = None` before and after each test.
- Mock `call_llm` with `side_effect` returning a list of JSON strings in call order.
- Integration test in `tests/test_integration.py` covers the full push → worker → wiki → MCP search pipeline.
- MCP tool tests import functions directly from `scripts.mcp_server` — they bypass the `FunctionTool` registration loop, so module-level import must succeed cleanly.

## LLM Backend Config

```env
LOCAL_LLM_BACKEND=auto         # auto | lmstudio | ollama
CLOUD_LLM_BACKEND=qwen_cloud   # claude | qwen_cloud | deepseek
USE_CLOUD_LLM=false            # true = cloud for CREATE_PAGE/SYNTHESIZE
LMSTUDIO_MODEL=qwen/qwen3.6-27b  # must match id from LM Studio /v1/models
```

Verify: `uv run python scripts/resource_mgr.py llm` · Reload worker after changes.

## Toggle Commands

```bash
uv run python scripts/resource_mgr.py cloud on|off  # cloud LLM for new pages
uv run python scripts/resource_mgr.py db on|off     # local SQLite vs DATABASE_URL
uv run python scripts/resource_mgr.py dev           # free RAM + pause Docker
uv run python scripts/resource_mgr.py compile       # load model + resume Docker
```

## MCP Server (7 tools)

| Tool | Purpose |
|------|---------|
| `search_wiki(query, limit=5)` | FTS5 search → module path + snippet |
| `get_module(path)` | Full frontmatter + content for a module |
| `list_modules(tag=None)` | All modules with summary; filter by tag |
| `get_recent_changes(since="7d")` | Events processed since cutoff (e.g. "24h", "7d") |
| `update_module(path, section, content)` | Append to section (module must exist) |
| `get_pipeline_status_tool()` | Pending count, failed count, last_processed |
| `get_runbooks(path)` | Returns `## Runbooks` section for a module |

MCP client config example: `.cursor/mcp.json` (committed). Update the absolute path in `args` if you clone elsewhere. In Cursor, reload via **Settings → MCP** → enable `pulse-wiki`.

## Knowledge Base (Obsidian daily digest)

Set `KNOWLEDGE_BASE_PATH` in `.env` to your vault's `wiki/` folder. Scanner walks that path only (not `raw/`).

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

Docs index: [docs/README.md](docs/README.md) · Demo script: [docs/DEMO.md](docs/DEMO.md)
