import pytest
from pathlib import Path


def test_module_not_exists_initially(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import module_exists
    init_db()
    assert not module_exists("auth/session")


def test_create_module_writes_file(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import create_module, module_exists
    init_db()
    create_module("auth/session", "## Overview\n\nHandles sessions.", summary="Session management")
    assert module_exists("auth/session")
    import scripts.config as cfg
    wiki_dir = Path(cfg.get_settings().wiki_dir)
    assert (wiki_dir / "auth" / "session.md").exists()


def test_create_module_sets_frontmatter(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import create_module, read_module
    init_db()
    create_module("auth/session", "## Overview\n\nHandles sessions.")
    post = read_module("auth/session")
    assert post["module"] == "auth/session"
    assert "last_updated" in post.metadata
    assert isinstance(post["recent_prs"], list)
    assert isinstance(post["slack_threads"], list)


def test_append_to_section_adds_content(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import create_module, append_to_section, read_module
    init_db()
    create_module(
        "api/users",
        "## Overview\n\nUser API.\n\n## Recent Changes\n\n## Known Issues\n\n## Related Modules\n",
    )
    append_to_section("api/users", "Recent Changes", "- Added pagination support", "#101")
    post = read_module("api/users")
    assert "pagination" in post.content
    assert "#101" in post["recent_prs"]


def test_append_to_section_stores_recent_events_metadata(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import create_module, append_to_section, read_module
    init_db()
    create_module(
        "api/users",
        "## Overview\n\nUser API.\n\n## Recent Changes\n\n## Known Issues\n\n## Related Modules\n",
    )
    append_to_section(
        "api/users",
        "Recent Changes",
        "- Added issue triage automation",
        "#202",
        source_meta={
            "platform": "github",
            "event_type": "issue_comment",
            "ref": "#202",
            "url": "https://github.com/owner/repo/issues/202#issuecomment-1",
            "actor": "alice",
            "issue_number": 202,
            "occurred_at": "2026-06-02 08:33:30",
        },
    )
    post = read_module("api/users")
    recent_events = post.get("recent_events", [])
    assert isinstance(recent_events, list)
    assert len(recent_events) == 1
    evt = recent_events[0]
    assert evt["platform"] == "github"
    assert evt["event_type"] == "issue_comment"
    assert evt["ref"] == "#202"
    assert evt["actor"] == "alice"


def test_append_updates_last_updated(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import create_module, append_to_section, read_module
    init_db()
    create_module("api/users", "## Recent Changes\n\n")
    append_to_section("api/users", "Recent Changes", "- fix: null pointer", "#99")
    post = read_module("api/users")
    assert post["last_updated"] != ""


def test_update_frontmatter(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import create_module, update_frontmatter, read_module
    init_db()
    create_module("auth/session", "## Overview\n\n")
    update_frontmatter("auth/session", {"tags": ["auth", "redis"], "owners": ["alice"]})
    post = read_module("auth/session")
    assert "redis" in post["tags"]
    assert "alice" in post["owners"]


def test_read_nonexistent_module_returns_none(tmp_db):
    from scripts.db import init_db
    from scripts.wiki.manager import read_module
    init_db()
    assert read_module("does/not/exist") is None
