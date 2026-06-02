#!/usr/bin/env bash
# Verify MCP retrieval with two modes:
# 1) Real-data mode (default): only read/query existing real data.
# 2) Test mode (--test): seed synthetic events, process them, then query.
#
# Usage:
#   bash scripts/verify_mcp_ingest.sh
#   bash scripts/verify_mcp_ingest.sh --module auth/session --query "issue"
#   bash scripts/verify_mcp_ingest.sh --test
#   bash scripts/verify_mcp_ingest.sh --test --enqueue-only
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT"
unset VIRTUAL_ENV || true

TEST_MODE=false
ENQUEUE_ONLY=false
MODULE_PATH="general"
QUERY="session retry"
SINCE="1d"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --test) TEST_MODE=true ;;
    --enqueue-only) ENQUEUE_ONLY=true ;;
    --module)
      MODULE_PATH="${2:?--module requires a module path}"
      shift
      ;;
    --query)
      QUERY="${2:?--query requires search text}"
      shift
      ;;
    --since)
      SINCE="${2:?--since requires time window like 1d or 24h}"
      shift
      ;;
    --help|-h)
      echo "Verify MCP ingestion/retrieval."
      echo ""
      echo "Usage:"
      echo "  bash scripts/verify_mcp_ingest.sh"
      echo "  bash scripts/verify_mcp_ingest.sh --module auth/session --query issue --since 7d"
      echo "  bash scripts/verify_mcp_ingest.sh --test"
      echo "  bash scripts/verify_mcp_ingest.sh --test --enqueue-only"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
  shift
done

if ! $TEST_MODE && $ENQUEUE_ONLY; then
  echo "--enqueue-only can only be used with --test"
  exit 1
fi

echo "==> Init database"
uv run python scripts/resource_mgr.py init >/dev/null

if $TEST_MODE; then
  echo "==> Test mode: seed synthetic GitHub + Slack events"
  SEED_OUTPUT="$(MODULE_PATH="$MODULE_PATH" uv run python - <<'PY'
import os
import json
from datetime import datetime

from scripts.db import push_event
from scripts.wiki.manager import create_module, module_exists

module_path = os.environ.get("MODULE_PATH", "general")

if not module_exists(module_path):
    create_module(
        module_path,
        "## Overview\n\nSeed module for MCP ingestion verification.\n\n"
        "## Recent Changes\n\n"
        "## Known Issues\n\n"
        "## Slack Discussions\n\n"
        "## Related Modules\n\n",
        "Seed module for verification",
    )

stamp = datetime.now().strftime("%Y%m%d%H%M%S")
seeded_ids = []

# Synthetic PR code event
seeded_ids.append(push_event(
    "github",
    "pr",
    json.dumps(
        {
            "pr_number": 9001,
            "title": f"Synthetic PR {stamp}: improve session retry",
            "description": "Improve retry logic for session refresh.",
            "diff": "+def refresh_session_with_retry(): pass",
            "body": "Adds safer session retry path.",
        }
    ),
))

# Synthetic PR review discussion
seeded_ids.append(push_event(
    "github",
    "pr_review",
    json.dumps(
        {
            "pr_number": 9001,
            "title": f"Synthetic PR {stamp}: improve session retry",
            "reviewer": "qa-bot",
            "state": "COMMENTED",
            "body": "Please add metrics around retries and timeout handling.",
            "url": "https://example.invalid/pr/9001/review/1",
        }
    ),
))

# Synthetic issue Q&A (plain issue comment)
seeded_ids.append(push_event(
    "github",
    "issue_comment",
    json.dumps(
        {
            "issue_number": 77,
            "title": f"Synthetic Issue {stamp}: token expiry confusion",
            "user": "reporter-bot",
            "body": "Q: Why does token expire early? A: clock skew in edge node.",
            "url": "https://example.invalid/issues/77#issuecomment-1",
        }
    ),
))

# Synthetic Slack message
seeded_ids.append(push_event(
    "slack",
    "message",
    json.dumps(
        {
            "channel": "C_SYNTHETIC",
            "user": "U_SYNTHETIC",
            "body": "Session timeout issue reproduced under burst traffic.",
            "ts": "1717228800.000100",
            "thread_ts": None,
            "is_thread_reply": False,
        }
    ),
))

# Synthetic Slack thread reply
seeded_ids.append(push_event(
    "slack",
    "thread_reply",
    json.dumps(
        {
            "channel": "C_SYNTHETIC",
            "user": "U_SYNTHETIC",
            "body": "Confirmed fix after increasing retry jitter; no failures in latest run.",
            "ts": "1717228801.000200",
            "thread_ts": "1717228800.000100",
            "is_thread_reply": True,
            "reply_count": 1,
        }
    ),
))

print("Synthetic events enqueued")
print("SEEDED_IDS=" + ",".join(str(i) for i in seeded_ids))
PY
  )"

  echo "$SEED_OUTPUT"
  SEEDED_IDS="$(echo "$SEED_OUTPUT" | awk -F= '/^SEEDED_IDS=/{print $2}' | tail -1)"
  if [[ -z "$SEEDED_IDS" ]]; then
    echo "Failed to parse seeded event ids"
    exit 1
  fi

  if $ENQUEUE_ONLY; then
    echo "==> Enqueue-only mode complete"
    echo "Run: uv run python scripts/distill/worker.py"
    exit 0
  fi

  echo "==> Process seeded events inline"
  SEEDED_IDS="$SEEDED_IDS" uv run python - <<'PY'
import os
from scripts.db import get_connection, mark_event_processing
from scripts.distill.worker import process_event

seeded_ids = [int(x) for x in os.environ.get("SEEDED_IDS", "").split(",") if x.strip()]
if not seeded_ids:
    print("Processing 0 events (no seeded ids)")
    raise SystemExit(0)

q_marks = ",".join(["?"] * len(seeded_ids))
with get_connection() as conn:
    events = conn.execute(
        f"SELECT * FROM events WHERE status='pending' AND id IN ({q_marks}) ORDER BY id",
        tuple(seeded_ids),
    ).fetchall()

print(f"Processing {len(events)} events (seeded only)")
for e in events:
    mark_event_processing(e["id"])
    process_event(e)
print("Processing complete")
PY
else
  echo "==> Real-data mode (no synthetic event generation)"
fi

echo "==> MCP/data verification summary"
MODULE_PATH="$MODULE_PATH" QUERY="$QUERY" SINCE="$SINCE" uv run python - <<'PY'
import json
import os
from scripts.db import get_connection
from scripts.mcp_server import get_module, get_recent_changes, search_wiki

module_path = os.environ.get("MODULE_PATH", "general")
query = os.environ.get("QUERY", "session retry")
since = os.environ.get("SINCE", "1d")

print(f"\n--- Recent done events ({since}) ---")
for row in get_recent_changes(since)[:12]:
    print(f"{row['source']}/{row['event_type']} | {row.get('title', '')}")

print(f"\n--- Search '{query}' ---")
rows = search_wiki(query, limit=8)
if not rows:
    print("No wiki search hits yet. Ensure worker processed real events first.")
for row in rows:
    print(f"{row['module']}: {row['snippet']}")

print("\n--- GitHub issue Q&A events (latest 10) ---")
with get_connection() as conn:
    issue_rows = conn.execute(
        """
        SELECT event_type, raw_json, status, created_at
        FROM events
        WHERE source='github' AND event_type IN ('issue', 'issue_comment', 'pr_comment')
        ORDER BY id DESC LIMIT 10
        """
    ).fetchall()

if not issue_rows:
    print("No GitHub issue/Q&A events yet.")
else:
    for r in issue_rows:
        try:
            raw = json.loads(r['raw_json'])
        except Exception:
            raw = {}
        title = raw.get('title', '')
        body = (raw.get('body', '') or '')[:80]
        print(f"{r['status']:10} {r['event_type']:13} {r['created_at']} | {title} | {body}")

print(f"\n--- Module preview: {module_path} ---")
module_text = get_module(module_path)
print(module_text[:1200])
PY

echo "==> Done"
echo "Tip: default mode reads real data only; use --test to seed synthetic data."