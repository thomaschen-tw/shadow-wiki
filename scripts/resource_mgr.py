#!/usr/bin/env python3
"""
Shadow Wiki resource manager.

Commands:
  init              Initialise the SQLite database
  status            Show pipeline queue health
  list              List all indexed wiki modules
  db on|off         Toggle USE_LOCAL_DB (on=SQLite, off=DATABASE_URL)
  cloud on|off      Toggle USE_CLOUD_LLM (on=cloud for new pages, off=all local)
  dev               Dev mode: pause Docker containers, unload local model from RAM
  compile           Compile mode: resume Docker containers, load local model into RAM
  llm               Show which models .env selects vs what LM Studio/Ollama expose
"""
import re
import subprocess
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.config import get_settings


# ── Shadow Wiki commands ───────────────────────────────────────────────────────

def cmd_init():
    from scripts.db import init_db
    init_db()
    print("Database initialized.")


def cmd_status():
    from scripts.db import get_pipeline_status, get_connection
    s = get_pipeline_status()
    with get_connection() as conn:
        module_count = conn.execute("SELECT COUNT(*) FROM modules").fetchone()[0]
    print(f"Pending : {s['pending']}")
    print(f"Failed  : {s['failed']}")
    print(f"Last run: {s['last_processed'] or 'never'}")
    print(f"Modules : {module_count}")


def cmd_list():
    from scripts.db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT path, summary, last_updated FROM modules ORDER BY path"
        ).fetchall()
    if not rows:
        print("No modules indexed yet.")
        return
    for r in rows:
        print(f"  {r['path']:<40} {r['last_updated'] or '—'}")
        if r["summary"]:
            print(f"    {r['summary'][:80]}")


# ── Database toggle ───────────────────────────────────────────────────────────

def cmd_db(state: str) -> None:
    if state not in ("on", "off"):
        print("Usage: resource_mgr.py db on|off")
        print("  on  = local SQLite (default)")
        print("  off = online database (set DATABASE_URL in .env)")
        sys.exit(1)
    value = "true" if state == "on" else "false"
    _update_env_key("USE_LOCAL_DB", value)
    from scripts.config import reload_settings
    reload_settings()
    if state == "on":
        db_path = get_settings().db_path
        print(f"Local DB enabled  →  {db_path}")
    else:
        url = get_settings().database_url
        if not url:
            print("Online DB selected. Set DATABASE_URL in .env to a PostgreSQL connection string.")
        else:
            print(f"Online DB enabled  →  {url}")


# ── Cloud toggle ───────────────────────────────────────────────────────────────

def _update_env_key(key: str, value: str, env_path: Path = Path(".env")) -> None:
    if not env_path.exists():
        env_path.write_text(f"{key}={value}\n")
        return
    text = env_path.read_text()
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(f"{key}={value}", text)
    else:
        text = text.rstrip("\n") + f"\n{key}={value}\n"
    env_path.write_text(text)


def cmd_cloud(state: str) -> None:
    if state not in ("on", "off"):
        print("Usage: resource_mgr.py cloud on|off")
        sys.exit(1)
    value = "true" if state == "on" else "false"
    _update_env_key("USE_CLOUD_LLM", value)
    from scripts.config import reload_settings
    reload_settings()
    label = "enabled" if state == "on" else "disabled"
    print(f"Cloud LLM {label}  (USE_CLOUD_LLM={value})")


# ── Local model memory (Ollama keep_alive / LM Studio warm-up) ─────────────────

def _toggle_ollama(model: str, action: str) -> None:
    keep_alive = -1 if action == "load" else 0
    payload = {"model": model, "messages": [], "keep_alive": keep_alive}
    try:
        resp = httpx.post("http://localhost:11434/api/chat", json=payload, timeout=30)
        if resp.status_code == 200:
            state = "loaded" if keep_alive == -1 else "released"
            print(f"Ollama: model '{model}' {state}.")
        else:
            print(f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        print(f"Could not reach Ollama: {exc}")


def _toggle_lmstudio(model: str, action: str) -> None:
    s = get_settings()
    if action == "unload":
        print(
            f"LM Studio: unload '{model}' in the LM Studio UI "
            "(no unload API). dev mode frees RAM when the model is ejected there."
        )
        return
    try:
        resp = httpx.post(
            f"{s.lmstudio_base_url}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=s.llm_timeout,
        )
        if resp.status_code == 200:
            print(f"LM Studio: warmed model '{model}' (chat/completions OK).")
        else:
            print(f"LM Studio HTTP {resp.status_code}: {resp.text[:300]}")
    except Exception as exc:
        print(f"Could not reach LM Studio: {exc}")


def toggle_local_llm(action: str) -> None:
    from scripts.distill.llm_router import get_active_local_model

    backend, model = get_active_local_model()
    print(f"Using {backend.value} → {model}")
    if backend.value == "ollama":
        _toggle_ollama(model, action)
    else:
        _toggle_lmstudio(model, action)


def _fetch_model_ids(base_url: str, api_key: str = "") -> list[str]:
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = httpx.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return [m["id"] for m in data.get("data", []) if m.get("id")]
    except Exception:
        return []


def cmd_llm() -> None:
    from scripts.distill.llm_router import get_active_local_backend, get_active_local_model

    s = get_settings()
    active_backend, active_model = get_active_local_model()

    print("Configured models (.env)")
    print(f"  LOCAL_LLM_BACKEND     = {s.local_llm_backend.value}")
    print(f"  LMSTUDIO_MODEL        = {s.lmstudio_model}")
    print(f"  OLLAMA_MODEL          = {s.ollama_model}")
    print(f"  USE_CLOUD_LLM         = {str(s.use_cloud_llm).lower()}")
    print(f"  CLOUD_LLM_BACKEND     = {s.cloud_llm_backend.value}")
    if s.cloud_llm_backend.value == "qwen_cloud":
        print(f"  QWEN_CLOUD_MODEL      = {s.qwen_cloud_model}")
    elif s.cloud_llm_backend.value == "claude":
        print(f"  CLAUDE_MODEL          = {s.claude_model}")
    else:
        print(f"  DEEPSEEK_MODEL        = {s.deepseek_model}")

    print("\nPipeline will use for local tasks (classify/summarize/append)")
    print(f"  → {active_backend.value} / {active_model}")

    lm_models = _fetch_model_ids(s.lmstudio_base_url)
    if lm_models:
        mark = "✓" if s.lmstudio_model in lm_models else "✗ NOT IN LIST"
        print(f"\nLM Studio /models ({len(lm_models)} loaded)")
        print(f"  {s.lmstudio_model}  {mark}")
        if s.lmstudio_model not in lm_models:
            print(f"  Available: {', '.join(lm_models[:8])}")
            print("  Fix: set LMSTUDIO_MODEL to an id above (exact string from LM Studio).")
    else:
        print("\nLM Studio: not reachable or no models loaded")

    ol_models = _fetch_model_ids(s.ollama_base_url, "ollama")
    if ol_models:
        mark = "✓" if s.ollama_model in ol_models else "✗ NOT IN LIST"
        print(f"\nOllama /models ({len(ol_models)} available)")
        print(f"  {s.ollama_model}  {mark}")
    else:
        print("\nOllama: not reachable")

    if active_backend.value == "lmstudio" and s.ollama_model != s.lmstudio_model:
        print(
            f"\nNote: OLLAMA_MODEL ({s.ollama_model}) is ignored while "
            f"LOCAL_LLM_BACKEND={s.local_llm_backend.value} resolves to lmstudio."
        )
    print("\nRestart worker after changing .env: kill worker → uv run python scripts/distill/worker.py")


# ── Docker helpers ─────────────────────────────────────────────────────────────

def _docker(action: str) -> None:
    try:
        subprocess.run(["docker", action, "database_postgres_1"], check=True)
        verb = "paused" if action == "pause" else "resumed"
        print(f"Docker containers {verb}.")
    except Exception as exc:
        print(f"Skipping Docker ({action}): {exc}")


# ── Mode commands ──────────────────────────────────────────────────────────────

def cmd_dev() -> None:
    print("Developer mode: freeing RAM and pausing heavy containers...")
    _docker("pause")
    toggle_local_llm("unload")


def cmd_compile() -> None:
    print("Compilation mode: loading model and resuming containers...")
    _docker("unpause")
    toggle_local_llm("load")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    if cmd == "init":
        cmd_init()
    elif cmd == "status":
        cmd_status()
    elif cmd == "list":
        cmd_list()
    elif cmd == "db":
        cmd_db(args[1] if len(args) > 1 else "")
    elif cmd == "cloud":
        cmd_cloud(args[1] if len(args) > 1 else "")
    elif cmd == "dev":
        cmd_dev()
    elif cmd == "compile":
        cmd_compile()
    elif cmd == "llm":
        cmd_llm()
    else:
        print(f"Unknown command: {cmd}\n{__doc__}")
        sys.exit(1)


if __name__ == "__main__":
    main()
