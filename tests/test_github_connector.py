import json
import pytest
from unittest.mock import patch


def test_webhook_rejects_bad_signature(tmp_db, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")
    import scripts.config as cfg
    cfg._settings = None
    from scripts.db import init_db
    init_db()

    from scripts.ingest.github_connector import app
    client = app.test_client()
    response = client.post(
        "/webhook/github",
        data=json.dumps({"action": "opened"}),
        content_type="application/json",
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=bad"},
    )
    assert response.status_code == 403


def test_webhook_accepts_pr_opened(tmp_db, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    import scripts.config as cfg
    cfg._settings = None
    from scripts.db import init_db, get_pending_events
    init_db()

    from scripts.ingest.github_connector import app
    client = app.test_client()

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
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-GitHub-Event": "pull_request"},
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
    client = app.test_client()
    response = client.post(
        "/webhook/github",
        data=json.dumps({}),
        content_type="application/json",
        headers={"X-GitHub-Event": "push"},
    )
    assert response.status_code == 200
    assert len(get_pending_events()) == 0
