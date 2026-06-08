#!/usr/bin/env python3
"""
PulseWiki — Environment Checker
Run: uv run python test_env.py

Validates .env settings and tests live connectivity to every configured service.
"""
import sys
import os
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx

# ── Helpers ───────────────────────────────────────────────────────────────────

PASS  = "\033[32m[PASS]\033[0m"
FAIL  = "\033[31m[FAIL]\033[0m"
WARN  = "\033[33m[WARN]\033[0m"
SKIP  = "\033[90m[SKIP]\033[0m"
INFO  = "\033[36m[INFO]\033[0m"

results: list[tuple[str, str]] = []  # (status, message)


def ok(msg: str)   -> None: results.append(("PASS", msg)); print(f"{PASS} {msg}")
def fail(msg: str) -> None: results.append(("FAIL", msg)); print(f"{FAIL} {msg}")
def warn(msg: str) -> None: results.append(("WARN", msg)); print(f"{WARN} {msg}")
def skip(msg: str) -> None: results.append(("SKIP", msg)); print(f"{SKIP} {msg}")
def info(msg: str) -> None: print(f"{INFO} {msg}")


def is_placeholder(value: str) -> bool:
    """Detect template placeholder values like sk-ant-... or ghp_..."""
    return not value or value.endswith("...") or value in ("sk-...", "ghp_...", "xoxb-...", "xapp-...", "lin_...")


def probe(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    """GET url → (reachable, status_line)"""
    try:
        r = httpx.get(url, timeout=timeout)
        return True, f"HTTP {r.status_code}"
    except httpx.ConnectError:
        return False, "connection refused"
    except httpx.TimeoutException:
        return False, "timeout"
    except Exception as exc:
        return False, str(exc)


def get_models(base_url: str, api_key: str = "", timeout: float = 5.0) -> list[str]:
    """Return list of model IDs from an OpenAI-compatible /models endpoint."""
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        r = httpx.get(f"{base_url}/models", headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json().get("data", [])
        return [m.get("id", "") for m in data if m.get("id")]
    except Exception:
        return []


# ── Section 1: Python & packages ─────────────────────────────────────────────

print("\n═══════════════════════════════════════════════════")
print("  PulseWiki — Environment Check")
print("═══════════════════════════════════════════════════\n")

info(f"Python {sys.version.split()[0]} — {sys.executable}")

v = sys.version_info
if v >= (3, 12):
    ok(f"Python version {v.major}.{v.minor}.{v.micro} ≥ 3.12")
else:
    fail(f"Python {v.major}.{v.minor} — need 3.12+. Run: uv sync (uses .python-version)")

print()
info("Checking package imports...")
for pkg in [
    ("scripts.config", "config"),
    ("scripts.db",     "database"),
    ("scripts.distill.llm_router", "LLM router"),
    ("scripts.wiki.manager",       "wiki manager"),
    ("scripts.mcp_server",         "MCP server"),
    ("fastmcp",   "fastmcp"),
    ("openai",    "openai"),
    ("anthropic", "anthropic"),
    ("httpx",     "httpx"),
    ("fastapi",   "fastapi"),
    ("uvicorn",   "uvicorn"),
]:
    mod, label = pkg
    try:
        __import__(mod)
        ok(f"Import {label} ({mod})")
    except ImportError as exc:
        fail(f"Import {label} failed: {exc}  →  run: uv sync")


# ── Section 2: .env and config ────────────────────────────────────────────────

print()
info("Loading .env ...")

if not Path(".env").exists():
    fail(".env not found — run: cp .env.example .env")
else:
    ok(".env file found")

try:
    from scripts.config import Settings
    s = Settings()
    ok(f"Settings loaded (LOCAL={s.local_llm_backend.value}, CLOUD={s.cloud_llm_backend.value})")
except Exception as exc:
    fail(f"Settings failed to load: {exc}")
    print("\n  Fix .env and re-run.")
    sys.exit(1)

if s.use_cloud_llm:
    info("USE_CLOUD_LLM=true  → cloud used for new wiki pages")
else:
    info("USE_CLOUD_LLM=false → all tasks run on local LLM")

info(
    f"Model ids in .env: LMSTUDIO_MODEL={s.lmstudio_model!r}  "
    f"OLLAMA_MODEL={s.ollama_model!r}  QWEN_CLOUD_MODEL={s.qwen_cloud_model!r}"
)
info("Run: uv run python scripts/resource_mgr.py llm  — compare .env vs loaded models")

if s.use_local_db:
    info(f"USE_LOCAL_DB=true   → SQLite at {s.db_path}")
else:
    info(f"USE_LOCAL_DB=false  → DATABASE_URL={s.database_url or '(not set)'}")


# ── Section 3: Local LLM ──────────────────────────────────────────────────────

print()
info("Checking local LLM backends...")

lm_up, lm_models = False, []
ol_up, ol_models = False, []

lm_reach, lm_status = probe(f"{s.lmstudio_base_url}/models")
if lm_reach:
    lm_models = get_models(s.lmstudio_base_url)
    if s.lmstudio_model in lm_models:
        ok(f"LM Studio reachable — model '{s.lmstudio_model}' loaded ✓")
        lm_up = True
    elif lm_models:
        warn(f"LM Studio reachable — model '{s.lmstudio_model}' NOT loaded")
        warn(f"  Available models: {', '.join(lm_models[:5])}")
        warn(f"  → Change LMSTUDIO_MODEL in .env to one of the above, or load '{s.lmstudio_model}' in LM Studio")
    else:
        warn(f"LM Studio reachable but no models found — load a model in LM Studio")
else:
    skip(f"LM Studio not reachable ({s.lmstudio_base_url}) — {lm_status}")

ol_reach, ol_status = probe(f"{s.ollama_base_url}/models")
if ol_reach:
    ol_models = get_models(s.ollama_base_url)
    if s.ollama_model in ol_models:
        ok(f"Ollama reachable — model '{s.ollama_model}' available ✓")
        ol_up = True
    elif ol_models:
        warn(f"Ollama reachable — model '{s.ollama_model}' not found")
        warn(f"  Available: {', '.join(ol_models[:5])}")
        warn(f"  → Run: ollama pull {s.ollama_model}")
    else:
        warn(f"Ollama reachable but no models pulled — run: ollama pull {s.ollama_model}")
else:
    skip(f"Ollama not reachable ({s.ollama_base_url}) — {ol_status}")

if s.local_llm_backend.value == "auto":
    if lm_up or ol_up:
        ok("LOCAL_LLM_BACKEND=auto — at least one local backend available")
    else:
        fail("LOCAL_LLM_BACKEND=auto — no local backend reachable; start LM Studio or Ollama")
elif s.local_llm_backend.value == "lmstudio":
    if not lm_up:
        fail("LOCAL_LLM_BACKEND=lmstudio — LM Studio not reachable or model not loaded")
elif s.local_llm_backend.value == "ollama":
    if not ol_up:
        fail("LOCAL_LLM_BACKEND=ollama — Ollama not reachable or model not available")


# ── Section 4: Cloud LLM ──────────────────────────────────────────────────────

print()
info("Checking cloud LLM configuration...")

if s.cloud_llm_backend.value == "claude":
    if is_placeholder(s.anthropic_api_key):
        if s.use_cloud_llm:
            fail("ANTHROPIC_API_KEY not set but USE_CLOUD_LLM=true — set a real key or switch backend")
        else:
            skip("ANTHROPIC_API_KEY not set (USE_CLOUD_LLM=false — not needed)")
    else:
        # Verify Claude key with a lightweight models call
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=s.anthropic_api_key)
            # Cheapest check: list models (no tokens charged)
            client.models.list(limit=1)
            ok(f"Claude API key valid — model: {s.claude_model}")
        except anthropic.AuthenticationError:
            fail("ANTHROPIC_API_KEY rejected by Anthropic — check key in .env")
        except Exception as exc:
            warn(f"Claude API check failed: {exc}")

elif s.cloud_llm_backend.value == "qwen_cloud":
    if is_placeholder(s.dashscope_api_key):
        if s.use_cloud_llm:
            fail("DASHSCOPE_API_KEY not set but USE_CLOUD_LLM=true")
        else:
            skip("DASHSCOPE_API_KEY not set (USE_CLOUD_LLM=false — not needed)")
    else:
        models = get_models(s.qwen_cloud_base_url, s.dashscope_api_key, timeout=8)
        if models:
            match = s.qwen_cloud_model in models
            label = f"model '{s.qwen_cloud_model}' {'✓' if match else '(not listed)'}"
            (ok if match else warn)(f"Qwen Cloud API key valid — {label}")
            if not match:
                warn(f"  Available models: {', '.join(models[:8])}")
                warn(f"  → Change QWEN_CLOUD_MODEL in .env")
        else:
            warn(f"Qwen Cloud reachable but model list empty or auth failed — check DASHSCOPE_API_KEY")

elif s.cloud_llm_backend.value == "deepseek":
    if is_placeholder(s.deepseek_api_key):
        if s.use_cloud_llm:
            fail("DEEPSEEK_API_KEY not set but USE_CLOUD_LLM=true")
        else:
            skip("DEEPSEEK_API_KEY not set (USE_CLOUD_LLM=false — not needed)")
    else:
        models = get_models(s.deepseek_base_url, s.deepseek_api_key, timeout=8)
        if models:
            ok(f"DeepSeek API key valid — model: {s.deepseek_model}")
        else:
            warn("DeepSeek: could not list models — check DEEPSEEK_API_KEY and DEEPSEEK_BASE_URL")


# ── Section 5: GitHub ─────────────────────────────────────────────────────────

print()
info("Checking GitHub integration...")

if is_placeholder(s.github_token):
    skip("GITHUB_TOKEN not set — GitHub connector disabled (manual diff ingestion still works)")
else:
    try:
        r = httpx.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {s.github_token}", "Accept": "application/vnd.github.v3+json"},
            timeout=8,
        )
        if r.status_code == 200:
            login = r.json().get("login", "?")
            ok(f"GitHub token valid — authenticated as @{login}")
            if s.github_repo:
                ok(f"GITHUB_REPO = {s.github_repo}")
            else:
                warn("GITHUB_REPO not set — set to owner/repo for clarity")
            if not s.github_webhook_secret:
                warn("GITHUB_WEBHOOK_SECRET not set — webhook requests won't be validated (insecure in prod)")
            else:
                ok(f"GITHUB_WEBHOOK_SECRET set ({len(s.github_webhook_secret)} chars)")
        elif r.status_code == 401:
            fail("GITHUB_TOKEN rejected (401) — regenerate token at github.com/settings/tokens")
        else:
            warn(f"GitHub API returned HTTP {r.status_code}")
    except Exception as exc:
        warn(f"GitHub connectivity check failed: {exc}")


# ── Section 6: Slack ──────────────────────────────────────────────────────────

print()
info("Checking Slack integration...")

if is_placeholder(s.slack_bot_token) or is_placeholder(s.slack_app_token):
    skip("SLACK_BOT_TOKEN / SLACK_APP_TOKEN not set — Slack connector disabled")
else:
    try:
        r = httpx.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {s.slack_bot_token}"},
            timeout=8,
        )
        data = r.json()
        if data.get("ok"):
            ok(f"Slack bot token valid — workspace: {data.get('team')}, bot: {data.get('user')}")
        else:
            fail(f"Slack auth failed: {data.get('error', 'unknown')} — check SLACK_BOT_TOKEN")
    except Exception as exc:
        warn(f"Slack connectivity check failed: {exc}")

    if not s.slack_channels:
        warn("SLACK_CHANNELS not set — connector will accept messages from ALL channels")
    else:
        ok(f"SLACK_CHANNELS = {s.slack_channels}")


# ── Section 7: Linear ─────────────────────────────────────────────────────────

print()
info("Checking Linear integration...")

if is_placeholder(s.linear_api_key):
    skip("LINEAR_API_KEY not set — Linear connector disabled")
else:
    try:
        r = httpx.post(
            "https://api.linear.app/graphql",
            json={"query": "{ viewer { id name } }"},
            headers={"Authorization": s.linear_api_key, "Content-Type": "application/json"},
            timeout=8,
        )
        data = r.json()
        viewer = (data.get("data") or {}).get("viewer", {})
        if viewer.get("name"):
            ok(f"Linear API key valid — authenticated as {viewer['name']}")
        else:
            errors = data.get("errors", [{}])
            fail(f"Linear auth failed: {errors[0].get('message', 'unknown')} — check LINEAR_API_KEY")
    except Exception as exc:
        warn(f"Linear connectivity check failed: {exc}")


# ── Section 8: Storage ────────────────────────────────────────────────────────

print()
info("Checking storage paths...")

db_dir = Path(s.db_path).parent
try:
    db_dir.mkdir(parents=True, exist_ok=True)
    test_file = db_dir / ".write_test"
    test_file.write_text("ok")
    test_file.unlink()
    ok(f"DB directory writable: {db_dir}")
except Exception as exc:
    fail(f"DB directory not writable ({db_dir}): {exc}")

wiki_dir = Path(s.resolved_wiki_dir)
try:
    wiki_dir.mkdir(parents=True, exist_ok=True)
    test_file = wiki_dir / ".write_test"
    test_file.write_text("ok")
    test_file.unlink()
    ok(f"Wiki directory writable: {wiki_dir}")
except Exception as exc:
    fail(f"Wiki directory not writable ({wiki_dir}): {exc}")

raw_dir = Path(s.raw_dir)
try:
    raw_dir.mkdir(parents=True, exist_ok=True)
    ok(f"Raw directory exists: {raw_dir}")
except Exception as exc:
    warn(f"Raw directory could not be created ({raw_dir}): {exc}")

if s.use_local_db and Path(s.db_path).exists():
    size = Path(s.db_path).stat().st_size
    ok(f"SQLite database exists ({size:,} bytes): {s.db_path}")
elif s.use_local_db:
    info(f"SQLite database not yet created — run: uv run python scripts/resource_mgr.py init")


# ── Summary ───────────────────────────────────────────────────────────────────

print()
print("═══════════════════════════════════════════════════")
passed  = sum(1 for s, _ in results if s == "PASS")
failed  = sum(1 for s, _ in results if s == "FAIL")
warned  = sum(1 for s, _ in results if s == "WARN")
skipped = sum(1 for s, _ in results if s == "SKIP")
print(f"  {passed} passed  |  {failed} failed  |  {warned} warnings  |  {skipped} skipped")
print("═══════════════════════════════════════════════════")

if failed > 0:
    print("\n\033[31mFailed checks:\033[0m")
    for status, msg in results:
        if status == "FAIL":
            print(f"  • {msg}")
    print("\nFix the items above, then re-run: uv run python test_env.py")
    sys.exit(1)
elif warned > 0:
    print("\n\033[33m⚠ Warnings present — system may work but review the items above.\033[0m")
    print("Ready to run: bash demo.sh")
else:
    print("\n\033[32m✓ All checks passed! Run: bash demo.sh\033[0m")
