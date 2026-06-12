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

CREATE TABLE IF NOT EXISTS etl_staging (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     INTEGER NOT NULL REFERENCES events(id),
    stage_name   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    input_json   TEXT,
    output_json  TEXT,
    error        TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at   TIMESTAMP,
    completed_at TIMESTAMP,
    archived_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS etl_staging_archive (
    id           INTEGER PRIMARY KEY,
    event_id     INTEGER NOT NULL,
    stage_name   TEXT NOT NULL,
    status       TEXT NOT NULL,
    input_json   TEXT,
    output_json  TEXT,
    error        TEXT,
    created_at   TIMESTAMP,
    started_at   TIMESTAMP,
    completed_at TIMESTAMP,
    archived_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_etl_staging_stage_status_archived
    ON etl_staging(stage_name, status, archived_at);

CREATE INDEX IF NOT EXISTS idx_etl_staging_event_stage_status
    ON etl_staging(event_id, stage_name, status);

CREATE INDEX IF NOT EXISTS idx_etl_staging_completed_at
    ON etl_staging(completed_at);

CREATE INDEX IF NOT EXISTS idx_etl_staging_archive_archived_at
    ON etl_staging_archive(archived_at);
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
        # Bootstrap legacy schemas first so archived_at/index DDL can be applied safely.
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                source          TEXT NOT NULL,
                event_type      TEXT NOT NULL,
                raw_json        TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                error           TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at    TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS etl_staging (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id     INTEGER NOT NULL REFERENCES events(id),
                stage_name   TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                input_json   TEXT,
                output_json  TEXT,
                error        TEXT,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at   TIMESTAMP,
                completed_at TIMESTAMP
            );
            """
        )
        # Migration: add parent_event_id to existing databases
        try:
            conn.execute("ALTER TABLE events ADD COLUMN parent_event_id INTEGER REFERENCES events(id)")
        except Exception:
            pass  # column already exists
        # Migration: add archived_at for existing etl_staging tables
        try:
            conn.execute("ALTER TABLE etl_staging ADD COLUMN archived_at TIMESTAMP")
        except Exception:
            pass  # column already exists

        conn.executescript(_SCHEMA)


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


def get_events_in_window(since: str, until: str, limit: int = 100) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM events
            WHERE created_at >= ? AND created_at <= ?
            ORDER BY created_at, id
            LIMIT ?
            """,
            (since, until, limit),
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


def push_staging(
    event_id: int,
    stage_name: str,
    input_json: str = "",
    output_json: str = "",
    status: str = "pending",
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO etl_staging (event_id, stage_name, status, input_json, output_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_id, stage_name, status, input_json, output_json),
        )
        return cursor.lastrowid


def mark_staging_processing(staging_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE etl_staging SET status='processing', started_at=CURRENT_TIMESTAMP WHERE id=?",
            (staging_id,),
        )


def mark_staging_done(staging_id: int, output_json: str = "") -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE etl_staging
            SET status='done',
                output_json=?,
                completed_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (output_json, staging_id),
        )


def mark_staging_failed(staging_id: int, error: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE etl_staging
            SET status='failed',
                error=?,
                completed_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (error, staging_id),
        )


def get_staging_records(
    stage_name: str,
    status: str = "done",
    limit: int = 100,
    hot_only: bool = True,
) -> list[sqlite3.Row]:
    with get_connection() as conn:
        archived_filter = "AND archived_at IS NULL" if hot_only else ""
        return conn.execute(
            f"""
            SELECT *
            FROM etl_staging
            WHERE stage_name=? AND status=? {archived_filter}
            ORDER BY created_at, id
            LIMIT ?
            """,
            (stage_name, status, limit),
        ).fetchall()


def has_staging_record(
    event_id: int,
    stage_name: str,
    status: str = "done",
    hot_only: bool = True,
) -> bool:
    with get_connection() as conn:
        archived_filter = "AND archived_at IS NULL" if hot_only else ""
        row = conn.execute(
            f"""
            SELECT 1
            FROM etl_staging
            WHERE event_id=? AND stage_name=? AND status=? {archived_filter}
            LIMIT 1
            """,
            (event_id, stage_name, status),
        ).fetchone()
    return row is not None


def get_staging_status_counts(hot_only: bool = True) -> dict[str, int]:
    with get_connection() as conn:
        archived_clause = "WHERE archived_at IS NULL" if hot_only else ""
        rows = conn.execute(
            f"SELECT stage_name, status, COUNT(*) AS c FROM etl_staging {archived_clause} GROUP BY stage_name, status"
        ).fetchall()

    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['stage_name']}:{row['status']}"
        counts[key] = row["c"]
    return counts


def get_pending_events_count() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM events WHERE status='pending'").fetchone()[0]


def get_inflight_staging_count() -> int:
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM etl_staging WHERE archived_at IS NULL AND status='processing'"
        ).fetchone()[0]


def get_recent_failed_staging_count(minutes: int = 15) -> int:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT COUNT(*)
            FROM etl_staging
            WHERE archived_at IS NULL
              AND status='failed'
              AND completed_at >= datetime('now', ?)
            """,
            (f"-{minutes} minutes",),
        ).fetchone()[0]


def etl_archive_or_prune(
    older_than_hours: int = 24,
    mode: str = "archive",
    dry_run: bool = True,
) -> int:
    """
    Manage completed ETL staging rows outside the hot table.

    mode:
      - archive: move hot done rows into etl_staging_archive then delete from hot
      - prune: hard-delete hot done rows directly
    """
    if mode not in {"archive", "prune"}:
        raise ValueError("mode must be 'archive' or 'prune'")

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM etl_staging
            WHERE archived_at IS NULL
              AND status='done'
              AND completed_at IS NOT NULL
              AND completed_at < datetime('now', ?)
            ORDER BY id
            """,
            (f"-{older_than_hours} hours",),
        ).fetchall()

        if dry_run:
            return len(rows)

        if not rows:
            return 0

        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)

        if mode == "archive":
            conn.executemany(
                """
                INSERT OR REPLACE INTO etl_staging_archive (
                    id, event_id, stage_name, status, input_json, output_json, error,
                    created_at, started_at, completed_at, archived_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    (
                        row["id"],
                        row["event_id"],
                        row["stage_name"],
                        row["status"],
                        row["input_json"],
                        row["output_json"],
                        row["error"],
                        row["created_at"],
                        row["started_at"],
                        row["completed_at"],
                    )
                    for row in rows
                ],
            )

        conn.execute(f"DELETE FROM etl_staging WHERE id IN ({placeholders})", ids)
        return len(ids)


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
