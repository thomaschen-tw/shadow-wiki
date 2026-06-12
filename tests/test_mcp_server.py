import json
import pytest


def test_search_wiki_returns_results(tmp_db):
    from scripts.db import init_db, update_fts, upsert_module
    init_db()
    upsert_module("auth/session", "wiki_content/legacy/auth/session.md", "Session handling")
    update_fts("auth/session", "This module handles Redis session token refresh")

    from scripts.mcp_server import search_wiki
    results = search_wiki("session token")
    assert len(results) > 0
    assert results[0]["module"] == "auth/session"


def test_get_module_returns_content(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import create_module
    init_db()
    create_module("auth/session", "## Overview\n\nHandles sessions.", "Session module")

    from scripts.mcp_server import get_module
    content = get_module("auth/session")
    assert "Overview" in content
    assert "auth/session" in content


def test_get_module_not_found(tmp_db):
    from scripts.db import init_db
    init_db()
    from scripts.mcp_server import get_module
    result = get_module("does/not/exist")
    assert "not found" in result.lower()


def test_list_modules_returns_all(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import create_module
    init_db()
    create_module("auth/session", "## Overview\n\n", "Session module")
    create_module("api/users", "## Overview\n\n", "Users API")

    from scripts.mcp_server import list_modules
    modules = list_modules()
    paths = [m["path"] for m in modules]
    assert "auth/session" in paths
    assert "api/users" in paths


def test_get_pipeline_status_tool(tmp_db):
    from scripts.db import init_db, push_event
    init_db()
    push_event("github", "pr", "{}")
    from scripts.mcp_server import get_pipeline_status_tool
    status = get_pipeline_status_tool()
    assert status["pending"] == 1


def test_update_module_appends_section(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import create_module, read_module
    init_db()
    create_module("api/users", "## Overview\n\n## Known Issues\n\n")

    from scripts.mcp_server import update_module
    result = update_module("api/users", "Known Issues", "- Rate limiting not implemented")
    assert result["status"] == "ok"
    post = read_module("api/users")
    assert "Rate limiting" in post.content


def test_get_recent_changes_returns_done_events(tmp_db):
    from scripts.db import init_db, push_event, mark_event_done
    init_db()
    eid = push_event("github", "pr", '{"title": "Fix session bug"}')
    mark_event_done(eid)

    from scripts.mcp_server import get_recent_changes
    results = get_recent_changes("1d")
    assert len(results) == 1
    assert results[0]["source"] == "github"
    assert results[0]["title"] == "Fix session bug"


def test_get_recent_changes_invalid_format(tmp_db):
    from scripts.db import init_db
    init_db()
    from scripts.mcp_server import get_recent_changes
    results = get_recent_changes("bad-format")
    assert len(results) == 1
    assert "error" in results[0]


def test_get_runbooks_returns_section(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import create_module, append_to_section
    init_db()
    create_module("api/users", "## Overview\n\n## Known Issues\n\n## Runbooks\n\n### 2026-06-01\n\n1. Restart the worker.\n")

    from scripts.mcp_server import get_runbooks
    result = get_runbooks("api/users")
    assert "Runbooks" in result
    assert "Restart the worker" in result


def test_get_runbooks_missing_section(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import create_module
    init_db()
    create_module("api/users", "## Overview\n\n## Known Issues\n\n")

    from scripts.mcp_server import get_runbooks
    result = get_runbooks("api/users")
    assert "No runbook yet" in result


def test_get_runbooks_module_not_found(tmp_db):
    from scripts.db import init_db
    init_db()
    from scripts.mcp_server import get_runbooks
    result = get_runbooks("does/not/exist")
    assert "not found" in result.lower()
