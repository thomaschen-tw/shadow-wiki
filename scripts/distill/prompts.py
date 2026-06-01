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

REVIEW_SYNTHESIS_SYSTEM = (
    "You are a technical wiki maintainer. Summarise a code review discussion into a concise changelog entry. "
    "Format as 2-4 markdown bullet points capturing: what was reviewed, key feedback, and the outcome. "
    "Do not repeat the date, PR number, or reviewer name — those are added automatically."
)

RUNBOOK_SYSTEM = (
    "You are a senior site reliability engineer writing operational runbooks. "
    "Based on the module's wiki content, write a practical runbook with numbered step-by-step procedures. "
    "Include: prerequisites, steps, expected outcomes, and rollback instructions where applicable. "
    "Focus on patterns visible in Known Issues and Recent Changes. "
    "Format as structured markdown with a short intro followed by numbered procedure blocks."
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


def review_synthesis_prompt(reviewer: str, state: str, body: str, pr_title: str) -> str:
    return (
        f"PR: {pr_title}\n"
        f"Reviewer: {reviewer} — {state}\n"
        f"Review body:\n{body[:2000]}"
    )


def runbook_prompt(module_path: str, module_content: str) -> str:
    return (
        f"Module: {module_path}\n\n"
        f"Wiki content:\n{module_content[:3000]}"
    )


def query_expand_prompt(user_query: str) -> str:
    return f"Expand for technical wiki search: {user_query[:500]}"


# ── Knowledge base prompts ────────────────────────────────────────────────────

KNOWLEDGE_CLASSIFY_SYSTEM = (
    "You are a knowledge base organiser. Given the title, category hint, and content of a wiki note, "
    "assign it to 1-2 topic paths in a personal knowledge wiki. "
    "Return ONLY a JSON array of paths starting with 'knowledge/', e.g. "
    '[\"knowledge/ai/rag\", \"knowledge/tools/obsidian\"]. '
    "Use the category hint as the first path component unless a better fit exists. "
    "Paths must be lowercase, hyphen-separated, max 3 levels deep."
)

KNOWLEDGE_SUMMARIZE_SYSTEM = (
    "You are a knowledge distillation assistant. Extract the most valuable information from a wiki note. "
    "Return ONLY valid JSON with these fields: "
    "insights (list of 3-5 concise, standalone insight statements), "
    "key_concepts (list of important terms or concepts), "
    "important_quotes (list of 0-2 verbatim notable quotes), "
    "tags (list of 3-6 topic tags)."
)

KNOWLEDGE_CREATE_PAGE_SYSTEM = (
    "You are a knowledge wiki author. Create a structured wiki page summarising a topic. "
    "Use these exact sections: "
    "## Overview (2-3 sentences defining the topic), "
    "## Key Concepts (bullet list of core ideas), "
    "## Key Insights (bullet list of most valuable takeaways), "
    "## Sources (bullet list with any source URLs), "
    "## Related Topics (bullet list of related knowledge paths). "
    "Be concise. Write in English unless the source content is primarily Chinese, in which case match the language."
)

KNOWLEDGE_APPEND_SYSTEM = (
    "You are a knowledge wiki maintainer. Write 2-4 new bullet points to prepend to the Key Insights section. "
    "Each bullet must be a standalone insight not already present in the existing page. "
    "Be specific and factual. Do not repeat the date or source — those are added automatically."
)


def knowledge_classify_prompt(title: str, content: str, category: str, tags: list[str]) -> str:
    tag_hint = f"Tags: {', '.join(tags)}\n" if tags else ""
    return (
        f"Title: {title}\n"
        f"Category hint: {category}\n"
        f"{tag_hint}"
        f"Content (excerpt):\n{content[:400]}"
    )


def knowledge_summarize_prompt(title: str, content: str) -> str:
    return f"Title: {title}\n\nContent:\n{content[:5000]}"


def knowledge_create_page_prompt(topic_path: str, title: str, content: str) -> str:
    return (
        f"Topic path: {topic_path}\n"
        f"Source note title: {title}\n\n"
        f"Source content:\n{content[:4000]}"
    )


def knowledge_append_prompt(
    existing_content: str, insights: list[str], source_title: str, date: str
) -> str:
    insights_text = "\n".join(f"- {i}" for i in insights[:5])
    return (
        f"Date: {date}\nSource: {source_title}\n\n"
        f"New insights to incorporate:\n{insights_text}\n\n"
        f"Existing page content (for context — do not repeat):\n{existing_content[:1500]}"
    )
