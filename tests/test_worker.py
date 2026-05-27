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
