"""End-to-end: diff in → worker → wiki module created → MCP search returns it."""
import json
from unittest.mock import patch


def test_full_pipeline(tmp_db):
    from scripts.db import init_db, push_event, get_pending_events
    from scripts.distill.worker import process_event
    from scripts.wiki.manager import module_exists, read_module
    from scripts.mcp_server import search_wiki, get_module
    init_db()

    diff = "+def authenticate(user, token):\n+    return validate_token(token)"
    raw_json = json.dumps({
        "pr_number": 99,
        "title": "Add token authentication",
        "description": "Implements JWT authentication for the auth module",
        "diff": diff,
    })
    push_event("github", "pr", raw_json)
    event = get_pending_events()[0]

    with patch("scripts.distill.worker.call_llm") as mock_llm:
        mock_llm.side_effect = [
            '["auth/token"]',
            '{"summary": "Added JWT authentication", "change_type": "feature", "affected_components": ["auth"], "key_decisions": ["use JWT"]}',
            "## Overview\n\nHandles JWT token validation.\n\n## Recent Changes\n\n## Known Issues\n\n## Related Modules\n",
        ]
        process_event(event)

    assert module_exists("auth/token")
    post = read_module("auth/token")
    assert "JWT" in post.content

    search_results = search_wiki("token authentication")
    assert any(r["module"] == "auth/token" for r in search_results)

    full = get_module("auth/token")
    assert "auth/token" in full
