# GitHub Integration Setup

Shadow Wiki listens to GitHub webhooks to automatically capture PR diffs and review comments. This guide explains what each setting does and how to set it up step by step.

---

## What Each Setting Does

| Variable | Required | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | **Yes** | Fetches the full PR diff from GitHub API (Bearer auth). Without this, diffs arrive empty and the wiki gets no code context. |
| `GITHUB_REPO` | No | Reference label only — displayed in logs and docs. Not used in code. Set it to `owner/repo` for clarity. |
| `GITHUB_WEBHOOK_SECRET` | Recommended | HMAC-SHA256 secret shared with GitHub. Validates that webhook payloads are genuine. If left empty, all POST requests to `:9000` are accepted without verification (fine for local dev, risky in production). |

---

## Step-by-Step Setup

### Step 1 — Create a Personal Access Token (PAT)

1. Go to **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. Click **Generate new token (classic)**
3. Name: `shadow-wiki`
4. Expiration: 90 days (or no expiration for a personal project)
5. Scopes: check **`repo`** (gives read access to code, PRs, issues)
6. Click **Generate token** — copy the token immediately, it won't be shown again
7. In `.env`:
   ```env
   GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
   GITHUB_REPO=your-org/your-repo
   ```

### Step 2 — Generate a Webhook Secret

Generate a random secret (you choose this — GitHub will send it back on every webhook):

```bash
openssl rand -hex 20
# example output: a3f8d2e1c4b7906543210fedcba98765432109
```

In `.env`:
```env
GITHUB_WEBHOOK_SECRET=a3f8d2e1c4b7906543210fedcba98765432109
```

### Step 3 — Start the Connector

```bash
uv run python scripts/ingest/github_connector.py
```

This starts a **FastAPI** server (Uvicorn) on port **9000**. Keep it running.

### Step 4 — Expose Port 9000 (local dev only)

GitHub needs a public HTTPS URL to deliver webhooks. For local development, use [ngrok](https://ngrok.com):

```bash
# Install: brew install ngrok  or  https://ngrok.com/download
ngrok http 9000
# → Forwarding: https://abc123.ngrok-free.app → localhost:9000
```

Copy the `https://abc123.ngrok-free.app` URL.

> For production, deploy the connector to a server with a real domain, or use a VPS.

### Step 5 — Configure the Webhook on GitHub

1. Go to your repo → **Settings → Webhooks → Add webhook**
2. Fill in:
   - **Payload URL**: `https://abc123.ngrok-free.app/webhook/github`
   - **Content type**: `application/json`
   - **Secret**: the same value you set in `GITHUB_WEBHOOK_SECRET`
   - **Which events**: choose **Let me select individual events**, then check:
     - ✅ Pull requests
     - ✅ Pull request review comments
3. Click **Add webhook**

GitHub will send a test ping. The connector logs should show `200 OK`.

### Step 6 — Test It

Open a PR on your repo (or re-open an existing one). Within seconds you should see:

```
INFO Queued PR #42
```

In the worker log:
```
INFO Processing 1 events
INFO Event 1 done
```

And a new `.md` file in `wiki/`.

---

## Verify the Integration

```bash
# Check for queued events
uv run python scripts/resource_mgr.py status

# See the raw event data
uv run python -c "
from scripts.db import get_connection, init_db
init_db()
with get_connection() as conn:
    rows = conn.execute(\"SELECT id, source, event_type, status FROM events ORDER BY id DESC LIMIT 5\").fetchall()
    for r in rows: print(dict(r))
"
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Webhook delivery fails (red ✗ on GitHub) | Check ngrok is running and URL matches |
| `403 Forbidden` from connector | `GITHUB_WEBHOOK_SECRET` mismatch — compare value in `.env` and GitHub |
| Diff is empty in wiki | `GITHUB_TOKEN` missing or lacks `repo` scope |
| Connector not running | `uv run python scripts/ingest/github_connector.py` — check port 9000 is free |
| Events stuck `pending` | Worker not running — `uv run python scripts/distill/worker.py` |

---

## Is GitHub Required to Run Shadow Wiki?

**No.** GitHub is one optional data source. You can run Shadow Wiki with just:

```bash
# Push diffs manually without GitHub
git diff HEAD~1 | uv run python scripts/ingest_diff.py --diff - --pr 1 --title "My change"
```

The local diff ingestion, Slack connector, Linear connector, and local file scanner all work independently of GitHub.
