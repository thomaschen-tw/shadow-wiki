import json
import logging
import time

import httpx

from scripts.config import get_settings
from scripts.db import push_event

logger = logging.getLogger(__name__)
_LINEAR_API = "https://api.linear.app/graphql"

_ISSUES_QUERY = """
query($after: String) {
  issues(first: 25, after: $after, orderBy: updatedAt) {
    nodes {
      id title description
      state { name }
      assignee { name }
      comments(first: 10) { nodes { body user { name } createdAt } }
      updatedAt
    }
    pageInfo { endCursor hasNextPage }
  }
}
"""


def _fetch_issues(after: str | None = None) -> dict:
    s = get_settings()
    resp = httpx.post(
        _LINEAR_API,
        json={"query": _ISSUES_QUERY, "variables": {"after": after}},
        headers={"Authorization": s.linear_api_key},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def ingest_linear_issues() -> int:
    data = _fetch_issues()
    nodes = data.get("data", {}).get("issues", {}).get("nodes", [])
    count = 0
    for issue in nodes:
        comments_text = "\n".join(
            f"[{c['user']['name']}]: {c['body']}"
            for c in issue.get("comments", {}).get("nodes", [])
        )
        raw_json = json.dumps({
            "id": issue["id"],
            "title": issue["title"],
            "description": issue.get("description") or "",
            "state": issue["state"]["name"],
            "body": f"{issue.get('description') or ''}\n\nComments:\n{comments_text}",
        })
        push_event("linear", "ticket", raw_json)
        count += 1
    logger.info("Queued %d Linear issues", count)
    return count


def run_linear_connector(poll_interval: int = 300) -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("Linear connector started (poll every %ds)", poll_interval)
    while True:
        try:
            ingest_linear_issues()
        except Exception as exc:
            logger.error("Linear poll failed: %s", exc)
        time.sleep(poll_interval)


if __name__ == "__main__":
    from scripts.db import init_db
    init_db()
    run_linear_connector()
