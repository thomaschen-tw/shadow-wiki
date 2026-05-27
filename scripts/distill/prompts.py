CLASSIFY_SYSTEM = (
    "You are a code repository analyst. Given a diff or message, identify which code modules are affected. "
    "Return ONLY a JSON array of module paths, e.g. [\"auth/session\", \"api/users\"]. "
    "Use snake_case paths with / separator. If unclear, return [\"general\"]."
)

SUMMARIZE_SYSTEM = (
    "You are a technical documentation assistant. Extract a structured change summary. "
    "Return ONLY valid JSON with these fields: "
    "summary (str), change_type (str: feature|fix|refactor|docs|chore), "
    "affected_components (list[str]), key_decisions (list[str])."
)

APPEND_SYSTEM = (
    "You are a technical wiki maintainer. Write a concise changelog entry for the given change. "
    "Format as 3-5 markdown bullet points. Be specific and factual. "
    "Do not repeat the date or PR number — those are added automatically."
)

CREATE_PAGE_SYSTEM = (
    "You are a senior software architect writing documentation for a codebase module. "
    "Create a comprehensive wiki page in markdown with these exact sections: "
    "## Overview, ## Recent Changes, ## Known Issues, ## Related Modules. "
    "Leave 'Recent Changes' and 'Known Issues' empty — just the headers. "
    "Be factual and concise."
)

SYNTHESIZE_SYSTEM = (
    "You are a technical writer. Synthesize multiple code changes into a comprehensive summary. "
    "Identify architectural patterns, key decisions, and trends. "
    "Format as structured markdown."
)

QUERY_SYSTEM = (
    "You are a search assistant for a technical wiki. "
    "Expand the query into search keywords. "
    "Return ONLY valid JSON: {\"keywords\": [\"...\"], \"module_hints\": [\"...\"]}."
)


def classify_prompt(raw_content: str) -> str:
    return f"Identify the affected modules in this change:\n\n{raw_content[:3000]}"


def summarize_prompt(diff: str, pr_description: str) -> str:
    return f"PR Description:\n{pr_description[:500]}\n\nDiff:\n{diff[:4000]}"


def append_prompt(existing_content: str, change_summary: str, pr_ref: str, date: str) -> str:
    return (
        f"Date: {date}\nPR: {pr_ref}\n\n"
        f"Change Summary:\n{change_summary}\n\n"
        f"Existing wiki content (for context only):\n{existing_content[:2000]}"
    )


def create_page_prompt(module_path: str, events_summary: str) -> str:
    return f"Module: {module_path}\n\nInitial information about this module:\n{events_summary[:2000]}"


def synthesize_prompt(module_path: str, recent_events: list[str]) -> str:
    events_text = "\n---\n".join(recent_events[:10])
    return f"Module: {module_path}\n\nRecent changes:\n{events_text}"


def query_expand_prompt(user_query: str) -> str:
    return f"Expand for technical wiki search: {user_query[:500]}"
