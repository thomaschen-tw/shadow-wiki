# GitHub PR + Slack Comment -> Wiki Verification

This guide validates two core Shadow Wiki paths end-to-end:

1. GitHub PR / review events update module wiki pages.
2. Slack messages / thread replies update module wiki pages.

It also includes a check to confirm unchanged files are not re-analyzed.

Quick path (no real GitHub/Slack activity required):

```bash
bash scripts/verify_mcp_ingest.sh
```

This seeds synthetic events, processes them, and prints MCP query output.

---

## 1. Prerequisites

- `.env` is configured and passes `uv run python test_env.py`.
- DB initialized: `uv run python scripts/resource_mgr.py init`.
- Worker running: `uv run python scripts/distill/worker.py`.
- GitHub connector running (webhook mode): `uv run python scripts/ingest/github_connector.py`.
- Slack connector running (Socket Mode): `uv run python scripts/ingest/slack_connector.py`.

Optional visibility command:

```bash
uv run python scripts/resource_mgr.py status
```

---

## 2. Test GitHub PR -> Wiki

### 2.1 Trigger a PR-like event quickly (manual diff path)

```bash
echo "+def login(): pass" | uv run python scripts/ingest_diff.py --diff - --pr 101 --title "Add login path"
```

This should enqueue a GitHub-style `pr` event and be processed by the worker.

### 2.2 Trigger real review/comment events (webhook path)

Create or use an existing PR in GitHub, then:

- Add a PR review comment on a changed line.
- Submit a PR review (`APPROVED` / `CHANGES_REQUESTED` / `COMMENTED`).
- Add an issue comment on the PR conversation tab.

The webhook server should enqueue `review_comment`, `pr_review`, and `pr_comment` events.

### 2.3 Verify results

```bash
uv run python scripts/resource_mgr.py status
uv run python scripts/resource_mgr.py list
```

Inspect generated module pages under `wiki/` and verify:

- `## Recent Changes` contains new entries for PR/review activity.
- `last_updated` frontmatter changes.
- Every 5th `Recent Changes` entry can trigger `SYNTHESIZE` refresh of `## Overview`.

---

## 3. Test Slack Message/Comment -> Wiki

### 3.1 Send test Slack content

In a channel listed in `SLACK_CHANNELS`:

- Post a normal message about a module change.
- Reply in thread (this validates `thread_reply` path).

### 3.2 Verify connector intake

Slack connector logs should show accepted channel and queued events.

If nothing appears, confirm:

- Bot is invited to the channel (`/invite @your-bot`).
- Channel ID exists in `SLACK_CHANNELS`.

### 3.3 Verify wiki updates

Check affected module page in `wiki/`:

- Slack thread replies should append to `## Slack Discussions`.
- Frontmatter `slack_threads` should be updated.

---

## 4. Verify Unchanged Files Are Not Re-analyzed

For knowledge base scanning:

```bash
uv run python scripts/ingest/knowledge_base_scanner.py --once
uv run python scripts/resource_mgr.py status

# Run scanner again without changing notes
uv run python scripts/ingest/knowledge_base_scanner.py --once
uv run python scripts/resource_mgr.py status
```

Expected behavior:

- First run queues changed/new notes.
- Second run queues 0 or significantly fewer events if nothing changed.

Reason: scanner dedup uses file hash and similarity threshold.

---

## 5. GitHub Actions Daily Digest Validation

Workflow: `.github/workflows/daily-knowledge-digest.yml`

- Schedule: `0 2 * * *` (10:00 Asia/Shanghai).
- Runner type: `self-hosted` (must be online).

### If you see this error

`The job has exceeded the maximum execution time while awaiting a runner for 24h0m0s`

It means no self-hosted runner was online for that repository.

Fix checklist:

1. Go to GitHub -> Settings -> Actions -> Runners and confirm status is `Online`.
2. On your Mac runner host, run:

```bash
cd ~/actions-runner
./svc.sh status
sudo ./svc.sh start
```

3. Re-run workflow manually from Actions -> Daily Knowledge Digest -> Run workflow.

---

## 6. Fast Recovery Commands

If worker crashed with events stuck in `processing`:

```bash
uv run python -c "
from scripts.db import get_connection
with get_connection() as conn:
    conn.execute(\"UPDATE events SET status='pending' WHERE status='processing'\")
print('Reset done')
"
```

Then restart worker and verify queue drains:

```bash
uv run python scripts/distill/worker.py
uv run python scripts/resource_mgr.py status
```