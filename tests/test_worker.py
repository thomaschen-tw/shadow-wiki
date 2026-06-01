import json
import pytest
from unittest.mock import patch


def test_process_event_creates_new_module(tmp_db):
    from scripts.db import init_db, push_event, get_pending_events
    from scripts.wiki.manager import module_exists
    init_db()

    raw = json.dumps({"pr_number": 42, "title": "Add login flow", "description": "New OAuth", "diff": "+"})
    eid = push_event("github", "pr", raw)

    event = get_pending_events()[0]

    with patch("scripts.distill.worker.call_llm") as mock_llm, \
         patch("scripts.distill.worker.module_exists", return_value=False), \
         patch("scripts.distill.worker.create_module") as mock_create, \
         patch("scripts.distill.worker.mark_event_done") as mock_done:
        mock_llm.side_effect = [
            '["api/auth"]',          # CLASSIFY
            '{"summary": "Add OAuth login", "change_type": "feature", "affected_components": [], "key_decisions": []}',  # SUMMARIZE
            "## Overview\n\nNew module.",  # CREATE_PAGE
        ]
        from scripts.distill.worker import process_event
        process_event(event)

    mock_create.assert_called_once()
    assert mock_create.call_args[0][0] == "api/auth"
    mock_done.assert_called_once_with(event["id"])


def test_process_event_appends_to_existing_module(tmp_db):
    from scripts.db import init_db, push_event, get_pending_events
    from scripts.wiki.manager import create_module
    init_db()

    create_module("api/auth", "## Overview\n\n## Recent Changes\n\n## Known Issues\n\n## Related Modules\n")
    raw = json.dumps({"pr_number": 43, "title": "Fix token expiry", "description": "Fix bug", "diff": "-bug\n+fix"})
    push_event("github", "pr", raw)
    event = get_pending_events()[0]

    with patch("scripts.distill.worker.call_llm") as mock_llm, \
         patch("scripts.distill.worker.mark_event_done"):
        mock_llm.side_effect = [
            '["api/auth"]',
            '{"summary": "Fix token expiry", "change_type": "fix", "affected_components": [], "key_decisions": []}',
            "- Fixed token expiry race condition",
        ]
        from scripts.distill.worker import process_event
        process_event(event)

    from scripts.wiki.manager import read_module
    post = read_module("api/auth")
    assert "token expiry" in post.content.lower() or "Fixed" in post.content


def test_process_event_marks_failed_on_error(tmp_db):
    from scripts.db import init_db, push_event, get_pending_events, get_connection
    init_db()

    push_event("github", "pr", '{"pr_number": 1, "diff": "x"}')
    event = get_pending_events()[0]

    with patch("scripts.distill.worker.call_llm", side_effect=RuntimeError("LLM down")):
        from scripts.distill.worker import process_event
        process_event(event)

    with get_connection() as conn:
        row = conn.execute("SELECT status FROM events WHERE id=?", (event["id"],)).fetchone()
    assert row["status"] == "failed"


def test_handle_review_event_appends_to_existing_module(tmp_db):
    from scripts.db import init_db, push_event, get_pending_events
    from scripts.wiki.manager import create_module, read_module
    init_db()

    create_module("api/auth", "## Overview\n\n## Recent Changes\n\n## Known Issues\n\n## Related Modules\n")
    raw = json.dumps({
        "pr_number": 20,
        "title": "Add OAuth",
        "reviewer": "alice",
        "state": "APPROVED",
        "body": "LGTM, ship it",
        "url": "https://github.com/owner/repo/pull/20#review-1",
    })
    push_event("github", "pr_review", raw)
    event = get_pending_events()[0]

    with patch("scripts.distill.worker.call_llm") as mock_llm, \
         patch("scripts.distill.worker.mark_event_done"):
        mock_llm.side_effect = [
            '["api/auth"]',                 # CLASSIFY
            "- Approved by alice: LGTM",    # APPEND (review synthesis)
        ]
        from scripts.distill.worker import process_event
        process_event(event)

    post = read_module("api/auth")
    assert "## Recent Changes" in post.content
    assert "alice" in post.content or "Approved" in post.content


def test_handle_review_event_skips_missing_module(tmp_db):
    from scripts.db import init_db, push_event, get_pending_events
    init_db()

    raw = json.dumps({"pr_number": 21, "title": "Fix X", "reviewer": "bob", "state": "CHANGES_REQUESTED", "body": "Needs tests"})
    push_event("github", "pr_review", raw)
    event = get_pending_events()[0]

    with patch("scripts.distill.worker.call_llm") as mock_llm, \
         patch("scripts.distill.worker.mark_event_done"):
        mock_llm.side_effect = [
            '["nonexistent/module"]',
            "- Needs tests",
        ]
        from scripts.distill.worker import process_event
        process_event(event)  # should not raise


def test_count_section_entries(tmp_db):
    from scripts.distill.worker import _count_section_entries

    content = (
        "## Overview\n\nSome text.\n\n"
        "## Recent Changes\n\n"
        "### 2026-01-01 (#1)\n\n- change one\n\n"
        "### 2026-01-02 (#2)\n\n- change two\n\n"
        "## Known Issues\n\n"
        "### 2026-01-03\n\n- issue one\n"
    )
    assert _count_section_entries(content, "Recent Changes") == 2
    assert _count_section_entries(content, "Known Issues") == 1
    assert _count_section_entries(content, "Runbooks") == 0


def test_synthesis_triggered_at_threshold(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import create_module, read_module
    from scripts.distill.worker import _maybe_synthesize
    init_db()

    body = (
        "## Overview\n\nOriginal overview.\n\n"
        "## Recent Changes\n\n"
        + "".join(f"### 2026-01-0{i} (#{ i})\n\n- change {i}\n\n" for i in range(1, 6))
    )
    create_module("api/auth", body)

    with patch("scripts.distill.worker.call_llm", return_value="Updated synthesis."):
        _maybe_synthesize("api/auth", read_module("api/auth").content)

    post = read_module("api/auth")
    assert "Updated synthesis." in post.content


def test_runbook_generated_when_known_issues_threshold_met(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import create_module, read_module
    from scripts.distill.worker import _maybe_generate_runbook
    init_db()

    body = (
        "## Overview\n\n## Recent Changes\n\n"
        "## Known Issues\n\n"
        "### 2026-01-01\n\n- Issue A\n\n"
        "### 2026-01-02\n\n- Issue B\n\n"
        "## Related Modules\n"
    )
    create_module("api/auth", body)

    with patch("scripts.distill.worker.call_llm", return_value="1. Run migration\n2. Restart service"):
        _maybe_generate_runbook("api/auth", read_module("api/auth").content)

    post = read_module("api/auth")
    assert "## Runbooks" in post.content
    assert "Run migration" in post.content
