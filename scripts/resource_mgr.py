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
    import scripts.config as cfg
    cfg._settings = None
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
    import scripts.config as cfg
    cfg._settings = None
    label = "enabled" if state == "on" else "disabled"
    print(f"Cloud LLM {label}  (USE_CLOUD_LLM={value})")


# ── Ollama model memory management ────────────────────────────────────────────

def _local_model_name() -> str:
    s = get_settings()
    return s.ollama_model if s.local_llm_backend.value == "ollama" else s.lmstudio_model


def toggle_local_llm(action: str) -> None:
    model = _local_model_name()
    keep_alive = -1 if action == "load" else 0
    payload = {
        "model": model,
        "messages": [],
        "keep_alive": keep_alive,
    }
    try:
        resp = httpx.post("http://localhost:11434/api/chat", json=payload, timeout=5)
        if resp.status_code == 200:
            state = "loaded" if keep_alive == -1 else "released"
            print(f"Model '{model}' {state} in Apple Unified Memory.")
        else:
            print(f"Ollama returned HTTP {resp.status_code}")
    except Exception as exc:
        print(f"Could not reach Ollama: {exc}")


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
    else:
        print(f"Unknown command: {cmd}\n{__doc__}")
        sys.exit(1)


if __name__ == "__main__":
    main()
