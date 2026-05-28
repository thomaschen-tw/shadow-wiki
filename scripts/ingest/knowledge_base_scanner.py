#!/usr/bin/env python3
"""
Obsidian knowledge base scanner.

Scans KNOWLEDGE_BASE_PATH (your vault's wiki/ subfolder) for new or meaningfully
changed markdown files. Uses two-stage change detection to avoid redundant LLM calls:

  Stage 1 — MD5 gate: skip files whose bytes haven't changed at all.
  Stage 2 — Similarity gate: skip files whose token overlap with the last processed
             snapshot exceeds KNOWLEDGE_BASE_SIMILARITY_THRESHOLD (default 0.85).

Only files that pass both gates are pushed as events to the SQLite queue.

Usage:
  uv run python scripts/ingest/knowledge_base_scanner.py --once
  uv run python scripts/ingest/knowledge_base_scanner.py --dry-run
  uv run python scripts/ingest/knowledge_base_scanner.py --watch
  uv run python scripts/ingest/knowledge_base_scanner.py --force  # ignore hashes
"""
import argparse
import hashlib
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import frontmatter

from scripts.config import get_settings
from scripts.db import get_connection, get_known_file_hashes, init_db, push_event, update_file_hash

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_SNAPSHOT_PREFIX = "kb_snapshot:"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def _normalize(text: str) -> set[str]:
    """Return bag-of-words for similarity comparison (lowercase, no punctuation)."""
    return set(re.sub(r"[^\w\s]", " ", text.lower()).split())


def _similarity(new_text: str, snapshot_hash: str) -> float:
    """
    Token overlap ratio between new_text and stored snapshot.
    snapshot_hash is stored as the normalized text joined by space (hashed for storage key).
    We re-normalize new_text and compare against the stored snapshot words.
    """
    # We store the snapshot as "kb_snapshot_text:{path}" → normalized text
    return 0.0   # calculated below with stored text; placeholder


def _get_snapshot_text(abs_path: str) -> str | None:
    """Retrieve previously stored normalized snapshot text from DB."""
    key = f"{_SNAPSHOT_PREFIX}text:{abs_path}"
    with get_connection() as conn:
        row = conn.execute("SELECT hash FROM file_hashes WHERE path=?", (key,)).fetchone()
    return row["hash"] if row else None


def _save_snapshot(abs_path: str, normalized_text: str) -> None:
    """Store normalized text as the snapshot for similarity comparison."""
    # We reuse the file_hashes table with a text: prefix key.
    # The 'hash' column stores the normalized text (may exceed typical hash length but SQLite is flexible).
    key = f"{_SNAPSHOT_PREFIX}text:{abs_path}"
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO file_hashes (path, hash) VALUES (?, ?)",
            (key, normalized_text[:4000]),   # cap at 4000 chars to keep DB lean
        )


def _compute_similarity(new_words: set[str], snapshot_text: str | None) -> float:
    if not snapshot_text or not new_words:
        return 0.0
    old_words = set(snapshot_text.split())
    if not old_words:
        return 0.0
    overlap = len(new_words & old_words)
    return overlap / max(len(new_words), 1)


def _extract_title(post: frontmatter.Post, path: Path) -> str:
    """Title from frontmatter > first H1 > filename."""
    if post.get("title"):
        return str(post["title"])
    for line in post.content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").replace("_", " ").title()


def _wiki_category(rel_path: Path) -> str:
    """Return first path component as category (concepts, comparisons, entities, summaries)."""
    parts = rel_path.parts
    return parts[0] if len(parts) > 1 else "general"


# ── Core scan ─────────────────────────────────────────────────────────────────

def scan_once(dry_run: bool = False, force: bool = False) -> int:
    s = get_settings()
    base = Path(s.knowledge_base_path)

    if not base.exists():
        logger.error("KNOWLEDGE_BASE_PATH does not exist: %s", base)
        return 0

    exts = {e.strip() for e in s.knowledge_base_extensions.split(",")}
    threshold = s.knowledge_base_similarity_threshold

    known_hashes = get_known_file_hashes()
    queued = 0
    skipped_unchanged = 0
    skipped_similar = 0

    for file_path in sorted(base.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix not in exts:
            continue
        # Skip Obsidian internal files
        if any(part.startswith(".") for part in file_path.parts):
            continue

        abs_str = str(file_path)
        rel_path = file_path.relative_to(base)

        try:
            raw_text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.warning("Cannot read %s: %s", file_path, exc)
            continue

        # Stage 1 — MD5 gate
        current_md5 = _md5(raw_text)
        if not force and known_hashes.get(abs_str) == current_md5:
            skipped_unchanged += 1
            continue

        # Stage 2 — Similarity gate
        new_words = _normalize(raw_text)
        snapshot_text = _get_snapshot_text(abs_str)
        similarity = _compute_similarity(new_words, snapshot_text)

        if not force and similarity > threshold:
            logger.debug("Skipping %s (similarity=%.2f > %.2f)", rel_path, similarity, threshold)
            skipped_similar += 1
            # Still update MD5 so we don't re-check next run
            if not dry_run:
                update_file_hash(abs_str, current_md5)
            continue

        # Parse frontmatter
        try:
            post = frontmatter.loads(raw_text)
        except Exception:
            post = frontmatter.Post(raw_text)

        title = _extract_title(post, file_path)
        category = _wiki_category(rel_path)
        tags = post.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]

        change_type = "new" if known_hashes.get(abs_str) is None else "updated"

        event_payload = {
            "file_path": abs_str,
            "relative_path": str(rel_path),
            "wiki_category": category,
            "title": title,
            "content": post.content[:8000],
            "tags": tags,
            "source_url": str(post.get("source") or post.get("url") or ""),
            "published": str(post.get("published") or post.get("created") or ""),
            "change_type": change_type,
            "similarity": round(similarity, 3),
        }

        if dry_run:
            logger.info("[DRY-RUN] Would queue: %s  (%s, similarity=%.2f)",
                        rel_path, change_type, similarity)
        else:
            import json
            push_event("knowledge_base", "note", json.dumps(event_payload))
            update_file_hash(abs_str, current_md5)
            normalized_joined = " ".join(sorted(new_words))
            _save_snapshot(abs_str, normalized_joined)
            logger.info("Queued %s  (%s, similarity=%.2f)", rel_path, change_type, similarity)

        queued += 1

    logger.info(
        "Scan complete: %d queued, %d skipped (unchanged), %d skipped (similar)",
        queued, skipped_unchanged, skipped_similar,
    )
    return queued


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Scan Obsidian knowledge base for changed notes")
    parser.add_argument("--once",     action="store_true", help="Single scan pass then exit")
    parser.add_argument("--watch",    action="store_true", help="Loop continuously")
    parser.add_argument("--interval", type=int, default=3600, help="Watch interval in seconds (default: 3600)")
    parser.add_argument("--force",    action="store_true", help="Ignore hashes, re-queue all files")
    parser.add_argument("--dry-run",  action="store_true", help="Print what would be queued, no DB writes")
    args = parser.parse_args()

    s = get_settings()
    if not s.knowledge_base_path:
        logger.error("KNOWLEDGE_BASE_PATH not set in .env")
        sys.exit(1)

    if not args.dry_run:
        init_db()

    logger.info("Knowledge base scanner  path=%s  threshold=%.2f",
                s.knowledge_base_path, s.knowledge_base_similarity_threshold)

    scan_once(dry_run=args.dry_run, force=args.force)

    if args.watch:
        logger.info("Watch mode — scanning every %ds (Ctrl+C to stop)", args.interval)
        while True:
            time.sleep(args.interval)
            scan_once(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
