import json
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


def test_webhook_rejects_bad_signature(tmp_db, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")
    import scripts.config as cfg
    cfg._settings = None
    from scripts.db import init_db
    init_db()

    from scripts.ingest.github_connector import app
    client = TestClient(app)
    response = client.post(
        "/webhook/github",
        content=json.dumps({"action": "opened"}),
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=bad",
        },
    )
    assert response.status_code == 403


def test_webhook_accepts_pr_opened(tmp_db, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    import scripts.config as cfg
    cfg._settings = None
    from scripts.db import init_db, get_pending_events
    init_db()

    from scripts.ingest.github_connector import app
    client = TestClient(app)

    payload = {
        "action": "opened",
        "pull_request": {
            "number": 55,
            "title": "Add caching layer",
            "body": "Adds Redis cache",
            "user": {"login": "alice"},
            "html_url": "https://github.com/owner/repo/pull/55",
            "merged": False,
            "url": "https://api.github.com/repos/owner/repo/pulls/55",
        },
    }
    with patch("scripts.ingest.github_connector.fetch_pr_diff", return_value="@@ diff @@"):
        response = client.post(
            "/webhook/github",
            content=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
            },
        )
    assert response.status_code == 200
    events = get_pending_events()
    assert len(events) == 1
    raw = json.loads(events[0]["raw_json"])
    assert raw["pr_number"] == 55


def test_webhook_ignores_unsupported_events(tmp_db, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    import scripts.config as cfg
    cfg._settings = None
    from scripts.db import init_db, get_pending_events
    init_db()

    from scripts.ingest.github_connector import app
    client = TestClient(app)
    response = client.post(
        "/webhook/github",
        content=json.dumps({}),
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "push",
        },
    )
    assert response.status_code == 200
    assert len(get_pending_events()) == 0


def test_webhook_queues_pr_review(tmp_db, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    import scripts.config as cfg
    cfg._settings = None
    from scripts.db import init_db, get_pending_events
    init_db()

    from scripts.ingest.github_connector import app
    client = TestClient(app)

    payload = {
        "action": "submitted",
        "pull_request": {"number": 10, "title": "Add auth"},
        "review": {
            "user": {"login": "reviewer1"},
            "state": "APPROVED",
            "body": "LGTM",
            "html_url": "https://github.com/owner/repo/pull/10#pullrequestreview-1",
        },
    }
    response = client.post(
        "/webhook/github",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json", "X-GitHub-Event": "pull_request_review"},
    )
    assert response.status_code == 200
    events = get_pending_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "pr_review"
    raw = json.loads(events[0]["raw_json"])
    assert raw["reviewer"] == "reviewer1"
    assert raw["state"] == "APPROVED"
    assert raw["pr_number"] == 10


def test_webhook_queues_pr_review_comment(tmp_db, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    import scripts.config as cfg
    cfg._settings = None
    from scripts.db import init_db, get_pending_events
    init_db()

    from scripts.ingest.github_connector import app
    client = TestClient(app)

    payload = {
        "action": "created",
        "pull_request": {"number": 11, "title": "Fix bug"},
        "comment": {
            "user": {"login": "alice"},
            "body": "Why is this not using a constant?",
            "path": "src/auth.py",
            "diff_hunk": "@@ -10,3 +10,3 @@",
            "html_url": "https://github.com/owner/repo/pull/11#comment-1",
        },
    }
    response = client.post(
        "/webhook/github",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json", "X-GitHub-Event": "pull_request_review_comment"},
    )
    assert response.status_code == 200
    events = get_pending_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "review_comment"
    raw = json.loads(events[0]["raw_json"])
    assert raw["author"] == "alice"
    assert raw["path"] == "src/auth.py"


def test_webhook_queues_issue_comment_on_pr(tmp_db, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    import scripts.config as cfg
    cfg._settings = None
    from scripts.db import init_db, get_pending_events
    init_db()

    from scripts.ingest.github_connector import app
    client = TestClient(app)

    payload = {
        "action": "created",
        "issue": {
            "number": 12,
            "title": "Deploy caching",
            "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/12"},
        },
        "comment": {
            "user": {"login": "bob"},
            "body": "Should we also update the docs?",
            "html_url": "https://github.com/owner/repo/pull/12#issuecomment-1",
        },
    }
    response = client.post(
        "/webhook/github",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json", "X-GitHub-Event": "issue_comment"},
    )
    assert response.status_code == 200
    events = get_pending_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "pr_comment"
    raw = json.loads(events[0]["raw_json"])
    assert raw["user"] == "bob"
    assert raw["pr_number"] == 12


def test_webhook_ignores_issue_comment_on_plain_issue(tmp_db, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    import scripts.config as cfg
    cfg._settings = None
    from scripts.db import init_db, get_pending_events
    init_db()

    from scripts.ingest.github_connector import app
    client = TestClient(app)

    # issue without pull_request field → should NOT be queued
    payload = {
        "action": "created",
        "issue": {"number": 13, "title": "Bug report"},
        "comment": {
            "user": {"login": "bob"},
            "body": "Can you reproduce this?",
            "html_url": "https://github.com/owner/repo/issues/13#issuecomment-2",
        },
    }
    response = client.post(
        "/webhook/github",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json", "X-GitHub-Event": "issue_comment"},
    )
    assert response.status_code == 200
    assert len(get_pending_events()) == 0
