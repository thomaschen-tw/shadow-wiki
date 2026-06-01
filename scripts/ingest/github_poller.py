#!/usr/bin/env python3
"""
GitHub API poller — no webhook or ngrok needed.

Polls your GitHub repo for recent PRs and commits using the token you already
have.  Deduplicates by PR number so re-running never double-queues.

Usage:
  uv run python scripts/ingest/github_poller.py            # pull last 20 PRs once
  uv run python scripts/ingest/github_poller.py --limit 50 # pull up to 50 PRs
  uv run python scripts/ingest/github_poller.py --watch    # poll every 5 min
  uv run python scripts/ingest/github_poller.py --commits  # also ingest recent commits
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import httpx

from scripts.config import get_settings
from scripts.db import get_connection, init_db, push_event, update_file_hash

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_GH_API = "https://api.github.com"


def _headers(token: str) -> dict:
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}


def _already_queued(key: str) -> bool:
    """Use file_hashes as a processed-item registry."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT 1 FROM file_hashes WHERE path=?", (key,)
        ).fetchone() is not None


def _mark_queued(key: str) -> None:
    update_file_hash(key, "queued")


# ── PRs ───────────────────────────────────────────────────────────────────────

def fetch_prs(repo: str, token: str, limit: int = 20) -> list[dict]:
    resp = httpx.get(
        f"{_GH_API}/repos/{repo}/pulls",
        params={"state": "all", "sort": "updated", "direction": "desc", "per_page": min(limit, 100)},
        headers=_headers(token),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_diff(pr_url: str, token: str) -> str:
    try:
        resp = httpx.get(
            pr_url,
            headers={**_headers(token), "Accept": "application/vnd.github.v3.diff"},
            timeout=15,
        )
        return resp.text[:8000]
    except Exception as exc:
        logger.warning("Could not fetch diff: %s", exc)
        return ""


def ingest_prs(repo: str, token: str, limit: int) -> int:
    logger.info("Fetching up to %d PRs from %s ...", limit, repo)
    prs = fetch_prs(repo, token, limit)
    queued = 0
    for pr in prs:
        key = f"github_pr_{repo}_{pr['number']}"
        if _already_queued(key):
            logger.debug("PR #%d already queued — skip", pr["number"])
            continue

        diff = fetch_diff(pr["url"], token)
        push_event("github", "pr", json.dumps({
            "pr_number": pr["number"],
            "title": pr["title"],
            "description": pr.get("body") or "",
            "author": pr["user"]["login"],
            "diff": diff,
            "url": pr["html_url"],
            "merged": pr.get("merged", False),
            "state": pr.get("state", ""),
        }))
        _mark_queued(key)
        logger.info("Queued PR #%d: %s", pr["number"], pr["title"])
        queued += 1

    logger.info("Ingested %d new PRs (%d already seen)", queued, len(prs) - queued)
    return queued


# ── Commits ───────────────────────────────────────────────────────────────────

def fetch_commits(repo: str, token: str, limit: int = 20) -> list[dict]:
    resp = httpx.get(
        f"{_GH_API}/repos/{repo}/commits",
        params={"per_page": min(limit, 100)},
        headers=_headers(token),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_commit_diff(repo: str, sha: str, token: str) -> str:
    try:
        resp = httpx.get(
            f"{_GH_API}/repos/{repo}/commits/{sha}",
            headers={**_headers(token), "Accept": "application/vnd.github.v3.diff"},
            timeout=15,
        )
        return resp.text[:8000]
    except Exception as exc:
        logger.warning("Could not fetch commit diff: %s", exc)
        return ""


def ingest_commits(repo: str, token: str, limit: int) -> int:
    logger.info("Fetching up to %d commits from %s ...", limit, repo)
    commits = fetch_commits(repo, token, limit)
    queued = 0
    for commit in commits:
        sha = commit["sha"]
        key = f"github_commit_{repo}_{sha}"
        if _already_queued(key):
            continue

        msg = commit["commit"]["message"].split("\n")[0]
        diff = fetch_commit_diff(repo, sha, token)
        push_event("github", "commit", json.dumps({
            "sha": sha[:8],
            "title": msg,
            "description": commit["commit"]["message"],
            "author": (commit.get("author") or {}).get("login", commit["commit"]["author"]["name"]),
            "diff": diff,
            "url": commit["html_url"],
        }))
        _mark_queued(key)
        logger.info("Queued commit %s: %s", sha[:7], msg[:60])
        queued += 1

    logger.info("Ingested %d new commits (%d already seen)", queued, len(commits) - queued)
    return queued


# ── Entry point ───────────────────────────────────────────────────────────────

def poll_once(repo: str, token: str, limit: int, do_commits: bool) -> int:
    total = ingest_prs(repo, token, limit)
    if do_commits:
        total += ingest_commits(repo, token, limit)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll GitHub API for PRs/commits (no webhook needed)")
    parser.add_argument("--limit",   type=int, default=20, help="Max items to fetch per run (default: 20)")
    parser.add_argument("--watch",   action="store_true",  help="Keep polling every --interval seconds")
    parser.add_argument("--interval",type=int, default=300, help="Poll interval in seconds (default: 300)")
    parser.add_argument("--commits", action="store_true",  help="Also ingest recent commits")
    args = parser.parse_args()

    s = get_settings()
    if not s.github_token or s.github_token.endswith("..."):
        logger.error("GITHUB_TOKEN not set in .env — cannot poll GitHub API")
        sys.exit(1)
    if not s.github_repo or s.github_repo == "owner/repo":
        logger.error("GITHUB_REPO not set in .env (e.g. thomaschen-tw/pulse-wiki)")
        sys.exit(1)

    init_db()
    logger.info("GitHub poller started  repo=%s  limit=%d  commits=%s",
                s.github_repo, args.limit, args.commits)

    poll_once(s.github_repo, s.github_token, args.limit, args.commits)

    if args.watch:
        logger.info("Watch mode — polling every %ds (Ctrl+C to stop)", args.interval)
        while True:
            time.sleep(args.interval)
            poll_once(s.github_repo, s.github_token, args.limit, args.commits)


if __name__ == "__main__":
    main()
