#!/usr/bin/env bash
# PulseWiki ETL 分阶段栈启动脚本
# 一键启动 ETL 模式的分阶段处理流程：webhook -> db -> clean -> route -> distill -> wiki
#
# 核心特性：
#   - ETL runner 是一个 bash while 循环，不中断执行 etl-run all
#   - 周期向队列检查新事件，使用 --apply 真写入 wiki_content/etl
#   - 支持 --dry-run（仅模拟）和 --from-staging（从暂存记录重播）
# 
# 强制配置：PIPELINE_MODE=etl, WIKI_WRITE_TARGET=etl

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT"

PORT=9000
START_SLACK="auto"   # auto | true | false
SKIP_SYNC=false
NO_TUNNEL=false
ETL_INTERVAL=30
ETL_LIMIT=50
ETL_APPLY=true

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
MAGENTA='\033[0;35m'
NC='\033[0m'

step() { echo -e "\n${CYAN}> $1${NC}"; }
ok() { echo -e "${GREEN}[ok] $1${NC}"; }
warn() { echo -e "${YELLOW}[warn] $1${NC}"; }
err() { echo -e "${RED}[err] $1${NC}"; }

usage() {
  cat <<'EOF'
One-click starter for ETL staged ingestion stack.

Starts:
  - scripts/ingest/github_connector.py (port 9000 by default)
  - scripts/ingest/slack_connector.py (auto if Slack tokens exist)
  - ETL runner loop (resource_mgr.py etl-run all)
  - cloudflared quick tunnel (unless --no-tunnel)

Before starting processes, this script forces:
  - PIPELINE_MODE=etl
  - WIKI_WRITE_TARGET=etl

Usage:
  bash scripts/start_etl_stack.sh
  bash scripts/start_etl_stack.sh --port 9000 --interval 20 --limit 100
  bash scripts/start_etl_stack.sh --dry-run --no-sync
  bash scripts/start_etl_stack.sh --no-tunnel

Options:
  --port N        GitHub webhook server port (default: 9000)
  --interval N    ETL loop interval in seconds (default: 30)
  --limit N       etl-run batch limit per cycle (default: 50)
  --dry-run       Run etl-run without --apply
  --slack         Force start Slack connector
  --no-slack      Disable Slack connector
  --no-sync       Skip "uv sync"
  --no-tunnel     Do not start cloudflared
  --help, -h      Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="${2:?--port requires a number}"
      shift
      ;;
    --interval)
      ETL_INTERVAL="${2:?--interval requires a number}"
      shift
      ;;
    --limit)
      ETL_LIMIT="${2:?--limit requires a number}"
      shift
      ;;
    --dry-run)
      ETL_APPLY=false
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

if ! [[ "$ETL_INTERVAL" =~ ^[0-9]+$ ]] || [[ "$ETL_INTERVAL" -le 0 ]]; then
  err "--interval must be a positive integer"
  exit 1
fi

if ! [[ "$ETL_LIMIT" =~ ^[0-9]+$ ]] || [[ "$ETL_LIMIT" -le 0 ]]; then
  err "--limit must be a positive integer"
  exit 1
fi

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
        *)                                 msg="$line" ;;
      esac
      case "$msg" in
        "Queued PR #"*|"Queued PR review"*|"Queued review comment"*|\
        "Queued PR comment"*|"Queued issue comment"*|"Queued issue #"*)
          printf "${CYAN}  [INBOUND]   ${NC}%s\n" "$msg"
          ;;
        "Queued Slack "*)
          printf "${CYAN}  [INBOUND]   ${NC}%s\n" "$msg"
          ;;
        "ETL all:"*|"ETL replay:"*|"ETL route:"*|"ETL distill:"*|"ETL clean:"*)
          printf "${YELLOW}  [ETL]       ${NC}%s\n" "$msg"
          ;;
        "ETL clean stage "*|"ETL route stage "*|"ETL distill stage "*)
          printf "${YELLOW}  [ETL]       ${NC}%s\n" "$msg"
          ;;
        "Appended "*)
          local wiki_path="${msg##* }"
          printf "${GREEN}  [WRITE]     ${NC}%-52s -> wiki_content/etl/%s.md\n" "$msg" "$wiki_path"
          ;;
        "Created module: "*|"Created knowledge page: "*)
          local wiki_path="${msg##*: }"
          printf "${GREEN}  [CREATE]    ${NC}%-52s -> wiki_content/etl/%s.md\n" "$msg" "$wiki_path"
          ;;
        "Synthesized overview for "*)
          local wiki_path="${msg##* }"
          printf "${MAGENTA}  [SYNTH]     ${NC}%-52s -> wiki_content/etl/%s.md\n" "$msg" "$wiki_path"
          ;;
        "Generated runbook for "*)
          local wiki_path="${msg##* }"
          printf "${MAGENTA}  [RUNBOOK]   ${NC}%-52s -> wiki_content/etl/%s.md\n" "$msg" "$wiki_path"
          ;;
        *"failed:"*|*" ERROR "*)
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
uv run python scripts/resource_mgr.py pipeline etl >/dev/null   # 设置管道模式为 etl
uv run python scripts/resource_mgr.py target etl >/dev/null     # 设置输出目录为 wiki_content/etl
ok "Pipeline mode and target forced to etl"

# 启动 GitHub Webhook 服务器
start_bg "github_connector" "GITHUB_CONNECTOR_PORT=${PORT} uv run python scripts/ingest/github_connector.py"
if ! wait_for_http "http://127.0.0.1:${PORT}/docs" 25; then
  err "GitHub connector did not become ready on port ${PORT}."
  exit 1
fi
ok "GitHub connector is reachable on http://127.0.0.1:${PORT}"
start_log_watcher "github_connector" "$LAST_LOG"

# 可选：启动 Slack 连接器
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

# ============================================================================
# 【关键】ETL 运行循环 - 这是 ETL 脚本的核心区别于 legacy 的地方
# ============================================================================
# while true 不中断循环的执行：
#   1. resource_mgr.py etl-run all --apply|--dry-run --limit N
#      └─ 执行 clean -> route -> distill 三个阶段的串联批处理
#      └ 若 --apply：真正写入 wiki_content/etl 文件，修改 etl_staging 记录为 done
#      └ 若 --dry-run：仅仅模拟，不修改任何磁盘/数据库
#   2. resource_mgr.py etl-status
#      └─ 打印当前 pending events 和 staging 表的行计数，便于观察进度
#   3. sleep ${ETL_INTERVAL}
#      └─ 等待 N 秒（默认 30s）后继续下一轮
#
# 这个循环的使用场景：
#   - 白天用 --dry-run --interval 20 快速验证，查看 staging 构建过程
#   - 准备好后用 --apply --interval 30 真实落地，自动写入 wiki 页面
#   - 午夜回放用 etl-replay 指定时间窗口，此脚本跟进追赶
# ============================================================================

if $ETL_APPLY; then
  ETL_STAGE_CMD="uv run python scripts/resource_mgr.py etl-loop --apply --limit ${ETL_LIMIT} --base-sleep ${ETL_INTERVAL}"
  ok "ETL apply mode enabled (writes to wiki_content/etl)"
else
  ETL_STAGE_CMD="uv run python scripts/resource_mgr.py etl-loop --limit ${ETL_LIMIT} --base-sleep ${ETL_INTERVAL}"
  ok "ETL dry-run mode enabled (no writes, simulation only)"
fi

# 【关键】启动 ETL 不中断循环进程
start_bg "etl_runner" "${ETL_STAGE_CMD}"
start_log_watcher "etl_runner" "$LAST_LOG"

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
echo "========== PulseWiki ETL Stack =========="
echo "Project: $PROJECT_ROOT"
echo "Mode   : etl"
echo "Target : etl"
echo "ETL run: ${ETL_STAGE_CMD}"
echo "Interval: ${ETL_INTERVAL}s"
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
echo -e "  ${YELLOW}[ETL]${NC}       ETL stage summary / stage progress"
echo -e "  ${GREEN}[WRITE]${NC}     wiki page updated with new content (etl)"
echo -e "  ${GREEN}[CREATE]${NC}    new wiki page created (etl)"
echo -e "  ${MAGENTA}[SYNTH]${NC}     overview section auto-refreshed"
echo -e "  ${MAGENTA}[RUNBOOK]${NC}   runbook section auto-generated"
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
