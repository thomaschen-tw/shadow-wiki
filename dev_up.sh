#!/usr/bin/env bash
# PulseWiki — development bring-up (debug / study)
#
# Unlike demo.sh, this script:
#   • runs test_env.py (not just curl)
#   • processes ONE event inline by default (won't drain a large pending queue)
#   • reports done vs failed for that event
#   • optional --daemon to keep worker.py running afterward
#
# Usage:
#   bash dev_up.sh                  # code diff → single inline distill
#   bash dev_up.sh --knowledge      # scan vault (if configured) → one KB distill
#   bash dev_up.sh --daemon         # then leave worker running (Ctrl+C to stop)
#   bash dev_up.sh --worker-only    # init DB + worker only
#   bash dev_up.sh --cloud          # force Qwen/Claude for the one distill (local OOM)
#   bash dev_up.sh --help
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

MODE="code"
DAEMON=false
WORKER_ONLY=false
NO_INGEST=false
USE_CLOUD=false
SKIP_ENV=false
SCAN_KB=true
WAIT_SECS=300
DEMO_PR="dev-$(date +%s)"

step() { echo -e "\n${CYAN}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
err()  { echo -e "${RED}✗ $1${NC}"; }

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  echo ""
  echo "Options:"
  echo "  --knowledge       Scan KNOWLEDGE_BASE_PATH (--once), distill oldest pending KB event"
  echo "  --no-scan         With --knowledge, skip scanner (only distill existing pending)"
  echo "  --worker-only     Init DB and start worker; no ingest / no inline distill"
  echo "  --no-ingest       Init + status only; no test event (implies no inline distill)"
  echo "  --daemon, -d      Start worker.py after inline step; wait until Ctrl+C"
  echo "  --cloud           Use cloud LLM for the single inline distill (local OOM workaround)"
  echo "  --wait-secs N     Wait for inline distill (default: 300)"
  echo "  --skip-env        Skip test_env.py"
  echo "  --help, -h        Show this help"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --knowledge)     MODE="knowledge" ;;
    --no-scan)       SCAN_KB=false ;;
    --worker-only)   WORKER_ONLY=true ;;
    --no-ingest)     NO_INGEST=true ;;
    --daemon|-d)     DAEMON=true ;;
    --cloud)         USE_CLOUD=true ;;
    --wait-secs)     WAIT_SECS="${2:?--wait-secs requires a number}"; shift ;;
    --skip-env)      SKIP_ENV=true ;;
    --help|-h)       usage; exit 0 ;;
    *)               err "Unknown option: $1"; usage; exit 1 ;;
  esac
  shift
done

if $WORKER_ONLY; then
  NO_INGEST=true
fi

WORKER_PID=""
cleanup() {
  if [[ -n "$WORKER_PID" ]] && kill -0 "$WORKER_PID" 2>/dev/null; then
    kill "$WORKER_PID" 2>/dev/null || true
    echo "Worker stopped (PID $WORKER_PID)"
  fi
}
trap cleanup EXIT

# ── 0. Prerequisites ────────────────────────────────────────────────────────
step "Prerequisites"

if ! command -v uv &>/dev/null; then
  err "uv not found — install: brew install uv  or  pip install uv"
  exit 1
fi

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  warn "Created .env from .env.example — run: uv run python scripts/resource_mgr.py llm"
fi

step "Installing dependencies (uv sync)"
uv sync --quiet
ok "Dependencies ready"

if ! $SKIP_ENV; then
  step "Environment check (test_env.py)"
  if uv run python test_env.py; then
    ok "test_env.py passed (or warnings only)"
  else
    err "test_env.py reported failures — fix .env / services, or use --skip-env"
    exit 1
  fi
else
  warn "Skipped test_env.py (--skip-env)"
fi

# ── 1. Database ───────────────────────────────────────────────────────────────
step "Initialising database"
uv run python scripts/resource_mgr.py init
ok "Database ready"

step "Queue snapshot (before ingest)"
uv run python scripts/resource_mgr.py status
QUEUE_INFO=$(uv run python -c "
from scripts.db import init_db, get_pipeline_status
init_db()
s = get_pipeline_status()
print(s['pending'], s['failed'])
" 2>/dev/null || echo "0 0")
read -r PENDING_BEFORE FAILED_BEFORE <<< "$QUEUE_INFO"

if [[ "${PENDING_BEFORE:-0}" -gt 0 ]] && ! $WORKER_ONLY && ! $NO_INGEST; then
  warn "There are already $PENDING_BEFORE pending events — inline mode will NOT drain them"
  warn "Use --daemon only if you intend to process the full queue (may take a long time)"
fi

# ── 2. Optional knowledge scan ────────────────────────────────────────────────
EVENT_ID=""

if [[ "$MODE" == "knowledge" ]]; then
  if $SCAN_KB; then
    step "Scanning knowledge base (--once)"
    if ! uv run python scripts/ingest/knowledge_base_scanner.py --once; then
      err "Scanner failed — set KNOWLEDGE_BASE_PATH in .env"
      exit 1
    fi
    ok "Scanner finished"
  else
    warn "Skipped scanner (--no-scan)"
  fi
fi

# ── 3. Ingest one test event (code mode) ──────────────────────────────────────
if [[ "$MODE" == "code" ]] && ! $NO_INGEST; then
  step "Queueing code test diff (PR $DEMO_PR)"
  TEST_DIFF=$(cat <<'DIFF'
diff --git a/auth/session.py b/auth/session.py
+++ b/auth/session.py
@@ -0,0 +1,8 @@
+import hashlib
+
+def create_session(user_id: str) -> str:
+    return hashlib.sha256(user_id.encode()).hexdigest()
+
+def validate_session(token: str) -> bool:
+    return len(token) == 64
DIFF
)
  INGEST_OUT=$(echo "$TEST_DIFF" | uv run python scripts/ingest_diff.py \
    --diff - --pr "$DEMO_PR" --title "dev_up: session helpers" 2>&1)
  echo "$INGEST_OUT"
  EVENT_ID=$(echo "$INGEST_OUT" | sed -n 's/^Queued event #\([0-9]*\).*/\1/p')
  if [[ -z "$EVENT_ID" ]]; then
    err "Could not parse event id from ingest_diff output"
    exit 1
  fi
  ok "Queued event #$EVENT_ID"
fi

# ── 4. Inline distill (one event) ─────────────────────────────────────────────
if ! $NO_INGEST && ! $WORKER_ONLY; then
  step "Inline distill (single event, up to ${WAIT_SECS}s)"
  if $USE_CLOUD; then
    warn "Using cloud LLM for this run (--cloud)"
  fi

  uv run python - "$MODE" "$EVENT_ID" "$USE_CLOUD" "$WAIT_SECS" <<'PY'
import sys
import time
import logging

import scripts.distill.llm_router as lr
import scripts.distill.worker as worker
from scripts.db import init_db, get_connection, get_pending_events
from scripts.distill.worker import process_event

mode, event_id_s, use_cloud_s, wait_s = sys.argv[1:5]
use_cloud = use_cloud_s.lower() == "true"
wait_secs = int(wait_s)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

if use_cloud:
    worker.call_llm = lambda task, prompt, system="You are a helpful assistant.": lr._call_cloud(
        prompt, system
    )

init_db()

if mode == "knowledge":
    if event_id_s:
        eid = int(event_id_s)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM events WHERE id = ?", (eid,)
            ).fetchone()
        if not row:
            print("ERROR: event not found", eid, file=sys.stderr)
            sys.exit(1)
        event = dict(row)
    else:
        pending = get_pending_events(limit=50)
        kb = [e for e in pending if e["source"] == "knowledge_base"]
        if not kb:
            print("ERROR: no pending knowledge_base events — run scanner or check KNOWLEDGE_BASE_PATH",
                  file=sys.stderr)
            sys.exit(1)
        event = kb[0]
        eid = event["id"]
else:
    eid = int(event_id_s)
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
    if not row:
        print("ERROR: event not found", eid, file=sys.stderr)
        sys.exit(1)
    event = dict(row)

import json
raw = json.loads(event["raw_json"])
label = raw.get("relative_path") or raw.get("title") or event.get("event_type", "?")
print(f"PROCESS event_id={eid} source={event['source']} label={label!r}")

t0 = time.time()
process_event(event)
elapsed = time.time() - t0

deadline = time.time() + max(5, wait_secs - int(elapsed))
status = "unknown"
error = ""
while time.time() < deadline:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status, error FROM events WHERE id = ?", (eid,)
        ).fetchone()
    status = row["status"]
    error = row["error"] or ""
    if status in ("done", "failed"):
        break
    time.sleep(2)

print(f"RESULT status={status} elapsed={time.time()-t0:.1f}s")
if error:
    print(f"ERROR {error}")
sys.exit(0 if status == "done" else 1)
PY

  DISTILL_EXIT=$?
  if [[ $DISTILL_EXIT -eq 0 ]]; then
    ok "Inline distill succeeded"
  else
    err "Inline distill failed — try --cloud if local model OOM; see worker log above"
    if ! $DAEMON; then
      exit 1
    fi
  fi
fi

# ── 5. Results ────────────────────────────────────────────────────────────────
step "Pipeline status"
uv run python scripts/resource_mgr.py status

step "Indexed modules"
uv run python scripts/resource_mgr.py list

step "Wiki files (newest first)"
find wiki -name "*.md" -print0 2>/dev/null | xargs -0 ls -t 2>/dev/null | head -8 || true

# ── 6. Optional daemon worker ─────────────────────────────────────────────────
if $DAEMON || $WORKER_ONLY; then
  if pgrep -f "[p]ython.*scripts/distill/worker.py" >/dev/null 2>&1; then
    warn "A worker.py process may already be running — second instance can race on events"
  fi
  step "Starting distillation worker (background)"
  uv run python scripts/distill/worker.py &
  WORKER_PID=$!
  ok "Worker PID $WORKER_PID (poll interval 30s)"
  echo ""
  echo -e "${GREEN}Dev stack up.${NC} Worker will process remaining pending events."
  echo "  Stop: Ctrl+C"
  echo "  Status: uv run python scripts/resource_mgr.py status"
  echo "  MCP config:"
  UV_BIN="$(command -v uv)"
  cat <<EOF
{
  "mcpServers": {
    "pulse-wiki": {
      "command": "$UV_BIN",
      "args": ["run", "python", "$PROJECT_ROOT/scripts/mcp_server.py"]
    }
  }
}
EOF
  wait "$WORKER_PID"
else
  echo ""
  echo -e "${GREEN}Dev bring-up complete.${NC} (no daemon — queue not drained)"
  echo "  Start worker: uv run python scripts/distill/worker.py &"
  echo "  Full MVP demo: bash demo.sh"
fi
