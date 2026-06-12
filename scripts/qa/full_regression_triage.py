#!/usr/bin/env python3
"""Run full pytest regression by logical suite and detect likely ETL breaking changes.

Usage:
  uv run python scripts/qa/full_regression_triage.py
  uv run python scripts/qa/full_regression_triage.py --category etl --maxfail 1
  uv run python scripts/qa/full_regression_triage.py --collect-only
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = ROOT / "tests"
ARTIFACT_DIR = ROOT / "artifacts" / "regression"


@dataclass(frozen=True)
class SuiteRule:
    name: str
    matcher: Callable[[str], bool]


def _is_etl(nodeid: str) -> bool:
    # ETL P0 scope is defined as db/worker/integration tests in this repository.
    return (
        nodeid.startswith("tests/test_db.py::")
        or nodeid.startswith("tests/test_worker.py::")
        or nodeid.startswith("tests/test_integration.py::")
    )


def _is_fastmcp(nodeid: str) -> bool:
    return nodeid.startswith("tests/test_mcp_server.py::")


def _is_legacy(nodeid: str) -> bool:
    return not _is_etl(nodeid) and not _is_fastmcp(nodeid)


RULES: tuple[SuiteRule, ...] = (
    SuiteRule("etl", _is_etl),
    SuiteRule("fastmcp", _is_fastmcp),
    SuiteRule("legacy", _is_legacy),
)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def collect_nodeids() -> list[str]:
    proc = _run([sys.executable, "-m", "pytest", "--collect-only", "-q", str(TESTS_DIR)])
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"pytest collection failed:\n{output}")

    nodeids: list[str] = []
    for line in output.splitlines():
        item = line.strip()
        if item.startswith("tests/") and "::" in item:
            nodeids.append(item)
    return sorted(set(nodeids))


def categorize(nodeid: str) -> str:
    for rule in RULES:
        if rule.matcher(nodeid):
            return rule.name
    return "legacy"


def parse_failed_nodeids(pytest_output: str) -> list[str]:
    failed: list[str] = []
    # Short summary line format: FAILED tests/test_x.py::test_y - AssertionError...
    for match in re.finditer(r"^FAILED\s+([^\s]+)\s+-\s+.*$", pytest_output, flags=re.MULTILINE):
        failed.append(match.group(1))
    return sorted(set(failed))


def infer_breaking_tags(text: str) -> list[str]:
    tags: list[str] = []
    lower = text.lower()

    route_signals = [
        "new_module_candidate",
        "module_not_found_candidate",
        "fallback_reason",
        "rule_source",
        "target_exists",
    ]
    if any(sig in lower for sig in route_signals):
        tags.append("route-fallback-contract")

    if "'general'" in text and ("new_module_candidate" in lower or "module_not_found_candidate" in lower):
        tags.append("legacy-assert-general-mismatch")

    staging_signals = [
        "hot_only",
        "etl_staging_archive",
        "archived_at",
        "get_staging_records",
        "get_staging_status_counts",
        "has_staging_record",
        "get_inflight_staging_count",
        "get_recent_failed_staging_count",
    ]
    if any(sig in lower for sig in staging_signals):
        tags.append("staging-hot-table-contract")

    if re.search(r"no such column: archived_at|no such table: etl_staging_archive", lower):
        tags.append("db-schema-drift")

    if "argument of type" in lower and "event_id" in lower:
        tags.append("typed-clean-contract")

    return sorted(set(tags))


def run_suite(category: str, nodeids: list[str], maxfail: int | None = None) -> dict:
    cmd = [sys.executable, "-m", "pytest", "-q", "-rA"]
    if maxfail is not None:
        cmd.extend(["--maxfail", str(maxfail)])
    cmd.extend(nodeids)

    proc = _run(cmd)
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    failed_nodeids = parse_failed_nodeids(combined)
    tags = infer_breaking_tags(combined) if failed_nodeids else []

    return {
        "category": category,
        "total": len(nodeids),
        "exit_code": proc.returncode,
        "failed_count": len(failed_nodeids),
        "failed_nodeids": failed_nodeids,
        "breaking_tags": tags,
        "pytest_output": combined,
    }


def _print_summary(report: dict) -> None:
    print("\n=== Regression Summary ===")
    print(f"Collected tests: {report['collected_total']}")
    print(f"Overall status : {'PASS' if report['ok'] else 'FAIL'}")

    for suite in report["suites"]:
        print(
            f"- {suite['category']:8s} total={suite['total']:2d} "
            f"failed={suite['failed_count']:2d} exit={suite['exit_code']}"
        )
        if suite["failed_nodeids"]:
            for nodeid in suite["failed_nodeids"]:
                print(f"    FAILED: {nodeid}")
        if suite["breaking_tags"]:
            print(f"    BREAKING_TAGS: {', '.join(suite['breaking_tags'])}")


def build_report(nodeids: list[str], selected: set[str], maxfail: int | None = None) -> dict:
    by_suite: dict[str, list[str]] = {rule.name: [] for rule in RULES}
    for nodeid in nodeids:
        suite = categorize(nodeid)
        if suite in selected:
            by_suite.setdefault(suite, []).append(nodeid)

    suites = []
    for suite_name in ["etl", "fastmcp", "legacy"]:
        if suite_name not in selected:
            continue
        suite_nodeids = by_suite.get(suite_name, [])
        if not suite_nodeids:
            suites.append(
                {
                    "category": suite_name,
                    "total": 0,
                    "exit_code": 0,
                    "failed_count": 0,
                    "failed_nodeids": [],
                    "breaking_tags": [],
                    "pytest_output": "",
                }
            )
            continue
        suites.append(run_suite(suite_name, suite_nodeids, maxfail=maxfail))

    ok = all(s["exit_code"] == 0 for s in suites)
    return {
        "collected_total": len(nodeids),
        "selected_categories": sorted(selected),
        "ok": ok,
        "suites": suites,
    }


def write_artifacts(report: dict) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = ARTIFACT_DIR / "full_regression_report.json"
    md_path = ARTIFACT_DIR / "full_regression_report.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Full Regression Report",
        "",
        f"Collected tests: **{report['collected_total']}**",
        f"Overall status: **{'PASS' if report['ok'] else 'FAIL'}**",
        "",
        "| Suite | Total | Failed | Exit Code | Breaking Tags |",
        "|---|---:|---:|---:|---|",
    ]

    for suite in report["suites"]:
        tags = ", ".join(suite["breaking_tags"]) if suite["breaking_tags"] else "-"
        lines.append(
            f"| {suite['category']} | {suite['total']} | {suite['failed_count']} | {suite['exit_code']} | {tags} |"
        )

    lines.append("")
    for suite in report["suites"]:
        if not suite["failed_nodeids"]:
            continue
        lines.append(f"## Failed Cases: {suite['category']}")
        for nodeid in suite["failed_nodeids"]:
            lines.append(f"- {nodeid}")
        lines.append("")

    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run categorized pytest regression and triage likely breaking changes.")
    parser.add_argument(
        "--category",
        action="append",
        choices=["etl", "fastmcp", "legacy", "all"],
        help="Category to run. Repeatable. Defaults to all.",
    )
    parser.add_argument("--maxfail", type=int, default=None, help="Pass --maxfail to each pytest suite run.")
    parser.add_argument("--collect-only", action="store_true", help="Only collect and print categorized tests.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    nodeids = collect_nodeids()

    selected = set(args.category or ["all"])
    if "all" in selected:
        selected = {"etl", "fastmcp", "legacy"}

    if args.collect_only:
        print(f"Collected {len(nodeids)} tests")
        counts = {"etl": 0, "fastmcp": 0, "legacy": 0}
        for nodeid in nodeids:
            counts[categorize(nodeid)] += 1
        for suite in ["etl", "fastmcp", "legacy"]:
            if suite in selected:
                print(f"- {suite}: {counts[suite]}")
        return 0

    report = build_report(nodeids=nodeids, selected=selected, maxfail=args.maxfail)
    write_artifacts(report)
    _print_summary(report)

    print("\nArtifacts:")
    print(f"- {json_path_rel(ARTIFACT_DIR / 'full_regression_report.json')}")
    print(f"- {json_path_rel(ARTIFACT_DIR / 'full_regression_report.md')}")

    return 0 if report["ok"] else 1


def json_path_rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
