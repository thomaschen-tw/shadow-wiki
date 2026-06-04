#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT"

PORT=9000
START_SLACK="auto"   # auto | true | false
SKIP_SYNC=false
NO_TUNNEL=false

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
MAGENTA='\033[0;35m'
NC='\033[0m'

step() { echo -e "\n${CYAN}▶ $1${NC}"; }
ok() { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
err() { echo -e "${RED}✗ $1${NC}"; }

usage() {
  cat <<'EOF'
One-click starter for webhook ingestion stack.

Starts:
  - scripts/ingest/github_connector.py (port 9000 by default)
  - scripts/distill/worker.py
  - scripts/ingest/slack_connector.py (auto if Slack tokens exist)
  - cloudflared quick tunnel (unless --no-tunnel)

Usage:
  bash scripts/start_ingest_stack.sh
  bash scripts/start_ingest_stack.sh --port 9000 --slack
  bash scripts/start_ingest_stack.sh --no-slack --no-sync
  bash scripts/start_ingest_stack.sh --no-tunnel

Options:
  --port N       GitHub webhook server port (default: 9000)
  --slack        Force start Slack connector
  --no-slack     Disable Slack connector
  --no-sync      Skip "uv sync"
  --no-tunnel    Do not start cloudflared
  --help, -h     Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="${2:?--port requires a number}"
      shift
      ;;
    --slack)
      START_SLACK="true"
      ;;
    --no-slack)
      START_SLACK="false"
      ;;
    --no-sync)
      SKIP_SYNC=true
      ;;
    --no-tunnel)
      NO_TUNNEL=true
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      err "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
  shift
done

if ! command -v uv >/dev/null 2>&1; then
  err "uv not found. Install it first (brew install uv)."
  exit 1
fi

if ! $NO_TUNNEL && ! command -v cloudflared >/dev/null 2>&1; then
  err "cloudflared not found. Install it first (brew install cloudflared)."
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  warn "Created .env from .env.example. Update tokens before production use."
fi

RUNTIME_DIR="$PROJECT_ROOT/.runtime"
mkdir -p "$RUNTIME_DIR"
RUN_ID="$(date +%Y%m%d_%H%M%S)"

declare -a PROC_NAMES=()
declare -a PROC_PIDS=()
declare -a PROC_LOGS=()
declare -a WATCHER_PIDS=()
LAST_LOG=""

register_proc() {
  local name="$1"
  local pid="$2"
  local log="$3"
  PROC_NAMES+=("$name")
  PROC_PIDS+=("$pid")
  PROC_LOGS+=("$log")
}

cleanup() {
  local i pid
  for pid in "${WATCHER_PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  for i in "${!PROC_PIDS[@]}"; do
    local pid="${PROC_PIDS[$i]}"
    local name="${PROC_NAMES[$i]}"
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      ok "Stopped $name (PID $pid)"
    fi
  done
}
trap cleanup EXIT INT TERM

start_bg() {
  local name="$1"
  local cmd="$2"
  local log="$RUNTIME_DIR/${name}_${RUN_ID}.log"
  LAST_LOG="$log"
  step "Starting $name"
  (
    cd "$PROJECT_ROOT"
    eval "$cmd" >"$log" 2>&1
  ) &
  local pid=$!
  register_proc "$name" "$pid" "$log"
  ok "$name started (PID $pid, log: $log)"
}

start_log_watcher() {
  local label="$1"
  local log_file="$2"
  (
    local waited=0
    while [[ ! -f "$log_file" ]] && (( waited < 20 )); do
      sleep 0.5
      waited=$(( waited + 1 ))
    done
    [[ -f "$log_file" ]] || exit 0
    tail -n 0 -f "$log_file" 2>/dev/null | while IFS= read -r line; do
      local msg
      case "$line" in
        [0-9][0-9][0-9][0-9]-*\ INFO\ *)  msg="${line#* INFO }" ;;
        [0-9][0-9][0-9][0-9]-*\ ERROR\ *) msg="${line#* ERROR }" ;;
        INFO:*:*)                          msg="${line##*:}"; msg="${msg## }" ;;
        *)                                 continue ;;
      esac
      case "$msg" in
        "Processing "[0-9]*" event"*)
          printf "${YELLOW}  [WORKER]    ${NC}%s\n" "$msg"
          ;;
        "Queued PR #"*|"Queued PR review"*|"Queued review comment"*|\
        "Queued PR comment"*|"Queued issue comment"*|"Queued issue #"*)
          printf "${CYAN}  [INBOUND]   ${NC}%s\n" "$msg"
          ;;
        "Queued Slack "*)
          printf "${CYAN}  [INBOUND]   ${NC}%s\n" "$msg"
          ;;
        "Appended "*)
          local wiki_path="${msg##* }"
          printf "${GREEN}  [WRITE]     ${NC}%-52s→ wiki/%s.md\n" "$msg" "$wiki_path"
          ;;
        "Created module: "*|"Created knowledge page: "*)
          local wiki_path="${msg##*: }"
          printf "${GREEN}  [CREATE]    ${NC}%-52s→ wiki/%s.md\n" "$msg" "$wiki_path"
          ;;
        "Synthesized overview for "*)
          local wiki_path="${msg##* }"
          printf "${MAGENTA}  [SYNTH]     ${NC}%-52s→ wiki/%s.md\n" "$msg" "$wiki_path"
          ;;
        "Generated runbook for "*)
          local wiki_path="${msg##* }"
          printf "${MAGENTA}  [RUNBOOK]   ${NC}%-52s→ wiki/%s.md\n" "$msg" "$wiki_path"
          ;;
        *"failed:"*)
          printf "${RED}  [ERROR]     ${NC}%s\n" "$msg"
          ;;
      esac
    done
  ) &
  WATCHER_PIDS+=("$!")
}

env_has_real_value() {
  local key="$1"
  local val
  val="$(grep -E "^${key}=" .env | tail -1 | cut -d= -f2- || true)"
  [[ -n "$val" ]] || return 1
  [[ "$val" != "..." ]] || return 1
  [[ "$val" != *"..."* ]] || return 1
  return 0
}

wait_for_http() {
  local url="$1"
  local timeout_secs="$2"
  local elapsed=0
  while (( elapsed < timeout_secs )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

step "Preparing environment"
if ! $SKIP_SYNC; then
  uv sync --quiet
  ok "Dependencies ready"
else
  warn "Skipped uv sync (--no-sync)"
fi

uv run python scripts/resource_mgr.py init >/dev/null
ok "Database initialized"

start_bg "github_connector" "GITHUB_CONNECTOR_PORT=${PORT} uv run python scripts/ingest/github_connector.py"
if ! wait_for_http "http://127.0.0.1:${PORT}/docs" 25; then
  err "GitHub connector did not become ready on port ${PORT}."
  exit 1
fi
ok "GitHub connector is reachable on http://127.0.0.1:${PORT}"
start_log_watcher "github_connector" "$LAST_LOG"

start_bg "worker" "uv run python scripts/distill/worker.py"
start_log_watcher "worker" "$LAST_LOG"

if [[ "$START_SLACK" == "true" ]]; then
  start_bg "slack_connector" "uv run python scripts/ingest/slack_connector.py"
  start_log_watcher "slack_connector" "$LAST_LOG"
elif [[ "$START_SLACK" == "auto" ]]; then
  if env_has_real_value "SLACK_BOT_TOKEN" && env_has_real_value "SLACK_APP_TOKEN"; then
    start_bg "slack_connector" "uv run python scripts/ingest/slack_connector.py"
    start_log_watcher "slack_connector" "$LAST_LOG"
  else
    warn "Slack tokens not configured in .env, skipping Slack connector."
  fi
else
  warn "Slack connector disabled (--no-slack)."
fi

WEBHOOK_URL=""
if ! $NO_TUNNEL; then
  CF_LOG="$RUNTIME_DIR/cloudflared_${RUN_ID}.log"
  step "Starting cloudflared quick tunnel"
  (
    cd "$PROJECT_ROOT"
    cloudflared tunnel --url "http://localhost:${PORT}" >"$CF_LOG" 2>&1
  ) &
  CF_PID=$!
  register_proc "cloudflared" "$CF_PID" "$CF_LOG"
  ok "cloudflared started (PID $CF_PID, log: $CF_LOG)"

  for _ in {1..40}; do
    DOMAIN="$(grep -Eo 'https://[-a-zA-Z0-9]+\.trycloudflare\.com' "$CF_LOG" | tail -1 || true)"
    if [[ -n "$DOMAIN" ]]; then
      WEBHOOK_URL="${DOMAIN}/webhook/github"
      break
    fi
    sleep 1
  done

  if [[ -n "$WEBHOOK_URL" ]]; then
    ok "GitHub Webhook URL: $WEBHOOK_URL"
  else
    warn "Tunnel started but URL not detected yet. Check log: $CF_LOG"
  fi
else
  warn "Cloudflare tunnel disabled (--no-tunnel)."
fi

echo ""
echo "========== PulseWiki Ingest Stack =========="
echo "Project: $PROJECT_ROOT"
echo "GitHub connector: http://127.0.0.1:${PORT}/webhook/github"
if [[ -n "$WEBHOOK_URL" ]]; then
  echo "Public webhook:  $WEBHOOK_URL"
fi
echo ""
echo "Running processes:"
for i in "${!PROC_PIDS[@]}"; do
  echo "- ${PROC_NAMES[$i]}  pid=${PROC_PIDS[$i]}  log=${PROC_LOGS[$i]}"
done
echo ""
echo -e "${CYAN}Live activity (log watchers active):${NC}"
echo -e "  ${CYAN}[INBOUND]${NC}   incoming GitHub / Slack event received"
echo -e "  ${GREEN}[WRITE]${NC}     wiki page updated with new content"
echo -e "  ${GREEN}[CREATE]${NC}    new wiki page created"
echo -e "  ${MAGENTA}[SYNTH]${NC}     overview section auto-refreshed"
echo -e "  ${MAGENTA}[RUNBOOK]${NC}   runbook section auto-generated"
echo -e "  ${YELLOW}[WORKER]${NC}    batch processing cycle"
echo -e "  ${RED}[ERROR]${NC}     processing failure"
echo ""
echo "Press Ctrl+C to stop all started processes."

while true; do
  for i in "${!PROC_PIDS[@]}"; do
    if ! kill -0 "${PROC_PIDS[$i]}" >/dev/null 2>&1; then
      err "${PROC_NAMES[$i]} exited unexpectedly. See log: ${PROC_LOGS[$i]}"
      exit 1
    fi
  done
  sleep 3
done
