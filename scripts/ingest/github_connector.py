import hashlib
import hmac
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import httpx
from flask import Flask, abort, request

from scripts.config import get_settings
from scripts.db import push_event

logger = logging.getLogger(__name__)
app = Flask(__name__)


def verify_signature(payload_body: bytes, signature_header: str) -> bool:
    secret = get_settings().github_webhook_secret
    if not secret:
        return True
    expected = "sha256=" + hmac.new(
        secret.encode(), payload_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def fetch_pr_diff(pr_api_url: str) -> str:
    s = get_settings()
    try:
        resp = httpx.get(
            pr_api_url,
            headers={
                "Authorization": f"token {s.github_token}",
                "Accept": "application/vnd.github.v3.diff",
            },
            timeout=10,
        )
        return resp.text[:8000]
    except Exception as exc:
        logger.warning("Failed to fetch diff: %s", exc)
        return ""


@app.route("/webhook/github", methods=["POST"])
def github_webhook():
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(request.data, sig):
        abort(403)

    event_type = request.headers.get("X-GitHub-Event", "")
    payload = request.get_json(silent=True) or {}

    if event_type == "pull_request" and payload.get("action") in (
        "opened", "closed", "synchronize", "reopened"
    ):
        pr = payload["pull_request"]
        diff = fetch_pr_diff(pr["url"])
        raw_json = json.dumps({
            "pr_number": pr["number"],
            "title": pr["title"],
            "description": pr.get("body") or "",
            "author": pr["user"]["login"],
            "diff": diff,
            "url": pr["html_url"],
            "merged": pr.get("merged", False),
        })
        push_event("github", "pr", raw_json)
        logger.info("Queued PR #%d", pr["number"])

    elif event_type == "pull_request_review_comment":
        pr = payload.get("pull_request", {})
        comment = payload.get("comment", {})
        raw_json = json.dumps({
            "pr_number": pr.get("number", ""),
            "body": comment.get("body", ""),
            "author": comment.get("user", {}).get("login", ""),
            "path": comment.get("path", ""),
            "diff_hunk": comment.get("diff_hunk", ""),
        })
        push_event("github", "review_comment", raw_json)

    return {"status": "ok"}, 200


if __name__ == "__main__":
    from scripts.db import init_db
    init_db()
    app.run(port=9000)
