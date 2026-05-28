import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.db import get_pending_events, mark_event_done, mark_event_failed, mark_event_processing
from scripts.distill.llm_router import TaskType, call_llm
from scripts.distill.prompts import (
    CLASSIFY_SYSTEM, SUMMARIZE_SYSTEM, APPEND_SYSTEM, CREATE_PAGE_SYSTEM,
    classify_prompt, summarize_prompt, append_prompt, create_page_prompt,
)
from scripts.wiki.manager import append_to_section, create_module, module_exists, read_module

logger = logging.getLogger(__name__)


def process_event(event) -> None:
    try:
        _handle_event(event)
        mark_event_done(event["id"])
    except Exception as exc:
        logger.error("Event %d failed: %s", event["id"], exc)
        mark_event_failed(event["id"], str(exc))


def _handle_event(event) -> None:
    raw = json.loads(event["raw_json"])
    content = " ".join(filter(None, [
        raw.get("diff", ""),
        raw.get("description", ""),
        raw.get("body", ""),
        raw.get("title", ""),
        raw.get("content", ""),
    ]))

    modules_json = call_llm(TaskType.CLASSIFY, classify_prompt(content), CLASSIFY_SYSTEM)
    try:
        modules: list[str] = json.loads(modules_json)
        if not isinstance(modules, list) or not modules:
            modules = ["general"]
    except (json.JSONDecodeError, TypeError):
        modules = ["general"]

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
            append_to_section(module_path, "Recent Changes", entry, pr_ref)


def run_worker(poll_interval: int = 30) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Shadow Wiki worker started (poll interval: %ds)", poll_interval)
    while True:
        events = get_pending_events(limit=10)
        if events:
            logger.info("Processing %d events", len(events))
            for event in events:
                # TODO: make claim atomic (UPDATE WHERE status='pending') before scaling to multiple workers
                mark_event_processing(event["id"])
                process_event(event)
        time.sleep(poll_interval)


if __name__ == "__main__":
    from scripts.db import init_db
    init_db()
    run_worker()
