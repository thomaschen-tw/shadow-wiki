import json
import pytest


def test_init_creates_tables(tmp_db):
    from scripts.db import init_db, get_connection
    init_db()
    with get_connection() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "events" in tables
    assert "modules" in tables


def test_push_event_returns_id(tmp_db):
    from scripts.db import init_db, push_event
    init_db()
    event_id = push_event("github", "pr", '{"pr_number": 42}')
    assert isinstance(event_id, int)
    assert event_id > 0


def test_get_pending_events(tmp_db):
    from scripts.db import init_db, push_event, get_pending_events
    init_db()
    push_event("github", "pr", '{"pr_number": 1}')
    push_event("slack", "message", '{"body": "hello"}')
    events = get_pending_events(limit=10)
    assert len(events) == 2
    assert events[0]["source"] == "github"


def test_mark_event_done_removes_from_pending(tmp_db):
    from scripts.db import init_db, push_event, get_pending_events, mark_event_done
    init_db()
    eid = push_event("github", "pr", "{}")
    mark_event_done(eid)
    assert len(get_pending_events()) == 0


def test_mark_event_failed_stores_error(tmp_db):
    from scripts.db import init_db, push_event, mark_event_failed, get_connection
    init_db()
    eid = push_event("github", "pr", "{}")
    mark_event_failed(eid, "LLM timeout")
    with get_connection() as conn:
        row = conn.execute("SELECT status, error FROM events WHERE id=?", (eid,)).fetchone()
    assert row["status"] == "failed"
    assert row["error"] == "LLM timeout"


def test_upsert_module_and_retrieve(tmp_db):
    from scripts.db import init_db, upsert_module, get_connection
    init_db()
    upsert_module("auth/session", "wiki_content/legacy/auth/session.md", "Handles session tokens")
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM modules WHERE path='auth/session'").fetchone()
    assert row["summary"] == "Handles session tokens"
    assert row["file_path"] == "wiki_content/legacy/auth/session.md"


def test_upsert_module_idempotent(tmp_db):
    from scripts.db import init_db, upsert_module, get_connection
    init_db()
    upsert_module("auth/session", "wiki_content/legacy/auth/session.md", "v1")
    upsert_module("auth/session", "wiki_content/legacy/auth/session.md", "v2")
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM modules").fetchone()[0]
    assert count == 1


def test_fts_search_returns_results(tmp_db):
    from scripts.db import init_db, update_fts, search_modules_fts
    init_db()
    update_fts("auth/session", "This module handles Redis session token refresh with retry logic")
    results = search_modules_fts("session token")
    assert len(results) > 0
    assert results[0]["module_path"] == "auth/session"


def test_pipeline_status(tmp_db):
    from scripts.db import init_db, push_event, mark_event_done, get_pipeline_status
    init_db()
    eid = push_event("github", "pr", "{}")
    status = get_pipeline_status()
    assert status["pending"] == 1
    assert status["failed"] == 0
    mark_event_done(eid)
    status = get_pipeline_status()
    assert status["pending"] == 0


def test_get_events_in_window(tmp_db):
    from scripts.db import init_db, push_event, get_events_in_window
    init_db()
    push_event("github", "pr", "{}")
    rows = get_events_in_window("2000-01-01 00:00:00", "2100-01-01 00:00:00", limit=10)
    assert len(rows) == 1


def test_etl_staging_roundtrip(tmp_db):
    from scripts.db import (
        init_db,
        push_event,
        push_staging,
        mark_staging_processing,
        mark_staging_done,
        get_staging_records,
        get_staging_status_counts,
    )
    init_db()
    event_id = push_event("github", "pr", '{"title": "x"}')
    staging_id = push_staging(event_id, "clean", input_json='{"title": "x"}', status="pending")
    mark_staging_processing(staging_id)
    mark_staging_done(staging_id, output_json='{"normalized": true}')

    rows = get_staging_records("clean", status="done", limit=10)
    assert len(rows) == 1
    assert rows[0]["event_id"] == event_id
    assert "normalized" in rows[0]["output_json"]

    counts = get_staging_status_counts()
    assert counts["clean:done"] == 1


def test_has_staging_record(tmp_db):
    from scripts.db import init_db, push_event, push_staging, mark_staging_done, has_staging_record

    init_db()
    event_id = push_event("github", "pr", '{"title": "x"}')
    staging_id = push_staging(event_id, "route", input_json="{}", status="processing")
    mark_staging_done(staging_id, output_json='{"ok": true}')

    assert has_staging_record(event_id, "route", status="done") is True
    assert has_staging_record(event_id, "distill", status="done") is False
