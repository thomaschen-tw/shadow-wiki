import sqlite3
from contextlib import contextmanager
from pathlib import Path
from scripts.config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    raw_json        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    error           TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at    TIMESTAMP,
    parent_event_id INTEGER REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS modules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    path         TEXT UNIQUE NOT NULL,
    file_path    TEXT NOT NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    summary      TEXT
);

CREATE TABLE IF NOT EXISTS file_hashes (
    path         TEXT PRIMARY KEY,
    hash         TEXT NOT NULL,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(
    module_path,
    content,
    tokenize='trigram'
);
"""


@contextmanager
def get_connection():
    db_path = Path(get_settings().db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(_SCHEMA)
        # Migration: add parent_event_id to existing databases
        try:
            conn.execute("ALTER TABLE events ADD COLUMN parent_event_id INTEGER REFERENCES events(id)")
        except Exception:
            pass  # column already exists


def push_event(
    source: str,
    event_type: str,
    raw_json: str,
    parent_event_id: int | None = None,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO events (source, event_type, raw_json, parent_event_id) VALUES (?, ?, ?, ?)",
            (source, event_type, raw_json, parent_event_id),
        )
        return cursor.lastrowid


def get_pending_events(limit: int = 10) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM events WHERE status='pending' ORDER BY created_at, id LIMIT ?",
            (limit,),
        ).fetchall()


def mark_event_done(event_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE events SET status='done', processed_at=CURRENT_TIMESTAMP WHERE id=?",
            (event_id,),
        )


def mark_event_failed(event_id: int, error: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE events SET status='failed', error=?, processed_at=CURRENT_TIMESTAMP WHERE id=?",
            (error, event_id),
        )


def mark_event_processing(event_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE events SET status='processing' WHERE id=?",
            (event_id,),
        )


def upsert_module(path: str, file_path: str, summary: str | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO modules (path, file_path, summary, last_updated)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(path) DO UPDATE SET
                file_path    = excluded.file_path,
                summary      = COALESCE(excluded.summary, summary),
                last_updated = CURRENT_TIMESTAMP
            """,
            (path, file_path, summary),
        )


def update_fts(module_path: str, content: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM wiki_fts WHERE module_path=?", (module_path,))
        conn.execute(
            "INSERT INTO wiki_fts (module_path, content) VALUES (?, ?)",
            (module_path, content),
        )


def search_modules_fts(query: str, limit: int = 5) -> list[sqlite3.Row]:
    # Escape FTS5 special chars by treating the whole query as a phrase
    escaped = '"' + query.replace('"', '""') + '"'
    _SQL = """
                SELECT module_path,
                       snippet(wiki_fts, 1, '<b>', '</b>', '...', 32) AS snippet
                FROM wiki_fts
                WHERE content MATCH ?
                LIMIT ?
                """
    try:
        with get_connection() as conn:
            rows = conn.execute(_SQL, (escaped, limit)).fetchall()
            if rows:
                return rows
            # Fall back to OR query across individually-escaped tokens
            tokens = query.split()
            if len(tokens) > 1:
                escaped_tokens = ['"' + t.replace('"', '""') + '"' for t in tokens]
                or_query = " OR ".join(escaped_tokens)
                rows = conn.execute(_SQL, (or_query, limit)).fetchall()
            return rows
    except sqlite3.OperationalError:
        return []


def get_pipeline_status() -> dict:
    with get_connection() as conn:
        pending = conn.execute(
            "SELECT COUNT(*) FROM events WHERE status='pending'"
        ).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM events WHERE status='failed'"
        ).fetchone()[0]
        last = conn.execute(
            "SELECT processed_at FROM events WHERE status='done' ORDER BY processed_at DESC LIMIT 1"
        ).fetchone()
        return {
            "pending": pending,
            "failed": failed,
            "last_processed": last["processed_at"] if last else None,
        }


def get_known_file_hashes() -> dict[str, str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT path, hash FROM file_hashes").fetchall()
        return {r["path"]: r["hash"] for r in rows}


def update_file_hash(path: str, hash_value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO file_hashes (path, hash) VALUES (?, ?)",
            (path, hash_value),
        )
