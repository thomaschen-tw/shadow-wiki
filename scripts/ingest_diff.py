#!/usr/bin/env python3
"""CLI: manually push a diff or file into the Shadow Wiki pipeline."""
import argparse
import json
import sys
from pathlib import Path

# Ensure the project root is on sys.path when running this script directly
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manually ingest a diff into Shadow Wiki"
    )
    parser.add_argument("--diff", required=True, metavar="FILE|-",
                        help="Path to diff file, or '-' to read from stdin")
    parser.add_argument("--pr", default="", metavar="NUMBER", help="PR number e.g. 142")
    parser.add_argument("--title", default="Manual ingestion", help="Change title")
    parser.add_argument("--description", default="", help="Change description")
    args = parser.parse_args()

    if args.diff == "-":
        diff_content = sys.stdin.read()
    else:
        diff_content = Path(args.diff).read_text()

    from scripts.db import init_db, push_event
    init_db()

    raw_json = json.dumps({
        "pr_number": args.pr,
        "title": args.title,
        "description": args.description,
        "diff": diff_content,
    })
    event_id = push_event("github", "pr", raw_json)
    print(f"Queued event #{event_id}. Run the worker to process it.")


if __name__ == "__main__":
    main()
