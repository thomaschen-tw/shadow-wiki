import json
import re
from datetime import datetime, timedelta

from fastmcp import FastMCP
from fastmcp.tools.tool import FunctionTool

from scripts.db import get_connection, get_pipeline_status, search_modules_fts
from scripts.wiki.manager import append_to_section, module_exists, read_module

mcp = FastMCP("shadow-wiki")


def search_wiki(query: str, limit: int = 5) -> list[dict]:
    """Search the wiki by keyword or phrase. Returns relevant module snippets."""
    results = search_modules_fts(query, limit)
    return [{"module": r["module_path"], "snippet": r["snippet"]} for r in results]


def get_module(path: str) -> str:
    """Get the full content of a wiki module page, including frontmatter metadata."""
    post = read_module(path)
    if post is None:
        return f"Module '{path}' not found."
    meta = json.dumps(dict(post.metadata), indent=2, default=str)
    return f"---\n{meta}\n---\n\n{post.content}"


def list_modules(tag: str | None = None) -> list[dict]:
    """List all wiki modules with one-line summaries. Optionally filter by tag."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT path, summary, last_updated FROM modules ORDER BY last_updated DESC"
        ).fetchall()

    if not tag:
        return [{"path": r["path"], "summary": r["summary"], "last_updated": r["last_updated"]} for r in rows]

    result = []
    for row in rows:
        post = read_module(row["path"])
        if post and tag in post.get("tags", []):
            result.append({"path": row["path"], "summary": row["summary"], "last_updated": row["last_updated"]})
    return result


def get_recent_changes(since: str = "7d") -> list[dict]:
    """Get recent processed events. 'since' format: '7d', '24h', '30d'."""
    match = re.match(r"(\d+)(d|h)", since)
    if not match:
        return [{"error": "Invalid 'since' format. Use '7d', '24h', etc."}]

    amount, unit = int(match.group(1)), match.group(2)
    delta = timedelta(days=amount) if unit == "d" else timedelta(hours=amount)
    cutoff = (datetime.now() - delta).isoformat()

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT source, event_type, raw_json, processed_at
               FROM events
               WHERE status='done' AND processed_at > ?
               ORDER BY processed_at DESC LIMIT 50""",
            (cutoff,),
        ).fetchall()

    result = []
    for r in rows:
        try:
            raw = json.loads(r["raw_json"])
            title = raw.get("title", raw.get("body", "")[:80])
        except (json.JSONDecodeError, TypeError):
            title = ""
        result.append({
            "source": r["source"],
            "event_type": r["event_type"],
            "title": title,
            "processed_at": r["processed_at"],
        })
    return result


def update_module(path: str, section: str, content: str) -> dict:
    """Append content to a specific section of a module wiki page."""
    if not module_exists(path):
        return {"error": f"Module '{path}' does not exist. It is created automatically by the pipeline."}
    append_to_section(path, section, content)
    return {"status": "ok", "module": path, "section": section}


def get_pipeline_status_tool() -> dict:
    """Get pipeline health: pending queue depth, failed count, and last processed timestamp."""
    return get_pipeline_status()


# Register all tools with the MCP server
for _fn in [search_wiki, get_module, list_modules, get_recent_changes, update_module, get_pipeline_status_tool]:
    mcp.add_tool(FunctionTool.from_function(_fn))


if __name__ == "__main__":
    from scripts.db import init_db
    init_db()
    mcp.run()
