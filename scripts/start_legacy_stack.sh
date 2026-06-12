#!/usr/bin/env bash# PulseWiki 旧版实时栈启动脚本
# 一键启动 legacy 模式的实时处理流程：webhook -> db -> worker -> wiki
# 
# 启动进程：
#   - GitHub Webhook 服务器（FastAPI，端口 9000）
#   - distill worker（实时轮询，30s 一次）
#   - Slack 连接器（可选）
#   - cloudflared 隧道（可选，用于公网访问）
#
# 强制配置：
#   - PIPELINE_MODE=legacy（实时管道模式）
#   - WIKI_WRITE_TARGET=legacy（输出到 wiki_content/legacy）
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT"

# ──────────────────────────────────────────────────────────────────────────
# 配置参数
# ──────────────────────────────────────────────────────────────────────────
PORT=9000
START_SLACK="auto"   # auto | true | false
SKIP_SYNC=false
NO_TUNNEL=false

# 日志颜色代码
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
MAGENTA='\033[0;35m'
NC='\033[0m'

# ──────────────────────────────────────────────────────────────────────────
# 日志函数
# ──────────────────────────────────────────────────────────────────────────
step() { echo -e "\n${CYAN}> $1${NC}"; }     # 步骤提示（青色）
ok() { echo -e "${GREEN}[ok] $1${NC}"; }     # 成功（绿色）
warn() { echo -e "${YELLOW}[warn] $1${NC}"; } # 警告（黄色）
err() { echo -e "${RED}[err] $1${NC}"; }     # 错误（红色）

usage() {
  cat <<'EOF'
One-click starter for LEGACY realtime ingestion stack.

Starts:
  - scripts/ingest/github_connector.py (port 9000 by default)
  - scripts/distill/worker.py
  - scripts/ingest/slack_connector.py (auto if Slack tokens exist)
  - cloudflared quick tunnel (unless --no-tunnel)

Before starting processes, this script forces:
  - PIPELINE_MODE=legacy
  - WIKI_WRITE_TARGET=legacy

Usage:
  bash scripts/start_legacy_stack.sh
  bash scripts/start_legacy_stack.sh --port 9000 --slack
  bash scripts/start_legacy_stack.sh --no-slack --no-sync
  bash scripts/start_legacy_stack.sh --no-tunnel

Options:
  --port N       GitHub webhook server port (default: 9000)
  --slack        Force start Slack connector
  --no-slack     Disable Slack connector
  --no-sync      Skip "uv sync"
  --no-tunnel    Do not start cloudflared
  --help, -h     Show this help
EOF
}

# ──────────────────────────────────────────────────────────────────────────
# 命令行参数解析
# ──────────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="${2:?--port requires a number}"  # GitHub webhook 监听端口
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

# ──────────────────────────────────────────────────────────────────────────
# 依赖检查
# ──────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────
# 进程管理：运行时目录 & 进程追踪
# ──────────────────────────────────────────────────────────────────────────
RUNTIME_DIR="$PROJECT_ROOT/.runtime"  # 日志输出目录
mkdir -p "$RUNTIME_DIR"
RUN_ID="$(date +%Y%m%d_%H%M%S)"        # 本次运行的唯一 ID

# 后台进程追踪数组
declare -a PROC_NAMES=()   # 进程名称
declare -a PROC_PIDS=()    # 进程 ID
declare -a PROC_LOGS=()    # 日志文件路径
declare -a WATCHER_PIDS=() # 日志监视器 PID（tail -f 进程）
LAST_LOG=""                # 最后启动的进程日志路径

# 注册后台进程以便后续追踪和清理
register_proc() {
  local name="$1"
  local pid="$2"
  local log="$3"
  PROC_NAMES+=("$name")
  PROC_PIDS+=("$pid")
  PROC_LOGS+=("$log")
}

# Ctrl+C 时的清理函数：停止所有后台进程
cleanup() {
  local i pid
  # 先杀死所有日志监视器（tail -f）
  for pid in "${WATCHER_PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  # 再杀死所有主进程
  for i in "${!PROC_PIDS[@]}"; do
    local pid="${PROC_PIDS[$i]}"
    local name="${PROC_NAMES[$i]}"
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      ok "Stopped $name (PID $pid)"
    fi
  done
}
# 捕获 EXIT / Ctrl+C / SIGTERM，自动清理
trap cleanup EXIT INT TERM

# 后台启动一个进程：将输出重定向到日志文件
start_bg() {
  local name="$1"
  local cmd="$2"
  local log="$RUNTIME_DIR/${name}_${RUN_ID}.log"
  LAST_LOG="$log"
  step "Starting $name"
  (
    cd "$PROJECT_ROOT"
    eval "$cmd" >"$log" 2>&1  # 所有输出（stdout & stderr）写入日志
  ) &
  local pid=$!  # 获取后台进程 ID
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
        "Processing "[0-9]*" event"*|"Processing "[0-9]*" events"*)
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
          printf "${GREEN}  [WRITE]     ${NC}%-52s -> wiki_content/legacy/%s.md\n" "$msg" "$wiki_path"
          ;;
        "Created module: "*|"Created knowledge page: "*)
          local wiki_path="${msg##*: }"
          printf "${GREEN}  [CREATE]    ${NC}%-52s -> wiki_content/legacy/%s.md\n" "$msg" "$wiki_path"
          ;;
        "Synthesized overview for "*)
          local wiki_path="${msg##* }"
          printf "${MAGENTA}  [SYNTH]     ${NC}%-52s -> wiki_content/legacy/%s.md\n" "$msg" "$wiki_path"
          ;;
        "Generated runbook for "*)
          local wiki_path="${msg##* }"
          printf "${MAGENTA}  [RUNBOOK]   ${NC}%-52s -> wiki_content/legacy/%s.md\n" "$msg" "$wiki_path"
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

# ──────────────────────────────────────────────────────────────────────────
# 主流程：准备环境
# ──────────────────────────────────────────────────────────────────────────
step "Preparing environment"
if ! $SKIP_SYNC; then
  uv sync --quiet  # 安装/更新所有 Python 依赖
  ok "Dependencies ready"
else
  warn "Skipped uv sync (--no-sync)"
fi

# 初始化数据库和强制配置
uv run python scripts/resource_mgr.py init >/dev/null
uv run python scripts/resource_mgr.py pipeline legacy >/dev/null  # 设置管道模式
uv run python scripts/resource_mgr.py target legacy >/dev/null    # 设置输出目录
ok "Pipeline mode and target forced to legacy"

# 启动 GitHub Webhook 服务器
start_bg "github_connector" "GITHUB_CONNECTOR_PORT=${PORT} uv run python scripts/ingest/github_connector.py"
if ! wait_for_http "http://127.0.0.1:${PORT}/docs" 25; then
  err "GitHub connector did not become ready on port ${PORT}."
  exit 1
fi
ok "GitHub connector is reachable on http://127.0.0.1:${PORT}"
start_log_watcher "github_connector" "$LAST_LOG"  # 启动日志实时输出监视器

# 启动实时蒸馏 worker（核心进程，30s 轮询一次 pending events）
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
echo "========== PulseWiki Legacy Stack =========="
echo "Project: $PROJECT_ROOT"
echo "Mode   : legacy"
echo "Target : legacy"
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
echo -e "  ${GREEN}[WRITE]${NC}     wiki page updated with new content (legacy)"
echo -e "  ${GREEN}[CREATE]${NC}    new wiki page created (legacy)"
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
