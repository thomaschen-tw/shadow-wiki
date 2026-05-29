# Shadow Wiki — Demo & Hackathon Recording Guide

**Pitch:** Context-Aware Documentation Agents — ingest PR / Slack / Linear / diffs → living wiki → Claude Code via MCP.

## Pre-flight (run before recording)

```bash
uv sync
uv run python test_env.py
uv run python scripts/resource_mgr.py llm    # LM Studio model id must show ✓
uv run python scripts/resource_mgr.py init
uv run python scripts/resource_mgr.py status   # avoid huge pending unless showing scale
```

**LLM:** Prefer local `qwen/qwen3.6-27b` in LM Studio. If OOM, use `bash dev_up.sh --cloud` (requires paid DashScope quota).

## Recommended live demo path (~4 min)

| Time | Action |
|------|--------|
| 0:00 | Problem: docs rot; knowledge in PR/Slack |
| 0:30 | Show README architecture diagram |
| 1:00 | `bash dev_up.sh` — queues diff → inline distill → `wiki/auth/session.md` updates |
| 2:00 | Open `wiki/auth/session.md` in editor (Recent Changes section) |
| 2:30 | Claude Code: `search_wiki("redis session")` → `get_module("auth/session")` |
| 3:30 | Hybrid local/cloud + Responsible AI (local default, cloud for new pages) |
| 4:00 | Repo URL + `uv run pytest -q` (49 tests) |

## Fallback if LLM fails on camera

Use pre-generated pages under `wiki/` and `wiki/knowledge/` already in the repo. MCP search still works without a live distill.

```bash
uv run python -c "from scripts.mcp_server import search_wiki; print(search_wiki('session'))"
```

## Do not use for recording

- `bash demo.sh` with 10+ pending knowledge events (drains queue for hours)
- `bash dev_up.sh --daemon` unless demonstrating backlog processing

See also: [knowledge-base-verification.md](knowledge-base-verification.md)
