#!/usr/bin/env python3
"""
PulseWiki resource manager.

Commands:
  init              Initialise the SQLite database
  status            Show pipeline queue health
  list              List all indexed wiki modules
  paths             Show wiki content root, targets, and active resolved path
  legacy-run-once   Process one pending event with the legacy realtime pipeline
  etl-status        Show ETL hot-table status for daytime testing
  etl-run <stage>   Run etl stage: clean|route|distill|all [--apply] [--limit N] [--from-staging]
  etl-replay        Replay ETL all-stage on a time window: --since ... --until ... [--apply] [--limit N]
    etl-archive       Soft-archive completed ETL staging rows older than N hours
  etl-prune         Archive/prune completed ETL staging rows older than N hours
  etl-loop          Adaptive ETL loop wrapper with backpressure-aware throttling
  db on|off         Toggle USE_LOCAL_DB (on=SQLite, off=DATABASE_URL)
  cloud on|off      Toggle USE_CLOUD_LLM (on=cloud for new pages, off=all local)
  pipeline <mode>   Set PIPELINE_MODE to legacy|etl|compare
  target <name>     Set WIKI_WRITE_TARGET to legacy|etl
  dev               Dev mode: pause Docker containers, unload local model from RAM
  compile           Compile mode: resume Docker containers, load local model into RAM
  llm               Show which models .env selects vs what LM Studio/Ollama expose
"""
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.config import get_settings


# -- PulseWiki commands --------------------------------------------------------

def _ensure_db_schema() -> None:
    from scripts.db import init_db

    init_db()


def cmd_init() -> None:
    from scripts.db import init_db

    init_db()
    print("Database initialized.")


def cmd_status() -> None:
    from scripts.db import get_connection, get_pipeline_status

    _ensure_db_schema()
    s = get_pipeline_status()
    cfg = get_settings()
    with get_connection() as conn:
        module_count = conn.execute("SELECT COUNT(*) FROM modules").fetchone()[0]
    print(f"Pending : {s['pending']}")
    print(f"Failed  : {s['failed']}")
    print(f"Last run: {s['last_processed'] or 'never'}")
    print(f"Modules : {module_count}")
    print(f"Mode    : {cfg.pipeline_mode.value}")
    print(f"Target  : {cfg.wiki_write_target.value}")
    print(f"Wiki dir: {cfg.resolved_wiki_dir}")


def cmd_list() -> None:
    from scripts.db import get_connection

    _ensure_db_schema()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT path, summary, last_updated FROM modules ORDER BY path"
        ).fetchall()
    if not rows:
        print("No modules indexed yet.")
        return
    for row in rows:
        print(f"  {row['path']:<40} {row['last_updated'] or '—'}")
        if row["summary"]:
            print(f"    {row['summary'][:80]}")


def cmd_paths() -> None:
    s = get_settings()
    print(f"Content root : {s.wiki_content_dir}")
    print(f"Legacy dir   : {s.legacy_wiki_dir}")
    print(f"ETL dir      : {s.etl_wiki_dir}")
    print(f"Mode         : {s.pipeline_mode.value}")
    print(f"Write target : {s.wiki_write_target.value}")
    print(f"Resolved dir : {s.resolved_wiki_dir}")
    if s.wiki_dir:
        print("Override     : WIKI_DIR is set explicitly and takes precedence over write target")


def cmd_legacy_run_once() -> None:
    from scripts.db import get_pending_events, mark_event_processing
    from scripts.distill.worker import process_event_legacy

    _ensure_db_schema()

    events = get_pending_events(limit=1)
    if not events:
        print("No pending events for legacy pipeline.")
        return
    event = events[0]
    mark_event_processing(event["id"])
    process_event_legacy(event)
    print(f"Legacy processed event #{event['id']}")


def cmd_etl_status() -> None:
    from scripts.db import get_pending_events_count, get_staging_status_counts

    _ensure_db_schema()

    pending = get_pending_events_count()
    staging_counts = get_staging_status_counts(hot_only=True)
    cfg = get_settings()
    print(f"Pipeline mode : {cfg.pipeline_mode.value}")
    print(f"Write target  : {cfg.wiki_write_target.value}")
    print(f"Resolved dir  : {cfg.resolved_wiki_dir}")
    print(f"Pending events: {pending}")
    if not staging_counts:
        print("Staging      : empty")
    else:
        print("Staging      :")
        for key in sorted(staging_counts.keys()):
            print(f"  - {key:<20} {staging_counts[key]}")


def _parse_positive_int(args: list[str], flag: str, default: int) -> int:
    if flag not in args:
        return default
    idx = args.index(flag)
    if idx + 1 >= len(args):
        print(f"Usage: {flag} <positive-int>")
        sys.exit(1)
    try:
        value = int(args[idx + 1])
    except ValueError:
        print(f"{flag} must be an integer")
        sys.exit(1)
    if value <= 0:
        print(f"{flag} must be > 0")
        sys.exit(1)
    return value


def _parse_limit(args: list[str], default: int = 10) -> int:
    if "--limit" not in args:
        return default
    idx = args.index("--limit")
    if idx + 1 >= len(args):
        print("Usage: resource_mgr.py etl-run <stage> [--apply] [--limit N]")
        sys.exit(1)
    try:
        return int(args[idx + 1])
    except ValueError:
        print("--limit must be an integer")
        sys.exit(1)


def _parse_window(args: list[str]) -> tuple[str | None, str | None]:
    since = None
    until = None
    if "--since" in args:
        idx = args.index("--since")
        if idx + 1 >= len(args):
            print("Usage: --since 'YYYY-MM-DD HH:MM:SS'")
            sys.exit(1)
        since = args[idx + 1]
    if "--until" in args:
        idx = args.index("--until")
        if idx + 1 >= len(args):
            print("Usage: --until 'YYYY-MM-DD HH:MM:SS'")
            sys.exit(1)
        until = args[idx + 1]
    return since, until


def cmd_etl_run(stage: str, args: list[str]) -> None:
    if stage not in ("clean", "route", "distill", "all"):
        print("Usage: resource_mgr.py etl-run clean|route|distill|all [--apply] [--limit N] [--from-staging]")
        sys.exit(1)

    dry_run = "--apply" not in args
    limit = _parse_limit(args, default=10)
    since, until = _parse_window(args)
    from_staging = "--from-staging" in args

    _ensure_db_schema()

    from scripts.distill.worker import (
        clean_batch,
        distill_batch,
        route_batch,
        run_etl_once_with_cleanup,
    )

    if stage == "clean":
        cleaned = clean_batch(limit=limit, dry_run=dry_run, since=since, until=until)
        print(f"ETL clean: {len(cleaned)} item(s) {'[dry-run]' if dry_run else '[apply]'}")
        return

    if stage == "route":
        cleaned = None if from_staging else clean_batch(limit=limit, dry_run=dry_run, since=since, until=until)
        routed = route_batch(cleaned, dry_run=dry_run, limit=limit)
        source = "staging" if from_staging else "clean"
        print(f"ETL route: {len(routed)} route(s) {'[dry-run]' if dry_run else '[apply]'} [source={source}]")
        return

    if stage == "distill":
        if from_staging:
            routed = None
        else:
            cleaned = clean_batch(limit=limit, dry_run=dry_run, since=since, until=until)
            routed = route_batch(cleaned, dry_run=dry_run, limit=limit)
        results = distill_batch(routed, dry_run=dry_run, limit=limit)
        source = "staging" if from_staging else "route"
        print(f"ETL distill: {len(results)} action(s) {'[dry-run]' if dry_run else '[apply]'} [source={source}]")
        return

    cleanup_hours = _parse_positive_int(args, "--cleanup-hours", 24)
    cleanup_mode = "archive"
    if "--cleanup-mode" in args:
        idx = args.index("--cleanup-mode")
        if idx + 1 >= len(args):
            print("Usage: --cleanup-mode archive|prune")
            sys.exit(1)
        cleanup_mode = args[idx + 1].strip().lower()
    if cleanup_mode not in {"archive", "prune"}:
        print("Usage: --cleanup-mode archive|prune")
        sys.exit(1)

    summary = run_etl_once_with_cleanup(
        limit=limit,
        dry_run=dry_run,
        since=since,
        until=until,
        cleanup_hours=cleanup_hours,
        cleanup_mode=cleanup_mode,
    )
    print(
        "ETL all: "
        f"cleaned={summary['cleaned']} "
        f"routed={summary['routed']} "
        f"distilled={summary['distilled']} "
        f"archived_or_pruned={summary.get('archived_or_pruned', 0)} "
        f"{'[dry-run]' if dry_run else '[apply]'}"
    )


def cmd_etl_replay(args: list[str]) -> None:
    since, until = _parse_window(args)
    if not since or not until:
        print("Usage: resource_mgr.py etl-replay --since 'YYYY-MM-DD HH:MM:SS' --until 'YYYY-MM-DD HH:MM:SS' [--apply] [--limit N]")
        sys.exit(1)
    limit = _parse_limit(args, default=200)
    dry_run = "--apply" not in args

    _ensure_db_schema()

    from scripts.distill.worker import run_etl_once_with_cleanup

    cleanup_hours = _parse_positive_int(args, "--cleanup-hours", 24)
    cleanup_mode = "archive"
    if "--cleanup-mode" in args:
        idx = args.index("--cleanup-mode")
        if idx + 1 >= len(args):
            print("Usage: --cleanup-mode archive|prune")
            sys.exit(1)
        cleanup_mode = args[idx + 1].strip().lower()

    summary = run_etl_once_with_cleanup(
        limit=limit,
        dry_run=dry_run,
        since=since,
        until=until,
        cleanup_hours=cleanup_hours,
        cleanup_mode=cleanup_mode,
    )
    print(
        "ETL replay: "
        f"window=[{since} -> {until}] "
        f"cleaned={summary['cleaned']} "
        f"routed={summary['routed']} "
        f"distilled={summary['distilled']} "
        f"archived_or_pruned={summary.get('archived_or_pruned', 0)} "
        f"{'[dry-run]' if dry_run else '[apply]'}"
    )


def cmd_etl_prune(args: list[str]) -> None:
    from scripts.db import etl_archive_or_prune

    _ensure_db_schema()

    hours = _parse_positive_int(args, "--hours", 24)
    mode = "archive"
    if "--mode" in args:
        idx = args.index("--mode")
        if idx + 1 >= len(args):
            print("Usage: --mode archive|prune")
            sys.exit(1)
        mode = args[idx + 1].strip().lower()
    if mode not in {"archive", "prune"}:
        print("Usage: resource_mgr.py etl-prune [--hours N] [--mode archive|prune] [--apply]")
        sys.exit(1)

    dry_run = "--apply" not in args
    count = etl_archive_or_prune(older_than_hours=hours, mode=mode, dry_run=dry_run)
    action = "Would move/delete" if dry_run else "Moved/deleted"
    print(f"{action} {count} completed staging row(s) older than {hours}h [mode={mode}] {'[dry-run]' if dry_run else '[apply]'}")


def cmd_etl_archive(args: list[str]) -> None:
        """Alias for etl-prune in archive mode.

        Usage:
            resource_mgr.py etl-archive [--hours N] [--apply]
        """
        forwarded = ["--mode", "archive", *args]
        cmd_etl_prune(forwarded)


def cmd_etl_loop(args: list[str]) -> None:
    from scripts.db import (
        get_inflight_staging_count,
        get_pending_events_count,
        get_recent_failed_staging_count,
    )
    from scripts.distill.worker import run_etl_once_with_cleanup

    _ensure_db_schema()

    dry_run = "--apply" not in args
    max_limit = _parse_positive_int(args, "--limit", 50)
    min_limit = _parse_positive_int(args, "--min-limit", 10)
    min_sleep = _parse_positive_int(args, "--min-sleep", 5)
    base_sleep = _parse_positive_int(args, "--base-sleep", 30)
    max_sleep = _parse_positive_int(args, "--max-sleep", 180)
    max_inflight = _parse_positive_int(args, "--max-inflight", 8)
    fail_window_mins = _parse_positive_int(args, "--fail-window", 15)
    cleanup_hours = _parse_positive_int(args, "--cleanup-hours", 24)

    cleanup_mode = "archive"
    if "--cleanup-mode" in args:
        idx = args.index("--cleanup-mode")
        if idx + 1 >= len(args):
            print("Usage: --cleanup-mode archive|prune")
            sys.exit(1)
        cleanup_mode = args[idx + 1].strip().lower()
    if cleanup_mode not in {"archive", "prune"}:
        print("Usage: --cleanup-mode archive|prune")
        sys.exit(1)

    print(
        f"ETL loop started {'[dry-run]' if dry_run else '[apply]'} "
        f"max_limit={max_limit} base_sleep={base_sleep}s max_inflight={max_inflight}"
    )

    failure_streak = 0
    while True:
        pending = get_pending_events_count()
        inflight = get_inflight_staging_count()
        recent_failed = get_recent_failed_staging_count(minutes=fail_window_mins)

        if inflight >= max_inflight:
            sleep_secs = min(max_sleep, max(base_sleep, min_sleep * 2))
            print(
                f"ETL loop skipped [reason=backpressure] pending={pending} inflight={inflight}/{max_inflight} sleep={sleep_secs}s"
            )
            time.sleep(sleep_secs)
            continue

        if recent_failed > 0:
            failure_streak += 1
            backoff = min(max_sleep, base_sleep * (2 ** min(failure_streak, 6)))
            print(
                (
                    f"ETL loop degraded [recent_failed={recent_failed} window={fail_window_mins}m] "
                    f"streak={failure_streak} backoff={backoff}s"
                ),
                file=sys.stderr,
            )
        else:
            failure_streak = 0
            backoff = base_sleep

        if pending > max_limit * 8:
            batch_limit = max(min_limit, max_limit // 2)
            adaptive_sleep = min_sleep
        elif pending > max_limit * 3:
            batch_limit = max(min_limit, (max_limit * 3) // 4)
            adaptive_sleep = max(min_sleep, base_sleep // 2)
        elif pending == 0:
            batch_limit = min_limit
            adaptive_sleep = min(max_sleep, base_sleep + 10)
        else:
            batch_limit = max_limit
            adaptive_sleep = base_sleep

        sleep_secs = min(max_sleep, max(adaptive_sleep, backoff))

        summary = run_etl_once_with_cleanup(
            limit=batch_limit,
            dry_run=dry_run,
            cleanup_hours=cleanup_hours,
            cleanup_mode=cleanup_mode,
        )
        print(
            "ETL loop cycle: "
            f"cleaned={summary['cleaned']} "
            f"routed={summary['routed']} "
            f"distilled={summary['distilled']} "
            f"archived_or_pruned={summary.get('archived_or_pruned', 0)} "
            f"pending={pending} inflight={inflight} "
            f"limit={batch_limit} sleep={sleep_secs}s "
            f"{'[dry-run]' if dry_run else '[apply]'}"
        )
        time.sleep(sleep_secs)


# -- Database toggle -----------------------------------------------------------

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


# -- Cloud toggle --------------------------------------------------------------

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


def cmd_pipeline(mode: str) -> None:
    if mode not in ("legacy", "etl", "compare"):
        print("Usage: resource_mgr.py pipeline legacy|etl|compare")
        sys.exit(1)
    _update_env_key("PIPELINE_MODE", mode)
    from scripts.config import reload_settings

    reload_settings()
    print(f"Pipeline mode set to {mode}")


def cmd_target(target: str) -> None:
    if target not in ("legacy", "etl"):
        print("Usage: resource_mgr.py target legacy|etl")
        sys.exit(1)
    _update_env_key("WIKI_WRITE_TARGET", target)
    from scripts.config import reload_settings

    reload_settings()
    s = get_settings()
    print(f"Wiki write target set to {target}")
    print(f"Resolved wiki dir: {s.resolved_wiki_dir}")
    if s.wiki_dir:
        print("Note: WIKI_DIR is explicitly set in .env; remove it if you want target switching to take effect.")


# -- Local model memory (Ollama keep_alive / LM Studio warm-up) --------------

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
    from scripts.distill.llm_router import get_active_local_model

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


# -- Docker helpers ------------------------------------------------------------

def _docker(action: str) -> None:
    try:
        subprocess.run(["docker", action, "database_postgres_1"], check=True)
        verb = "paused" if action == "pause" else "resumed"
        print(f"Docker containers {verb}.")
    except Exception as exc:
        print(f"Skipping Docker ({action}): {exc}")


# -- Mode commands -------------------------------------------------------------

def cmd_dev() -> None:
    print("Developer mode: freeing RAM and pausing heavy containers...")
    _docker("pause")
    toggle_local_llm("unload")


def cmd_compile() -> None:
    print("Compilation mode: loading model and resuming containers...")
    _docker("unpause")
    toggle_local_llm("load")


# -- Entry point ---------------------------------------------------------------

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
    elif cmd == "paths":
        cmd_paths()
    elif cmd == "legacy-run-once":
        cmd_legacy_run_once()
    elif cmd == "etl-status":
        cmd_etl_status()
    elif cmd == "etl-run":
        stage = args[1] if len(args) > 1 else ""
        cmd_etl_run(stage, args[2:])
    elif cmd == "etl-replay":
        cmd_etl_replay(args[1:])
    elif cmd == "etl-archive":
        cmd_etl_archive(args[1:])
    elif cmd == "etl-prune":
        cmd_etl_prune(args[1:])
    elif cmd == "etl-loop":
        cmd_etl_loop(args[1:])
    elif cmd == "db":
        cmd_db(args[1] if len(args) > 1 else "")
    elif cmd == "cloud":
        cmd_cloud(args[1] if len(args) > 1 else "")
    elif cmd == "pipeline":
        cmd_pipeline(args[1] if len(args) > 1 else "")
    elif cmd == "target":
        cmd_target(args[1] if len(args) > 1 else "")
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
