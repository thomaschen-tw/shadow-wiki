#!/usr/bin/env python3
"""Push a code diff into the PulseWiki event queue.

Usage (stdin):
  git diff HEAD~1 | uv run python scripts/ingest_diff.py --diff - --pr 42 --title "Add feature"

Usage (file):
  uv run python scripts/ingest_diff.py --diff changes.patch --pr 42 --title "Fix bug"
"""
import argparse
import ast
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.config import get_settings
from scripts.db import init_db, push_event


def validate_diff_syntax(diff_text: str) -> tuple[bool, str]:
    """Parse Python files in the diff for fatal syntax errors."""
    lines = diff_text.split("\n")
    current_file = None
    code_block = []

    for line in lines:
        if line.startswith("+++ b/"):
            current_file = line[6:]
            code_block = []
        elif current_file and current_file.endswith(".py"):
            if line.startswith("+") and not line.startswith("+++"):
                code_block.append(line[1:])

    if code_block:
        try:
            ast.parse("\n".join(code_block))
            return True, "Python syntax OK"
        except SyntaxError as exc:
            return False, f"Syntax error in {current_file}: {exc}"
    return True, "No Python code to validate"


def _save_raw(diff_text: str, title: str, confidence: float, reason: str) -> str:
    s = get_settings()
    raw_dir = Path(s.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    ts = int(datetime.now().timestamp())
    out = raw_dir / f"commit_{ts}.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out.write_text(
        f"---\ntitle: {title}\ntime: {now}\nconfidence: {confidence}\n"
        f"ast_validated: {confidence >= 0.9}\nreason: \"{reason}\"\n---\n\n"
        f"```diff\n{diff_text}\n```\n"
    )
    return str(out)


def main():
    parser = argparse.ArgumentParser(description="Push a diff into the PulseWiki queue")
    parser.add_argument("--diff", required=True, help="Path to diff file, or - for stdin")
    parser.add_argument("--pr", default="", help="PR number")
    parser.add_argument("--title", default="Manual diff", help="PR/commit title")
    parser.add_argument("--description", default="", help="Optional description")
    parser.add_argument("--no-validate", action="store_true", help="Skip AST syntax check")
    args = parser.parse_args()

    diff_text = sys.stdin.read() if args.diff == "-" else Path(args.diff).read_text()

    if not args.no_validate:
        ok, reason = validate_diff_syntax(diff_text)
        confidence = 0.95 if ok else 0.40
        if not ok:
            print(f"Warning: {reason} (ingesting with low confidence {confidence})")
    else:
        ok, reason, confidence = True, "Validation skipped", 0.95

    init_db()
    event_id = push_event("manual", "pr", json.dumps({
        "diff": diff_text,
        "pr_number": args.pr,
        "title": args.title,
        "description": args.description,
        "confidence": confidence,
    }))

    raw_path = _save_raw(diff_text, args.title, confidence, reason)
    print(f"Queued event #{event_id}  confidence={confidence:.2f}  {reason}")
    print(f"Raw backup : {raw_path}")


if __name__ == "__main__":
    main()
