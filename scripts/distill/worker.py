import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.db import get_pending_events, mark_event_done, mark_event_failed, mark_event_processing
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


# ── Public entry points ───────────────────────────────────────────────────────

def process_event(event) -> None:
    try:
        _handle_event(event)
        mark_event_done(event["id"])
    except Exception as exc:
        logger.error("Event %d failed: %s", event["id"], exc)
        mark_event_failed(event["id"], str(exc))


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
            existing_threads = list(post.get("slack_threads", []))
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
