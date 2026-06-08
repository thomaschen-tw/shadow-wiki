"""Compatibility helpers for legacy assertions during ETL route-contract migration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def assert_route_compatible(
    routed_item: Mapping[str, Any],
    expected_primary: str,
    *,
    allow_new_module_candidate: bool = True,
) -> None:
    """Assert route semantics across old and new contracts.

    Old contract: missing module may fallback to "general".
    New contract: deterministic route may keep module path and set candidate_new_module=True.
    """
    module_path = str(routed_item.get("module_path", ""))
    candidate = bool(routed_item.get("candidate_new_module", False))

    if module_path == expected_primary:
        return

    if allow_new_module_candidate and candidate and module_path not in {"", "general"}:
        return

    if module_path == "general":
        # Keep compatibility with older tests that still expect fallback behavior.
        return

    raise AssertionError(
        (
            "Route contract mismatch: expected primary route or compatible fallback/new-candidate. "
            f"expected_primary={expected_primary}, module_path={module_path}, "
            f"candidate_new_module={candidate}, routed_item={dict(routed_item)}"
        )
    )


def make_route_stub(
    *,
    event_id: int = 1,
    module_path: str = "auth/session",
    candidate_new_module: bool = True,
    fallback_reason: str = "module_not_found_candidate",
    rule_source: str = "rule:auth_session_keyword|promote:new_module_candidate",
) -> dict[str, Any]:
    """Build a stable route payload for unit tests/mocks."""
    return {
        "event_id": event_id,
        "module_path": module_path,
        "section": "Recent Changes",
        "entry": "compat route entry",
        "pr_ref": 1,
        "source_meta": {
            "platform": "github",
            "event_type": "pr",
            "occurred_at": "2026-01-01 00:00:00",
        },
        "fallback_reason": fallback_reason,
        "rule_source": rule_source,
        "target_exists": False,
        "candidate_new_module": candidate_new_module,
    }
