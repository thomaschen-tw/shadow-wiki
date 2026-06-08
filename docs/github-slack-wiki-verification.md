# GitHub + Slack -> Wiki Verification

This guide validates PulseWiki end-to-end ingestion and traceability.

One-click startup (recommended):

```bash
bash scripts/start_ingest_stack.sh
```

This command starts `github_connector` + `worker` (+ `slack_connector` when tokens exist), creates a Cloudflare quick tunnel, and prints a ready-to-use GitHub webhook URL.

## 1. Verification Modes

Default mode (real data only):

```bash
bash scripts/verify_mcp_ingest.sh --module auth/session --query issue --since 7d --verbose
```

Test mode (synthetic data):

```bash
bash scripts/verify_mcp_ingest.sh --test
```

What the script checks:

1. `db/shadow.db` queue + module index are readable.
2. Real/synthetic GitHub events are distinguished in output.
3. Wiki search/index and module frontmatter can be queried through MCP functions.

## 2. Prerequisites

Run these in separate terminals and keep them alive:

```bash
uv run python scripts/ingest/github_connector.py
uv run python scripts/distill/worker.py
cloudflared tunnel --url http://localhost:9000
```

Required webhook URL in GitHub settings:

`https://<current-trycloudflare-domain>/webhook/github`

Webhook options:

- Content type: `application/json`
- Secret: must match `GITHUB_WEBHOOK_SECRET` in `.env`
- Events: `pull_request`, `pull_request_review`, `pull_request_review_comment`, `issues`, `issue_comment`

## 3. Why REAL Data May Be Missing

If output says `REAL=0`, check in order:

1. GitHub webhook URL points to an expired quick tunnel domain.
2. Webhook path is missing `/webhook/github`.
3. Content type is `form` instead of `json`.
4. Secret mismatch causes signature 403.
5. Worker is not running, leaving events in `pending` / `processing`.

## 4. Where Data Is Stored

1. Raw events: SQLite `events` table in `db/shadow.db`
2. Module index: SQLite `modules` table in `db/shadow.db`
3. Final markdown pages: `wiki/<module>.md`

Useful checks:

```bash
uv run python scripts/resource_mgr.py status
uv run python scripts/resource_mgr.py list
bash scripts/verify_mcp_ingest.sh --module auth/session --query issue --since 7d --verbose
```

## 5. Frontmatter Traceability Fields

Frontmatter now keeps both legacy and structured references:

- `recent_prs`: legacy short refs (`#123`) for backward compatibility
- `recent_events`: structured source metadata for analysis and trace-back

Example:

```yaml
recent_events:
  - key: https://github.com/owner/repo/issues/202#issuecomment-1
    platform: github
    event_type: issue_comment
    ref: '#202'
    url: https://github.com/owner/repo/issues/202#issuecomment-1
    actor: alice
    issue_number: 202
    occurred_at: '2026-06-02 08:33:30'
```

Notes:

- `recent_events` is written when a module gets a new append/update event.
- Existing wiki files gain `recent_events` after the next update to that module.

## 6. Recovery Commands

Reset stuck events:

```bash
uv run python -c "
from scripts.db import get_connection
with get_connection() as conn:
    conn.execute(\"UPDATE events SET status='pending' WHERE status='processing'\")
print('Reset done')
"
```

Re-run worker:

```bash
uv run python scripts/distill/worker.py
uv run python scripts/resource_mgr.py status
```