import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.db import get_pending_events, mark_event_done, mark_event_failed, mark_event_processing
from scripts.db import (
    etl_archive_or_prune,
    get_events_in_window,
    has_staging_record,
    get_staging_records,
    mark_staging_done,
    mark_staging_failed,
    mark_staging_processing,
    push_staging,
)
from scripts.distill.llm_router import TaskType, call_llm
from scripts.distill.prompts import (
    # Code prompts
    CLASSIFY_SYSTEM, SUMMARIZE_SYSTEM, APPEND_SYSTEM, CREATE_PAGE_SYSTEM,
    SYNTHESIZE_SYSTEM, REVIEW_SYNTHESIS_SYSTEM, RUNBOOK_SYSTEM,
    classify_prompt, summarize_prompt, append_prompt, create_page_prompt,
    synthesize_prompt, review_synthesis_prompt, runbook_prompt,
    # Knowledge prompts
    KNOWLEDGE_CLASSIFY_SYSTEM, KNOWLEDGE_SUMMARIZE_SYSTEM,
    KNOWLEDGE_CREATE_PAGE_SYSTEM, KNOWLEDGE_APPEND_SYSTEM,
    knowledge_classify_prompt, knowledge_summarize_prompt,
    knowledge_create_page_prompt, knowledge_append_prompt,
)
from scripts.wiki.manager import append_to_section, create_module, module_exists, read_module, update_frontmatter

logger = logging.getLogger(__name__)


MAX_TITLE_LEN = 300
MAX_DESC_LEN = 3000
MAX_DIFF_LEN = 12000
MAX_TEXT_LEN = 400


class RawEventContext(BaseModel):
    """Strict clean-stage contract for ETL payload normalization."""

    model_config = ConfigDict(extra="ignore")

    event_id: int
    source: str = ""
    event_type: str = ""
    occurred_at: str
    title: str = ""
    description: str = ""
    diff: str = ""
    is_completed: bool = True
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source", "event_type", mode="before")
    @classmethod
    def _normalize_short_text(cls, value: Any) -> str:
        return _normalize_text(value, max_len=80)

    @field_validator("title", mode="before")
    @classmethod
    def _normalize_title(cls, value: Any) -> str:
        return _normalize_text(value, max_len=MAX_TITLE_LEN)

    @field_validator("description", mode="before")
    @classmethod
    def _normalize_description(cls, value: Any) -> str:
        return _normalize_text(value, max_len=MAX_DESC_LEN)

    @field_validator("diff", mode="before")
    @classmethod
    def _normalize_diff(cls, value: Any) -> str:
        return _normalize_text(value, max_len=MAX_DIFF_LEN)

    @field_validator("occurred_at", mode="before")
    @classmethod
    def _normalize_occurred_at(cls, value: Any) -> str:
        return _normalize_timestamp(value)


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: int
    module_path: str
    section: str = "Recent Changes"
    entry: str
    pr_ref: int | str | None = None
    source_meta: dict[str, Any] = Field(default_factory=dict)
    fallback_reason: str = ""
    rule_source: str = ""
    target_exists: bool = False
    candidate_new_module: bool = False


# ── Public entry points ───────────────────────────────────────────────────────

def process_event(event) -> None:
    try:
        _handle_event(event)
        mark_event_done(event["id"])
    except Exception as exc:
        logger.error("Event %d failed: %s", event["id"], exc)
        mark_event_failed(event["id"], str(exc))


def process_event_legacy(event) -> None:
    """Legacy single-event entry point (kept for backward compatibility)."""
    process_event(event)


def run_worker(poll_interval: int = 30) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("PulseWiki worker started (poll interval: %ds)", poll_interval)
    while True:
        events = get_pending_events(limit=10)
        if events:
            logger.info("Processing %d events", len(events))
            for event in events:
                mark_event_processing(event["id"])
                process_event(event)
        time.sleep(poll_interval)


def run_legacy_worker(poll_interval: int = 30) -> None:
    """Legacy realtime polling worker entry point."""
    run_worker(poll_interval=poll_interval)


def clean_batch(
    limit: int = 10,
    dry_run: bool = True,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    """ETL stage 1: deterministic normalization + strict schema validation."""
    cleaned: list[dict] = []
    events = get_events_in_window(since, until, limit=limit) if since and until else get_pending_events(limit=limit)
    for event in events:
        raw = _safe_json(_event_value(event, "raw_json", "{}"), {})
        input_json = json.dumps(raw, ensure_ascii=False)
        event_id_raw = _event_value(event, "id")
        event_id = int(event_id_raw) if isinstance(event_id_raw, int) else None
        if event_id is None:
            logger.error("ETL clean validation failed: missing/invalid event id (%s)", event_id_raw)
            continue

        if not dry_run and has_staging_record(event_id, "clean", status="done"):
            logger.info("ETL clean stage skip event %s (already done)", event_id)
            continue

        staging_id: int | None = None
        if not dry_run:
            staging_id = push_staging(
                event_id=event_id,
                stage_name="clean",
                input_json=input_json,
                status="processing",
            )

        try:
            if not isinstance(raw, dict):
                raise ValueError("raw_json must decode to a JSON object")

            context = RawEventContext.model_validate(
                {
                    "event_id": event_id,
                    "source": _event_value(event, "source", ""),
                    "event_type": _event_value(event, "event_type", ""),
                    "occurred_at": _event_value(event, "created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    "title": raw.get("title") or raw.get("message") or "",
                    "description": raw.get("description") or raw.get("body") or raw.get("content") or "",
                    "diff": raw.get("diff") or "",
                    "is_completed": True,
                    "raw": raw,
                }
            )
            item = context.model_dump()
            cleaned.append(item)

            if not dry_run and staging_id is not None:
                mark_staging_processing(staging_id)
                mark_staging_done(staging_id, output_json=json.dumps(item, ensure_ascii=False))
        except (ValidationError, ValueError, TypeError) as exc:
            logger.error("ETL clean validation failed for event %s: %s", event_id, exc)
            if not dry_run and staging_id is not None:
                mark_staging_failed(staging_id, f"clean_validation_error: {exc}")
                mark_event_failed(event_id, f"clean_validation_error: {exc}")
            continue
        except Exception as exc:
            if not dry_run and staging_id is not None:
                mark_staging_failed(staging_id, str(exc))
            raise

    logger.info("ETL clean stage prepared %d item(s)%s", len(cleaned), " [dry-run]" if dry_run else "")
    return cleaned


def route_batch(cleaned: list[dict] | None = None, dry_run: bool = True, limit: int = 100) -> list[dict]:
    """ETL stage 2: explicit routing rules + fallback metadata."""
    if cleaned is None:
        cleaned_rows = get_staging_records("clean", status="done", limit=limit)
        cleaned = []
        for row in cleaned_rows:
            payload = _safe_json(row["output_json"], {})
            if payload:
                cleaned.append(payload)

    routed: list[dict] = []
    for item in cleaned:
        module_path, rule_source, fallback_reason, candidate_new_module = _resolve_route(item)
        target_exists = module_exists(module_path)
        if not target_exists and not candidate_new_module and module_path != "general":
            # Keep deterministic routes (for example auth/session) and mark them as
            # explicit new-module candidates instead of collapsing to `general`.
            candidate_new_module = True
            fallback_reason = fallback_reason or "module_not_found_candidate"
            rule_source = f"{rule_source}|promote:new_module_candidate"

        route_context = RouteDecision(
            event_id=item["event_id"],
            module_path=module_path,
            section="Recent Changes",
            entry=_normalize_text(item.get("description") or item.get("title") or "No summary", MAX_TEXT_LEN),
            pr_ref=item.get("raw", {}).get("pr_number"),
            source_meta={
                "platform": item.get("source", ""),
                "event_type": item.get("event_type", ""),
                "occurred_at": item.get("occurred_at", ""),
            },
            fallback_reason=fallback_reason,
            rule_source=rule_source,
            target_exists=target_exists,
            candidate_new_module=candidate_new_module,
        )
        route_item = route_context.model_dump()
        routed.append(route_item)

        if not dry_run:
            if has_staging_record(route_item["event_id"], "route", status="done"):
                logger.info("ETL route stage skip event %s (already done)", route_item["event_id"])
                continue
            staging_id = push_staging(
                event_id=route_item["event_id"],
                stage_name="route",
                input_json=json.dumps(item, ensure_ascii=False),
                status="processing",
            )
            try:
                mark_staging_processing(staging_id)
                mark_staging_done(staging_id, output_json=json.dumps(route_item, ensure_ascii=False))
            except Exception as exc:
                mark_staging_failed(staging_id, str(exc))
                raise

    logger.info("ETL route stage produced %d route(s)%s", len(routed), " [dry-run]" if dry_run else "")
    return routed


def distill_batch(routed: list[dict] | None = None, dry_run: bool = True, limit: int = 100) -> list[dict]:
    """ETL stage 3 skeleton: materialize routed entries into wiki modules."""
    if routed is None:
        route_rows = get_staging_records("route", status="done", limit=limit)
        routed = []
        for row in route_rows:
            payload = _safe_json(row["output_json"], {})
            if payload:
                routed.append(payload)

    results: list[dict] = []
    for item in routed:
        module_path = item["module_path"]
        if dry_run:
            results.append({"module": module_path, "action": "preview"})
            continue

        if has_staging_record(item["event_id"], "distill", status="done"):
            logger.info("ETL distill stage skip event %s (already done)", item["event_id"])
            results.append({"module": module_path, "action": "skipped"})
            continue

        staging_id = push_staging(
            event_id=item["event_id"],
            stage_name="distill",
            input_json=json.dumps(item, ensure_ascii=False),
            status="processing",
        )
        try:
            if not module_exists(module_path):
                create_action = _create_module_for_etl(item)
                action = create_action
            else:
                action = "updated"

            pr_ref = item.get("pr_ref")
            pr_label = f"#{pr_ref}" if pr_ref else None
            append_to_section(
                module_path,
                item.get("section", "Recent Changes"),
                item.get("entry", ""),
                pr_label,
                source_meta=item.get("source_meta"),
            )
            mark_event_done(item["event_id"])
            mark_staging_done(staging_id, output_json=json.dumps({"module": module_path, "action": action}))
            results.append({"module": module_path, "action": action})
        except Exception as exc:
            mark_staging_failed(staging_id, str(exc))
            raise

    logger.info("ETL distill stage completed %d action(s)%s", len(results), " [dry-run]" if dry_run else "")
    return results


def run_etl_once(
    limit: int = 10,
    dry_run: bool = True,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    """Run ETL skeleton stages in-memory for daytime testing and validation."""
    cleaned = clean_batch(limit=limit, dry_run=dry_run, since=since, until=until)
    routed = route_batch(cleaned, dry_run=dry_run, limit=limit)
    results = distill_batch(routed, dry_run=dry_run, limit=limit)
    return {
        "cleaned": len(cleaned),
        "routed": len(routed),
        "distilled": len(results),
        "dry_run": dry_run,
    }


def run_etl_once_with_cleanup(
    limit: int = 10,
    dry_run: bool = True,
    since: str | None = None,
    until: str | None = None,
    cleanup_hours: int = 24,
    cleanup_mode: str = "archive",
) -> dict:
    """Run ETL and perform best-effort hot-table maintenance after apply."""
    summary = run_etl_once(limit=limit, dry_run=dry_run, since=since, until=until)
    if dry_run:
        summary["archived_or_pruned"] = 0
        return summary

    moved = etl_archive_or_prune(
        older_than_hours=cleanup_hours,
        mode=cleanup_mode,
        dry_run=False,
    )
    summary["archived_or_pruned"] = moved
    return summary


# ── Dispatcher ────────────────────────────────────────────────────────────────

def _handle_event(event) -> None:
    if event["source"] == "knowledge_base":
        _handle_knowledge_event(event)
    elif event["source"] == "slack" and event["event_type"] == "thread_reply":
        _handle_slack_thread_reply(event)
    elif event["source"] == "github" and event["event_type"] in ("pr_review", "pr_comment"):
        _handle_review_event(event)
    else:
        _handle_code_event(event)


# ── Slack thread reply handler ───────────────────────────────────────────────

def _handle_slack_thread_reply(event) -> None:
    raw = json.loads(event["raw_json"])
    body = raw.get("body", "")
    channel = raw.get("channel", "")
    thread_ts = raw.get("thread_ts", "")
    user = raw.get("user", "")

    if not body.strip():
        logger.info("Skipping empty thread reply from channel %s", channel)
        return

    # Classify which module(s) this thread discussion is about
    modules_json = call_llm(TaskType.CLASSIFY, classify_prompt(body), CLASSIFY_SYSTEM)
    modules = _parse_json_list(modules_json, default=["general"])

    today = datetime.now().strftime("%Y-%m-%d")
    thread_ref = f"slack:{channel}:{thread_ts}" if thread_ts else f"slack:{channel}"
    entry = f"**Thread** `{thread_ref}` — {body[:500]}"
    source_meta = {
        "platform": "slack",
        "event_type": "thread_reply",
        "ref": thread_ref,
        "url": raw.get("url", ""),
        "actor": user,
        "channel": channel,
        "thread_ts": thread_ts,
        "occurred_at": _event_value(event, "created_at", today),
    }

    for module_path in modules:
        if not module_exists(module_path):
            logger.info("Module %s not found for thread reply — skipping", module_path)
            continue

        # Append to Slack Discussions section
        append_to_section(module_path, "Slack Discussions", entry, source_meta=source_meta)

        # Update slack_threads frontmatter (deduplicated)
        post = read_module(module_path)
        if post is not None:
            threads_value = post.get("slack_threads", [])
            existing_threads = list(threads_value) if isinstance(threads_value, list) else []
            if thread_ref not in existing_threads:
                update_frontmatter(module_path, {"slack_threads": [thread_ref] + existing_threads[:9]})

        logger.info("Appended Slack thread reply to %s", module_path)


# ── GitHub review / PR comment handler ──────────────────────────────────────

def _handle_review_event(event) -> None:
    raw = json.loads(event["raw_json"])
    event_type = event["event_type"]
    pr_number = raw.get("pr_number", "")
    pr_ref = f"#{pr_number}" if pr_number else "unknown"
    pr_title = raw.get("title", "")

    if event_type == "pr_review":
        reviewer = raw.get("reviewer", "")
        state = raw.get("state", "")
        body = raw.get("body", "")
        content = f"{pr_title} — {state} by {reviewer}: {body}"
        synthesis_prompt = review_synthesis_prompt(reviewer, state, body, pr_title)
    else:  # pr_comment
        user = raw.get("user", "")
        body = raw.get("body", "")
        content = f"{pr_title}: {body}"
        synthesis_prompt = review_synthesis_prompt(user, "COMMENT", body, pr_title)

    modules_json = call_llm(TaskType.CLASSIFY, classify_prompt(content), CLASSIFY_SYSTEM)
    modules = _parse_json_list(modules_json, default=["general"])

    entry = call_llm(TaskType.APPEND, synthesis_prompt, REVIEW_SYNTHESIS_SYSTEM)
    source_meta = {
        "platform": "github",
        "event_type": event_type,
        "ref": pr_ref,
        "url": raw.get("url", ""),
        "actor": raw.get("reviewer") or raw.get("user", ""),
        "pr_number": pr_number,
        "occurred_at": _event_value(event, "created_at", datetime.now().strftime("%Y-%m-%d")),
    }

    for module_path in modules:
        if not module_exists(module_path):
            logger.info("Module %s not found for review event — skipping", module_path)
            continue
        append_to_section(module_path, "Recent Changes", entry, pr_ref, source_meta=source_meta)
        logger.info("Appended %s to %s", event_type, module_path)


# ── Code event handler (GitHub / Slack / Linear / manual diff) ───────────────

def _handle_code_event(event) -> None:
    raw = json.loads(event["raw_json"])
    content = " ".join(filter(None, [
        raw.get("diff", ""),
        raw.get("description", ""),
        raw.get("body", ""),
        raw.get("title", ""),
        raw.get("content", ""),
    ]))

    modules_json = call_llm(TaskType.CLASSIFY, classify_prompt(content), CLASSIFY_SYSTEM)
    modules = _parse_json_list(modules_json, default=["general"])

    diff = raw.get("diff", "")
    description = raw.get("description", raw.get("body", raw.get("title", "")))
    summary_json = call_llm(TaskType.SUMMARIZE, summarize_prompt(diff, description), SUMMARIZE_SYSTEM)
    try:
        summary_data = json.loads(summary_json)
        change_text = summary_data.get("summary", description[:300])
    except (json.JSONDecodeError, TypeError):
        change_text = description[:300]

    pr_number = raw.get("pr_number", raw.get("number", ""))
    pr_ref = f"#{pr_number}" if pr_number else "unknown"
    source_meta = {
        "platform": _event_value(event, "source", ""),
        "event_type": _event_value(event, "event_type", ""),
        "ref": pr_ref,
        "url": raw.get("url", ""),
        "actor": raw.get("author") or raw.get("user", ""),
        "pr_number": pr_number,
        "issue_number": raw.get("issue_number", ""),
        "channel": raw.get("channel", ""),
        "thread_ts": raw.get("thread_ts", ""),
        "occurred_at": _event_value(event, "created_at", datetime.now().strftime("%Y-%m-%d")),
    }

    for module_path in modules:
        if not module_exists(module_path):
            body = call_llm(
                TaskType.CREATE_PAGE,
                create_page_prompt(module_path, content[:2000]),
                CREATE_PAGE_SYSTEM,
            )
            create_module(module_path, body, summary=change_text[:200])
            logger.info("Created module: %s", module_path)
        else:
            existing = read_module(module_path)
            existing_content = existing.content if existing else ""
            entry = call_llm(
                TaskType.APPEND,
                append_prompt(existing_content, change_text, pr_ref, datetime.now().strftime("%Y-%m-%d")),
                APPEND_SYSTEM,
            )
            append_to_section(module_path, "Recent Changes", entry, pr_ref, source_meta=source_meta)

            # Post-append triggers: synthesis every 5 entries, runbook when issues accumulate
            updated = read_module(module_path)
            if updated:
                rc_count = _count_section_entries(updated.content, "Recent Changes")
                if rc_count > 0 and rc_count % 5 == 0:
                    _maybe_synthesize(module_path, updated.content)
                ki_count = _count_section_entries(updated.content, "Known Issues")
                if ki_count >= 2 and "## Runbooks" not in updated.content:
                    _maybe_generate_runbook(module_path, updated.content)


# ── Knowledge event handler (Obsidian wiki notes) ────────────────────────────

def _handle_knowledge_event(event) -> None:
    raw = json.loads(event["raw_json"])
    content  = raw.get("content", "")
    title    = raw.get("title", "")
    category = raw.get("wiki_category", "general")
    tags     = raw.get("tags") or []

    # Deterministic fallback path from category + slugified title
    slug = _slugify(title)
    default_path = f"knowledge/{category}/{slug}"

    # 1. CLASSIFY — confirm or refine topic path(s)
    topics_json = call_llm(
        TaskType.CLASSIFY,
        knowledge_classify_prompt(title, content, category, tags),
        KNOWLEDGE_CLASSIFY_SYSTEM,
    )
    topics = _parse_json_list(topics_json, default=[default_path])
    topics = [
        (t if t.startswith("knowledge/") else f"knowledge/{t}")
        for t in topics[:2]   # cap at 2 topics per note
    ]

    # 2. SUMMARIZE — extract structured insights
    summary_json = call_llm(
        TaskType.SUMMARIZE,
        knowledge_summarize_prompt(title, content),
        KNOWLEDGE_SUMMARIZE_SYSTEM,
    )
    summary_data = _safe_json(summary_json, {"insights": [], "key_concepts": [], "tags": []})

    today = datetime.now().strftime("%Y-%m-%d")

    # 3. CREATE or INCREMENTAL APPEND
    for topic_path in topics:
        if not module_exists(topic_path):
            body = call_llm(
                TaskType.CREATE_PAGE,
                knowledge_create_page_prompt(topic_path, title, content),
                KNOWLEDGE_CREATE_PAGE_SYSTEM,
            )
            create_module(topic_path, body, summary=title[:200])
            logger.info("Created knowledge page: %s", topic_path)
        else:
            existing = read_module(topic_path)
            existing_text = existing.content if existing else ""

            # Incremental guard: discard insights whose first 40 chars already appear
            new_insights = [
                i for i in summary_data.get("insights", [])
                if i.lower()[:40] not in existing_text.lower()
            ]

            if not new_insights:
                logger.info("No new insights for %s — skipping append", topic_path)
                continue

            entry = call_llm(
                TaskType.APPEND,
                knowledge_append_prompt(existing_text, new_insights, title, today),
                KNOWLEDGE_APPEND_SYSTEM,
            )
            append_to_section(topic_path, "Key Insights", entry)
            logger.info("Appended %d insights to %s", len(new_insights), topic_path)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _count_section_entries(content: str, section: str) -> int:
    """Count ### subsection entries within a ## section."""
    header = f"## {section}"
    if header not in content:
        return 0
    start = content.index(header) + len(header)
    next_h2 = content.find("\n## ", start)
    section_text = content[start:next_h2] if next_h2 != -1 else content[start:]
    return section_text.count("\n### ")


def _maybe_synthesize(module_path: str, content: str) -> None:
    """Synthesize recent changes into the Overview section (every 5 appends)."""
    try:
        recent_entries = content.split("## Recent Changes", 1)[-1].split("\n### ")[1:6]
        if not recent_entries:
            return
        entry = call_llm(
            TaskType.SYNTHESIZE,
            synthesize_prompt(module_path, recent_entries),
            SYNTHESIZE_SYSTEM,
        )
        append_to_section(module_path, "Overview", entry)
        logger.info("Synthesized overview for %s", module_path)
    except Exception as exc:
        logger.warning("Synthesis failed for %s: %s", module_path, exc)


def _maybe_generate_runbook(module_path: str, content: str) -> None:
    """Generate a Runbooks section when Known Issues has accumulated 2+ entries."""
    try:
        entry = call_llm(
            TaskType.RUNBOOK,
            runbook_prompt(module_path, content),
            RUNBOOK_SYSTEM,
        )
        append_to_section(module_path, "Runbooks", entry)
        logger.info("Generated runbook for %s", module_path)
    except Exception as exc:
        logger.warning("Runbook generation failed for %s: %s", module_path, exc)


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:60] or "untitled"


def _normalize_text(value: Any, max_len: int) -> str:
    if value is None:
        text = ""
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _normalize_timestamp(value: Any) -> str:
    if value is None:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip()
    if not text:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Keep already-normalized timestamps unchanged.
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text[:19], fmt)
            if fmt == "%Y-%m-%d":
                return dt.strftime("%Y-%m-%d 00:00:00")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _path_to_module_hint(path_value: Any) -> str:
    if not path_value:
        return ""
    path_text = str(path_value).strip().replace("\\", "/")
    parts = [p for p in path_text.split("/") if p]
    if not parts:
        return ""

    # Drop common roots and file names.
    stripped = [p for p in parts if p not in {"src", "scripts", "app", "lib", "wiki", "wiki_content"}]
    if not stripped:
        return ""

    tail = stripped[:2]
    tail[-1] = re.sub(r"\.[A-Za-z0-9_]+$", "", tail[-1])
    tail = [re.sub(r"[^a-zA-Z0-9_-]", "", p).lower() for p in tail if p]
    if not tail:
        return ""
    return "/".join(tail)


def _resolve_route(item: dict) -> tuple[str, str, str, bool]:
    text = " ".join(
        filter(None, [item.get("title", ""), item.get("description", ""), item.get("diff", "")])
    ).lower()
    raw = item.get("raw", {}) if isinstance(item.get("raw"), dict) else {}

    explicit_hint = raw.get("module_path") or _path_to_module_hint(raw.get("path"))
    if explicit_hint:
        module_path = _slugify(explicit_hint.replace("/", "-")) if "/" not in explicit_hint else explicit_hint
        module_path = module_path.strip("/")
        if module_exists(module_path):
            return module_path, "rule:explicit_hint", "", False
        return module_path, "rule:explicit_hint", "new_module_candidate", True

    if "auth" in text and "session" in text:
        return "auth/session", "rule:auth_session_keyword", "", False
    if "auth" in text:
        return "auth/user", "rule:auth_keyword", "", False

    return "general", "fallback:rule_miss", "rule_miss", False


def _build_local_stub_body() -> str:
    return "## Overview\n\n## Recent Changes\n\n## Known Issues\n\n## Related Modules\n\n## Runbooks\n"


def _create_module_for_etl(item: dict) -> str:
    module_path = item["module_path"]
    entry = item.get("entry", "")
    candidate_new_module = bool(item.get("candidate_new_module", False))

    # For ETL target and cloud-enabled mode, allow CREATE_PAGE for new module candidates.
    try:
        from scripts.config import WikiWriteTarget, get_settings

        s = get_settings()
        can_cloud_create = (
            s.wiki_write_target == WikiWriteTarget.ETL and
            s.use_cloud_llm and
            candidate_new_module
        )
    except Exception:
        can_cloud_create = False

    if can_cloud_create:
        try:
            body = call_llm(
                TaskType.CREATE_PAGE,
                create_page_prompt(module_path, entry[:2000]),
                CREATE_PAGE_SYSTEM,
            )
            create_module(module_path, body, summary=entry[:200])
            return "created_cloud"
        except Exception as exc:
            logger.warning("ETL cloud skeleton generation failed for %s: %s", module_path, exc)

    create_module(module_path, _build_local_stub_body(), summary=entry[:200])
    return "created_stub"


def _parse_json_list(s: str, default: list) -> list:
    try:
        result = json.loads(s)
        if isinstance(result, list) and result:
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return default


def _safe_json(s: str, default: dict) -> dict:
    try:
        result = json.loads(s)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return default


def _event_value(event, key: str, default=None):
    """Fetch a value from either sqlite Row-like objects or plain dicts."""
    try:
        if isinstance(event, dict):
            return event.get(key, default)
        return event[key]
    except Exception:
        return default


if __name__ == "__main__":
    from scripts.db import init_db
    init_db()
    run_worker()
