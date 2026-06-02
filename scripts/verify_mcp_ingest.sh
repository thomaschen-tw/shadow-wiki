#!/usr/bin/env bash
# Verify end-to-end ingestion -> distillation -> MCP retrieval using synthetic data.
#
# Usage:
#   bash scripts/verify_mcp_ingest.sh
#   bash scripts/verify_mcp_ingest.sh --enqueue-only
#   bash scripts/verify_mcp_ingest.sh --module auth/session
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT"
# Avoid confusing uv warnings when another project's virtualenv is activated.
unset VIRTUAL_ENV || true

ENQUEUE_ONLY=false
MODULE_PATH="general"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --enqueue-only) ENQUEUE_ONLY=true ;;
    --module)
      MODULE_PATH="${2:?--module requires a module path}"
      shift
      ;;
    --help|-h)
            echo "Verify end-to-end ingestion -> distillation -> MCP retrieval using synthetic data."
            echo ""
            echo "Usage:"
            echo "  bash scripts/verify_mcp_ingest.sh"
            echo "  bash scripts/verify_mcp_ingest.sh --enqueue-only"
            echo "  bash scripts/verify_mcp_ingest.sh --module auth/session"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
  shift
done

echo "==> Init database"
uv run python scripts/resource_mgr.py init >/dev/null

echo "==> Seed synthetic GitHub + Slack events"
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

# Synthetic source 1: a GitHub PR-style code event.
# Real source in production: github_connector.py receives a pull_request webhook,
# fetches the diff from GitHub, then stores a normalized event in db.events.
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

# Synthetic source 2: a GitHub review event.
# Real source in production: pull_request_review webhook -> event_type=pr_review.
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

seeded_ids.append(push_event(
    "github",
    "pr_comment",
    json.dumps(
        {
            "pr_number": 9001,
            "title": f"Synthetic PR {stamp}: improve session retry",
            "user": "dev-bot",
            "body": "Added retry metrics and clarified backoff behavior.",
            "url": "https://example.invalid/pr/9001#issuecomment-1",
        }
    ),
))

# Synthetic source 3: a normal Slack channel message.
# Real source in production: slack_connector.py receives a Socket Mode event and
# stores it as source=slack, event_type=message.
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

# Synthetic source 4: a Slack thread reply.
# Real source in production: slack_connector.py detects thread_ts != ts and
# stores event_type=thread_reply, which worker.py writes into Slack Discussions.
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

echo "==> Process pending events inline"
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

echo "==> MCP verification summary"
MODULE_PATH="$MODULE_PATH" uv run python - <<'PY'
import os
from scripts.mcp_server import get_module, get_recent_changes, search_wiki

module_path = os.environ.get("MODULE_PATH", "general")

print("\n--- Recent done events (1d) ---")
# Reads processed rows from db.events so you can confirm queue consumption.
for row in get_recent_changes("1d")[:8]:
    print(f"{row['source']}/{row['event_type']} | {row.get('title', '')}")

print("\n--- Search 'session retry' ---")
# Queries the FTS search index built from generated wiki pages.
for row in search_wiki("session retry", limit=5):
    print(f"{row['module']}: {row['snippet']}")

print(f"\n--- Module preview: {module_path} ---")
# Reads the final wiki page through the same MCP surface an editor client uses.
module_text = get_module(module_path)
print(module_text[:1200])
PY

echo "==> Done"
echo "Next: open wiki/general.md and review 'Recent Changes' + 'Slack Discussions'."