#!/usr/bin/env python3
"""CLI: manage Shadow Wiki database and configuration."""
import argparse
import sys
from pathlib import Path

# Ensure the project root is on sys.path when running this script directly
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def cmd_init(_args) -> None:
    from scripts.db import init_db
    init_db()
    print("Database initialized.")


def cmd_status(_args) -> None:
    from scripts.db import get_pipeline_status, get_connection
    status = get_pipeline_status()
    print(f"Pending : {status['pending']}")
    print(f"Failed  : {status['failed']}")
    print(f"Last run: {status['last_processed'] or 'never'}")
    with get_connection() as conn:
        mod_count = conn.execute("SELECT COUNT(*) FROM modules").fetchone()[0]
    print(f"Modules : {mod_count}")


def cmd_list(_args) -> None:
    from scripts.db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT path, summary, last_updated FROM modules ORDER BY last_updated DESC"
        ).fetchall()
    if not rows:
        print("No modules indexed yet.")
        return
    for r in rows:
        print(f"  {r['path']:40s}  {r['summary'] or '—'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Shadow Wiki resource manager")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Initialize the database")
    sub.add_parser("status", help="Show pipeline status")
    sub.add_parser("list", help="List all indexed wiki modules")

    args = parser.parse_args()
    {"init": cmd_init, "status": cmd_status, "list": cmd_list}[args.command](args)


if __name__ == "__main__":
    main()
