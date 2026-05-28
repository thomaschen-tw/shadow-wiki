#!/usr/bin/env bash
# Shadow Wiki — MVP Demo
# Runs the full pipeline: init → worker → push diff → show wiki output
# Usage: bash demo.sh
set -euo pipefail

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
step() { echo -e "\n${CYAN}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }

# ── 0. Pre-flight ─────────────────────────────────────────────────────────────
step "Checking prerequisites"

if ! command -v uv &>/dev/null; then
  echo "uv not found. Install: pip install uv  or  brew install uv"; exit 1
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
  warn ".env created from template — edit LMSTUDIO_MODEL if your model name differs"
fi

# Check LM Studio or Ollama is reachable
LM_OK=false; OL_OK=false
curl -sf http://localhost:1234/v1/models -o /dev/null && LM_OK=true || true
curl -sf http://localhost:11434/v1/models -o /dev/null && OL_OK=true || true

if $LM_OK; then
  ok "LM Studio reachable at localhost:1234"
elif $OL_OK; then
  ok "Ollama reachable at localhost:11434"
  # Switch .env to ollama if LM Studio not running
  sed -i '' 's/^LOCAL_LLM_BACKEND=.*/LOCAL_LLM_BACKEND=ollama/' .env 2>/dev/null || \
    sed -i 's/^LOCAL_LLM_BACKEND=.*/LOCAL_LLM_BACKEND=ollama/' .env
else
  warn "Neither LM Studio nor Ollama is reachable."
  warn "Start LM Studio → Load Qwen model → Start Server, then re-run."
  warn "Or: ollama pull qwen3:8b && ollama serve"
  exit 1
fi

ok "Prerequisites OK"

# ── 1. Install deps ───────────────────────────────────────────────────────────
step "Installing dependencies (uv sync)"
uv sync --quiet
ok "Dependencies installed"

# ── 2. Init DB ────────────────────────────────────────────────────────────────
step "Initialising database"
uv run python scripts/resource_mgr.py init
ok "Database ready"

# ── 3. Start worker ───────────────────────────────────────────────────────────
step "Starting distillation worker (background)"
uv run python scripts/distill/worker.py &
WORKER_PID=$!
trap "kill $WORKER_PID 2>/dev/null; echo 'Worker stopped'" EXIT
ok "Worker PID $WORKER_PID"

# ── 4. Push a test diff ───────────────────────────────────────────────────────
step "Pushing test diff"
TEST_DIFF=$(cat <<'DIFF'
diff --git a/auth/session.py b/auth/session.py
+++ b/auth/session.py
@@ -0,0 +1,10 @@
+import redis
+import hashlib
+
+def create_session(user_id: str) -> str:
+    token = hashlib.sha256(f"{user_id}:{time.time()}".encode()).hexdigest()
+    redis_client.setex(f"session:{token}", 3600, user_id)
+    return token
+
+def validate_session(token: str) -> str | None:
+    return redis_client.get(f"session:{token}")
DIFF
)
echo "$TEST_DIFF" | uv run python scripts/ingest_diff.py \
  --diff - --pr 1 --title "Add Redis session management"
ok "Event queued"

# ── 5. Wait for worker ────────────────────────────────────────────────────────
step "Waiting for worker to process (up to 60s)..."
MAX=12; COUNT=0
while [ $COUNT -lt $MAX ]; do
  sleep 5; COUNT=$((COUNT+1))
  STATUS=$(uv run python -c "
from scripts.db import get_pipeline_status, init_db
init_db()
s = get_pipeline_status()
print(s['pending'])
" 2>/dev/null || echo "1")
  if [ "$STATUS" = "0" ]; then break; fi
  echo "  pending=$STATUS, elapsed=$((COUNT*5))s..."
done

# ── 6. Show results ───────────────────────────────────────────────────────────
step "Pipeline status"
uv run python scripts/resource_mgr.py status

step "Indexed modules"
uv run python scripts/resource_mgr.py list

step "Wiki files created"
find wiki -name "*.md" 2>/dev/null | head -10 || echo "  (none yet — LLM may still be processing)"

# ── 7. MCP server hint ────────────────────────────────────────────────────────
step "To connect Claude Code, add to ~/.claude/claude.json:"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo '{
  "mcpServers": {
    "shadow-wiki": {
      "command": "'"$(which uv)"'",
      "args": ["run", "python", "'"$SCRIPT_DIR/scripts/mcp_server.py"'"]
    }
  }
}'

echo -e "\n${GREEN}✓ MVP demo complete!${NC}"
echo -e "  Worker running (PID $WORKER_PID) — Ctrl+C to stop"
echo -e "  Wiki files are in: $SCRIPT_DIR/wiki/"
wait $WORKER_PID
