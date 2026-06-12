# PulseWiki Operational Runbook

This document covers operational procedures for running, monitoring, and troubleshooting PulseWiki.

---

## 1. Starting the Ingest Stack

**One-click startup (recommended):**

```bash
bash scripts/start_ingest_stack.sh
```

This starts:
- GitHub webhook receiver (port 9000)
- Distillation worker
- Slack Socket Mode listener (if tokens configured)
- Cloudflare quick tunnel for public webhook

**With custom options:**

```bash
bash scripts/start_ingest_stack.sh --port 9001 --no-slack --no-tunnel
```

Options:
- `--port N` — change webhook port (default 9000)
- `--slack` — force start Slack
- `--no-slack` — disable Slack
- `--no-tunnel` — skip Cloudflare tunnel (use local webhook only)
- `--no-sync` — skip dependency sync

**Verify startup:**

```bash
curl http://127.0.0.1:9000/docs
# Shows FastAPI Swagger docs if healthy
```

---

## 2. Monitoring Live Activity

When the ingest stack is running, the launcher shows live activity with color-coded tags:

| Tag | Color | Meaning |
|---|---|---|
| `[INBOUND]` | Cyan | Event received from GitHub/Slack |
| `[WORKER]` | Yellow | Worker processing batch |
| `[WRITE]` | Green | Existing module updated |
| `[CREATE]` | Green | New module/page created |
| `[SYNTH]` | Magenta | Overview synthesized |
| `[RUNBOOK]` | Magenta | Runbook auto-generated |
| `[ERROR]` | Red | Processing failure |

---

## 3. Database Health

Check queue depth and last processed time:

```bash
uv run python scripts/resource_mgr.py status
```

Output shows:
- `pending` — events waiting to process
- `failed` — events that errored
- `last_processed` — timestamp of last successful event

Example:
```
Pipeline Status:
  Pending: 0
  Failed:  0
  Last processed: 2026-06-04 15:23:45
```

---

## 4. List and Search Indexed Modules

```bash
# List all indexed wiki modules
uv run python scripts/resource_mgr.py list

# Search by keyword
bash scripts/verify_mcp_ingest.sh --query "session retry" --since 7d --verbose
```

View a specific module:

```bash
# See full markdown + frontmatter
cat wiki_content/legacy/auth/session.md
```

Check active write target and ETL staging counters:

```bash
uv run python scripts/resource_mgr.py paths
uv run python scripts/resource_mgr.py etl-status
```

---

## 5. Manual Event Ingestion

Push a code diff manually (useful for testing without GitHub webhook):

```bash
echo "+def login(): pass" | uv run python scripts/ingest_diff.py \
  --diff - --pr 123 --title "Add login"
```

---

## 6. Reset Stuck Events

If events get stuck in `processing` state (e.g., worker crashed):

```bash
uv run python -c "
from scripts.db import get_connection
with get_connection() as conn:
    conn.execute(\"UPDATE events SET status='pending' WHERE status='processing'\")
print('Reset done')
"
```

Then restart worker:

```bash
uv run python scripts/distill/worker.py
```

For staged ETL replay testing in daytime:

```bash
# Dry-run replay over a window
uv run python scripts/resource_mgr.py etl-replay --since "2026-06-01 00:00:00" --until "2026-06-01 23:59:59" --limit 200

# Apply replay over a window
uv run python scripts/resource_mgr.py etl-replay --since "2026-06-01 00:00:00" --until "2026-06-01 23:59:59" --apply --limit 200

# Route and distill from persisted staging rows
uv run python scripts/resource_mgr.py etl-run route --from-staging --apply --limit 100
uv run python scripts/resource_mgr.py etl-run distill --from-staging --apply --limit 100
```

---

## 7. Changing LLM Models

Update `.env`:

```bash
# Switch to local Ollama
sed -i '' 's/^LOCAL_LLM_BACKEND=.*/LOCAL_LLM_BACKEND=ollama/' .env

# Or switch model name
sed -i '' 's/^LMSTUDIO_MODEL=.*/LMSTUDIO_MODEL=qwen3.6:latest/' .env
```

Verify which backend is active:

```bash
uv run python scripts/resource_mgr.py llm
```

Restart worker to pick up changes:

```bash
pkill -f "uv run python scripts/distill/worker.py"
uv run python scripts/distill/worker.py &
```

---

## 8. Webhook Security

**Development (local only):**

No secret required. Use `--no-tunnel` flag.

**Production (public URL):**

Set `GITHUB_WEBHOOK_SECRET` in `.env`:

```bash
GITHUB_WEBHOOK_SECRET=whsec_your_secret_here
```

To enforce secret validation:

```bash
export GITHUB_WEBHOOK_REQUIRE_SECRET=true
bash scripts/start_ingest_stack.sh
```

---

## 9. Troubleshooting

### "GitHub connector did not become ready"

Check FastAPI startup:

```bash
# Look for errors in connector startup
tail -f .runtime/github_connector_*.log
```

Typical causes:
- Port 9000 already in use → use `--port 9001`
- Python environment issue → run `uv sync`

### "No events appear after webhook"

Verify:
1. Webhook URL in GitHub settings points to current tunnel domain (it rotates)
2. Webhook secret matches (if configured)
3. Events subscribed: `pull_request`, `pull_request_review`, `issues`, `issue_comment`, `discussion`, `discussion_comment`
4. Worker is running: `ps aux | grep "uv run python scripts/distill/worker.py"`

Check worker logs:

```bash
tail -f .runtime/worker_*.log | grep "Processing\|ERROR"
```

### Worker timeout on LLM

Increase timeout in `.env`:

```bash
LLM_TIMEOUT=600  # 10 minutes
```

Or use cloud LLM for cloud-backed tasks:

```bash
USE_CLOUD_LLM=true
```

### Too many pending events

Worker may be slow. Check if it's running and check logs for errors:

```bash
uv run python scripts/resource_mgr.py status
tail -f .runtime/worker_*.log
```

If completely stuck, reset to `pending`:

```bash
uv run python -c "
from scripts.db import get_connection
with get_connection() as conn:
    conn.execute(\"UPDATE events SET status='processing' WHERE status='failed'\")
print('Moved failed back to pending')
"
```

---

## 10. MCP Client Integration

Once the MCP server is running (started by ingest stack or manually):

```bash
uv run python scripts/mcp_server.py
```

Use any MCP-compatible client (VS Code, Claude Code, Cursor):

```
search_wiki("redis session")          # Find modules by keyword
get_module("auth/session")            # Read full module
get_runbooks("auth/session")          # Operational procedures for module
get_recent_changes("7d")              # What changed in last 7 days
get_pipeline_status_tool()            # Queue health
list_modules()                        # All indexed modules
```

---

## 11. Daily Knowledge Base Digest

If configured, knowledge base scanner runs daily via GitHub Actions on a self-hosted runner.

Manual one-time scan:

```bash
uv run python scripts/ingest/knowledge_base_scanner.py --once
```

Check which files would be scanned:

```bash
uv run python scripts/ingest/knowledge_base_scanner.py --dry-run
```

See [docs/github-actions-setup.md](github-actions-setup.md) for automation setup.

---

## 12. Deployment Checklist

- [ ] `GITHUB_TOKEN` and `GITHUB_REPO` set in `.env`
- [ ] `GITHUB_WEBHOOK_SECRET` configured (production only)
- [ ] LM Studio or Ollama running with correct model loaded
- [ ] Database initialized: `uv run python scripts/resource_mgr.py init`
- [ ] Tests passing: `uv run pytest -q`
- [ ] One-click stack starts cleanly: `bash scripts/start_ingest_stack.sh --help`
- [ ] Test event processed: push diff or send Slack message
- [ ] MCP server responds to queries
- [ ] Wiki pages created/updated in `wiki/` directory

---

**For more details, see:**
- [docs/SOP.md](SOP.md) — full setup and operations
- [docs/architecture.md](architecture.md) — system design
- [docs/github-slack-wiki-verification.md](github-slack-wiki-verification.md) — E2E verification
