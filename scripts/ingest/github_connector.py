import hashlib
import hmac
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request

from scripts.config import get_settings
from scripts.db import push_event

logger = logging.getLogger(__name__)
app = FastAPI()


def verify_signature(payload_body: bytes, signature_header: str) -> bool:
    secret = get_settings().github_webhook_secret
    if not secret:
        # Production mode: must have a secret configured
        logger.warning("Webhook received but GITHUB_WEBHOOK_SECRET is not configured. Set it in .env for production.")
        # Use env var to allow dev/test without secret, but require in production
        import os
        if os.environ.get("GITHUB_WEBHOOK_REQUIRE_SECRET", "false").lower() == "true":
            return False
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


@app.post("/webhook/github")
async def github_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(body, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    event_type = request.headers.get("X-GitHub-Event", "")
    try:
        payload = json.loads(body)
    except Exception:
        payload = {}

    if event_type == "pull_request" and payload.get("action") in (
        "opened", "closed", "synchronize", "reopened"
    ):
        pr = payload["pull_request"]
        diff = fetch_pr_diff(pr["url"])
        push_event("github", "pr", json.dumps({
            "pr_number": pr["number"],
            "title": pr["title"],
            "description": pr.get("body") or "",
            "author": pr["user"]["login"],
            "diff": diff,
            "url": pr["html_url"],
            "merged": pr.get("merged", False),
        }))
        logger.info("Queued PR #%d", pr["number"])

    elif event_type == "pull_request_review_comment":
        pr = payload.get("pull_request", {})
        comment = payload.get("comment", {})
        push_event("github", "review_comment", json.dumps({
            "pr_number": pr.get("number", ""),
            "body": comment.get("body", ""),
            "author": comment.get("user", {}).get("login", ""),
            "path": comment.get("path", ""),
            "diff_hunk": comment.get("diff_hunk", ""),
            "url": comment.get("html_url", ""),
        }))
        logger.info("Queued review comment on PR #%s", pr.get("number", ""))

    elif event_type == "pull_request_review" and payload.get("action") == "submitted":
        pr = payload.get("pull_request", {})
        review = payload.get("review", {})
        state = review.get("state", "").upper()  # APPROVED | CHANGES_REQUESTED | COMMENTED
        push_event("github", "pr_review", json.dumps({
            "pr_number": pr.get("number", ""),
            "title": pr.get("title", ""),
            "reviewer": review.get("user", {}).get("login", ""),
            "state": state,
            "body": review.get("body") or "",
            "url": review.get("html_url", ""),
        }))
        logger.info("Queued PR review (%s) on PR #%s", state, pr.get("number", ""))

    elif event_type == "issue_comment" and payload.get("action") in ("created", "edited"):
        issue = payload.get("issue", {})
        comment = payload.get("comment", {})

        # Comments on pull requests (issues with pull_request field) -> pr_comment
        if "pull_request" in issue:
            push_event("github", "pr_comment", json.dumps({
                "pr_number": issue.get("number", ""),
                "title": issue.get("title", ""),
                "user": comment.get("user", {}).get("login", ""),
                "body": comment.get("body", ""),
                "url": comment.get("html_url", ""),
            }))
            logger.info("Queued PR comment on #%s", issue.get("number", ""))
        else:
            # Plain GitHub issue Q&A comments -> issue_comment
            push_event("github", "issue_comment", json.dumps({
                "issue_number": issue.get("number", ""),
                "title": issue.get("title", ""),
                "user": comment.get("user", {}).get("login", ""),
                "body": comment.get("body", ""),
                "url": comment.get("html_url", ""),
                "state": issue.get("state", ""),
            }))
            logger.info("Queued issue comment on #%s", issue.get("number", ""))

    elif event_type == "issues" and payload.get("action") in ("opened", "edited", "reopened"):
        issue = payload.get("issue", {})
        labels = [x.get("name", "") for x in issue.get("labels", []) if x.get("name")]
        push_event("github", "issue", json.dumps({
            "issue_number": issue.get("number", ""),
            "title": issue.get("title", ""),
            "body": issue.get("body", ""),
            "user": issue.get("user", {}).get("login", ""),
            "url": issue.get("html_url", ""),
            "state": issue.get("state", ""),
            "labels": labels,
        }))
        logger.info("Queued issue #%s (%s)", issue.get("number", ""), payload.get("action", ""))

    elif event_type == "discussion" and payload.get("action") in ("created", "edited", "transferred", "reopened"):
        discussion = payload.get("discussion", {})
        category = discussion.get("category", {}).get("name", "General")
        push_event("github", "discussion", json.dumps({
            "discussion_id": discussion.get("id", ""),
            "number": discussion.get("number", ""),
            "title": discussion.get("title", ""),
            "body": discussion.get("body", ""),
            "user": discussion.get("user", {}).get("login", ""),
            "url": discussion.get("html_url", ""),
            "category": category,
        }))
        logger.info("Queued discussion #%s (%s)", discussion.get("number", ""), payload.get("action", ""))

    elif event_type == "discussion_comment" and payload.get("action") in ("created", "edited"):
        discussion = payload.get("discussion", {})
        comment = payload.get("comment", {})
        push_event("github", "discussion_comment", json.dumps({
            "discussion_number": discussion.get("number", ""),
            "discussion_title": discussion.get("title", ""),
            "body": comment.get("body", ""),
            "user": comment.get("user", {}).get("login", ""),
            "url": comment.get("html_url", ""),
        }))
        logger.info("Queued discussion comment on discussion #%s", discussion.get("number", ""))

    return {"status": "ok"}


if __name__ == "__main__":
    from scripts.db import init_db
    logging.basicConfig(level=logging.INFO)
    init_db()
    port = int(os.environ.get("GITHUB_CONNECTOR_PORT", "9000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
