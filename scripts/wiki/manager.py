import copy
from datetime import datetime
from pathlib import Path
import frontmatter
from scripts.config import get_settings
from scripts.db import upsert_module, update_fts

_DEFAULT_METADATA = {
    "module": "",
    "last_updated": "",
    "recent_prs": [],
    "owners": [],
    "known_issues": [],
    "slack_threads": [],
    "tags": [],
}


def _module_file(module_path: str) -> Path:
    return Path(get_settings().wiki_dir) / f"{module_path}.md"


def module_exists(module_path: str) -> bool:
    return _module_file(module_path).exists()


def read_module(module_path: str) -> frontmatter.Post | None:
    path = _module_file(module_path)
    if not path.exists():
        return None
    return frontmatter.load(str(path))


def _save_and_index(module_path: str, post: frontmatter.Post, summary: str | None = None) -> None:
    path = _module_file(module_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    upsert_module(module_path, str(path), summary)
    update_fts(module_path, post.content)


def create_module(module_path: str, body: str, summary: str | None = None) -> None:
    post = frontmatter.Post(
        body,
        **{
            **copy.deepcopy(_DEFAULT_METADATA),
            "module": module_path,
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
        },
    )
    _save_and_index(module_path, post, summary)


def append_to_section(
    module_path: str, section: str, content: str, pr_number: str | None = None
) -> None:
    post = read_module(module_path)
    if post is None:
        raise FileNotFoundError(f"Module '{module_path}' does not exist")

    header = f"## {section}"
    body = post.content

    if header not in body:
        body += f"\n\n{header}\n\n"

    insert_at = body.index(header) + len(header)
    next_section = body.find("\n## ", insert_at)

    date_str = datetime.now().strftime("%Y-%m-%d")
    entry = f"\n\n### {date_str}"
    if pr_number:
        entry += f" ({pr_number})"
    entry += f"\n\n{content}\n"

    # Always insert right after the section header (newest entry first / top-prepend)
    body = body[:insert_at] + entry + body[insert_at:]

    post.content = body
    post["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    if pr_number:
        existing = post.get("recent_prs", [])
        if pr_number not in existing:
            post["recent_prs"] = [pr_number] + existing[:9]

    _save_and_index(module_path, post)


def update_frontmatter(module_path: str, updates: dict) -> None:
    post = read_module(module_path)
    if post is None:
        raise FileNotFoundError(f"Module '{module_path}' does not exist")
    for key, value in updates.items():
        post[key] = value
    _save_and_index(module_path, post)
