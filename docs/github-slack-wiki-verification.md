# GitHub PR + Slack Comment -> Wiki Verification

This guide validates two core PulseWiki paths end-to-end:

1. GitHub PR / review events update module wiki pages.
2. Slack messages / thread replies update module wiki pages.

It also includes a check to confirm unchanged files are not re-analyzed.

Quick path for real data (default, no synthetic data):

```bash
bash scripts/verify_mcp_ingest.sh --module auth/session --query issue --since 7d
```

Quick path for synthetic test data:

```bash
bash scripts/verify_mcp_ingest.sh --test
```

Default mode behavior:

- Does not create synthetic events.
- Reads real events/wiki data already in your DB and MCP index.

`--test` mode behavior:

- Seeds synthetic events (`pr`, `pr_review`, `issue_comment`, `message`, `thread_reply`).
- Processes only those newly-seeded events.
- Prints MCP query output.

What this script is trying to prove:

1. Raw GitHub and Slack events can be stored in the SQLite event queue.
2. The worker can classify those events to a module and update the wiki.
3. The MCP server can then read back the updated wiki content.

In other words, the script validates this path:

`synthetic event -> db.events -> worker.py -> wiki/*.md -> mcp_server.py`

---

## 0. What Each Command Is For

Before running the commands below, it helps to know what each one is supposed to achieve:

### `uv run python scripts/resource_mgr.py init`

Purpose:

- Create or migrate the SQLite database at `db/shadow.db`.
- Ensure the `events`, `modules`, `file_hashes`, and `wiki_fts` tables exist.

Handled data:

- Database schema only. It does not ingest external data.

Data source:

- Local filesystem only.

### `uv run python scripts/resource_mgr.py status`

Purpose:

- Show queue health: how many events are pending, how many failed, and when the last event finished.

Handled data:

- Reads status from the `events` table.

Data source:

- SQLite database `db/shadow.db`.

Typical output meaning:

- `pending > 0`: events are waiting for the worker.
- `failed > 0`: some event processing failed and needs inspection.
- `last_processed != null`: the worker successfully handled at least one event.

### `uv run python scripts/distill/worker.py`

Purpose:

- Poll `events` from the database.
- Route each event to the correct handler.
- Call the LLM pipeline.
- Update `wiki/*.md` and FTS search index.

Handled data:

- GitHub PRs, GitHub reviews/comments, Slack messages/thread replies, knowledge base notes, manual diff events.

Data source:

- Reads from `db.events`, not directly from GitHub or Slack.

### `uv run python scripts/ingest/github_connector.py`

Purpose:

- Receive GitHub webhook payloads over HTTP.
- Convert them into normalized queue events.

Handled data:

- `pull_request`
- `pull_request_review`
- `pull_request_review_comment`
- `issue_comment` on PRs only

Data source:

- GitHub webhook POST requests.

### `uv run python scripts/ingest/slack_connector.py`

Purpose:

- Listen to Slack Events API via Socket Mode.
- Convert Slack messages into normalized queue events.

Handled data:

- normal channel messages
- thread replies

Data source:

- Slack realtime event stream.

### `bash scripts/verify_mcp_ingest.sh`

Purpose:

- In default mode, query real data through MCP and DB summaries.
- In `--test` mode, create fake-but-realistic events in `db.events`, process them inline, then query through MCP.

Handled data (default mode):

- existing real data in `db.events`, `wiki_fts`, and `wiki/*.md`

Handled data (`--test` mode):

- synthetic `github/pr`
- synthetic `github/pr_review`
- synthetic `github/issue_comment`
- synthetic `slack/message`
- synthetic `slack/thread_reply`

Data source:

- Default mode: real local DB/wiki content produced by your connectors/worker.
- `--test` mode: local script-generated JSON payloads.

---

## 0.1 Sample Payloads

These are the kinds of records the system handles.

### Synthetic GitHub PR event

```json
{
    "pr_number": 9001,
    "title": "Synthetic PR 20260602103000: improve session retry",
    "description": "Improve retry logic for session refresh.",
    "diff": "+def refresh_session_with_retry(): pass",
    "body": "Adds safer session retry path."
}
```

Meaning:

- This is treated like a code-change event.
- `worker.py` sends it through `_handle_code_event()`.
- Result usually lands in `## Recent Changes`, and may create a new module page if needed.

### Synthetic GitHub review event

```json
{
    "pr_number": 9001,
    "title": "Synthetic PR 20260602103000: improve session retry",
    "reviewer": "qa-bot",
    "state": "COMMENTED",
    "body": "Please add metrics around retries and timeout handling.",
    "url": "https://example.invalid/pr/9001/review/1"
}
```

Meaning:

- This is treated like review discussion context.
- `worker.py` sends it through `_handle_review_event()`.
- Result is synthesized into a short changelog-style entry.

### Synthetic Slack thread reply event

```json
{
    "channel": "C_SYNTHETIC",
    "user": "U_SYNTHETIC",
    "body": "Confirmed fix after increasing retry jitter; no failures in latest run.",
    "ts": "1717228801.000200",
    "thread_ts": "1717228800.000100",
    "is_thread_reply": true,
    "reply_count": 1
}
```

Meaning:

- This is treated as discussion context, not code diff.
- `worker.py` sends it through `_handle_slack_thread_reply()`.
- Result lands in `## Slack Discussions` and updates frontmatter `slack_threads`.

---

## 1. Prerequisites

- `.env` is configured and passes `uv run python test_env.py`.
- DB initialized: `uv run python scripts/resource_mgr.py init`.
- Worker running: `uv run python scripts/distill/worker.py`.
- GitHub connector running (webhook mode): `uv run python scripts/ingest/github_connector.py`.
- Slack connector running (Socket Mode): `uv run python scripts/ingest/slack_connector.py`.

Optional visibility command:

```bash
# Read current queue health from SQLite.
# Use this before and after tests to see whether events were queued and processed.
uv run python scripts/resource_mgr.py status
```

---

## 2. Test GitHub PR -> Wiki

### 2.1 Trigger a PR-like event quickly (manual diff path)

```bash
# Push one fake code diff into the queue without needing GitHub webhook setup.
# This exercises the same worker code path as a normal PR/code-change event.
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
# First command: show queue health.
# Second command: list indexed wiki modules after the worker processes the event.
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

Suggested sample messages:

- Normal message: `Session timeout issue reproduced under burst traffic in auth/session.`
- Thread reply: `Confirmed fix after retry jitter update; no failures in latest run.`

Why these examples help:

- They mention a concrete module/topic (`auth/session`).
- They contain operational context that should show up clearly in the wiki.

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
# First scan: queue changed or new notes from KNOWLEDGE_BASE_PATH.
uv run python scripts/ingest/knowledge_base_scanner.py --once
uv run python scripts/resource_mgr.py status

# Second scan with no note changes: should enqueue little or nothing.
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
# Reset interrupted events back to pending so the worker can retry them.
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