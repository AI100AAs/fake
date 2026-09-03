from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from flask import current_app, g

SCHEMA_MIGRATIONS = {
    1: """
CREATE TABLE IF NOT EXISTS sample_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    description TEXT NOT NULL,
    accent_color TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    radius REAL NOT NULL DEFAULT 0.11,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
""",
    2: """
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
""",
    3: """
ALTER TABLE article_history ADD COLUMN owner_token TEXT NOT NULL DEFAULT '';
""",
}
LATEST_SCHEMA_VERSION = max(SCHEMA_MIGRATIONS)
BUSY_TIMEOUT_MS = 10_000
WRITE_RETRY_DELAYS = (0.05, 0.15, 0.35)


def _connect(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return connection


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _applied_migrations(connection: sqlite3.Connection) -> set[int]:
    rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(row["version"]) for row in rows}


def _apply_migrations(connection: sqlite3.Connection) -> None:
    _ensure_migration_table(connection)
    applied = _applied_migrations(connection)

    for version, sql in sorted(SCHEMA_MIGRATIONS.items()):
        if version in applied:
            continue
        try:
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                f"{sql}\n"
                f"INSERT INTO schema_migrations (version) VALUES ({int(version)});\n"
                "COMMIT;"
            )
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = _connect(str(current_app.config["DB_PATH"]))
    return g.db


def close_db(_: BaseException | None = None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def initialize_database(config: dict) -> None:
    connection = _connect(str(config["DB_PATH"]))
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS article_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                input_type TEXT NOT NULL CHECK (input_type IN ('text', 'url')),
                source_url TEXT NOT NULL DEFAULT '',
                article_text TEXT NOT NULL,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        _apply_migrations(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                source_url TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


def schema_version(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0] or 0)


def verify_database_schema(config: dict) -> None:
    connection = _connect(str(config["DB_PATH"]))
    try:
        current_version = schema_version(connection)
    finally:
        connection.close()
    if current_version != LATEST_SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema is version {current_version}; expected {LATEST_SCHEMA_VERSION}. "
            "Run: python server/manage.py init-db"
        )


def database_readiness(config: dict) -> tuple[bool, dict[str, Any]]:
    try:
        connection = _connect(str(config["DB_PATH"]))
        try:
            connection.execute("SELECT 1").fetchone()
            current_version = schema_version(connection)
            connection.execute("PRAGMA busy_timeout = 1000")
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return False, {"database": "unavailable", "detail": str(exc)}

    ready = current_version == LATEST_SCHEMA_VERSION
    return ready, {
        "database": "ready" if ready else "schema-outdated",
        "schemaVersion": current_version,
        "expectedSchemaVersion": LATEST_SCHEMA_VERSION,
    }


def backup_database(config: dict, output_path: Path) -> Path:
    source_path = Path(config["DB_PATH"])
    if not source_path.exists():
        raise FileNotFoundError(f"Database does not exist: {source_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source = _connect(str(source_path))
    destination = sqlite3.connect(output_path)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()
    return output_path


def fetch_sample_nodes(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, slug, label, description, accent_color, x, y, radius, created_at
        FROM sample_nodes
        ORDER BY id
        LIMIT 500
        """
    ).fetchall()
    return [dict(row) for row in rows]


def search_sample_nodes(connection: sqlite3.Connection, query: str, limit: int = 8) -> list[dict[str, Any]]:
    term = query.strip().lower()
    if not term:
        return []

    rows = connection.execute(
        """
        SELECT id, slug, label, description, accent_color, x, y, radius, created_at
        FROM sample_nodes
        WHERE lower(slug) LIKE ?
           OR lower(label) LIKE ?
           OR lower(description) LIKE ?
        ORDER BY id
        LIMIT ?
        """,
        (f"%{term}%", f"%{term}%", f"%{term}%", limit),
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_article_history(connection: sqlite3.Connection, owner_token: str, limit: int = 30) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, input_type, source_url, article_text, report_json, created_at
        FROM article_history
        WHERE owner_token = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (owner_token, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def delete_article_history(connection: sqlite3.Connection, owner_token: str) -> int:
    cursor = connection.execute("DELETE FROM article_history WHERE owner_token = ?", (owner_token,))
    connection.commit()
    return cursor.rowcount


def insert_article_history(connection: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    cursor = connection.execute(
        """
        INSERT INTO article_history (owner_token, input_type, source_url, article_text, report_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (payload["owner_token"], payload["input_type"], payload["source_url"], payload["article_text"], payload["report_json"]),
    )
    connection.commit()
    row = connection.execute(
        """
        SELECT id, input_type, source_url, article_text, report_json, created_at
        FROM article_history WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return dict(row)


def fetch_knowledge_entries(connection: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, title, source_url, notes, created_at
        FROM knowledge_entries
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def insert_knowledge_entry(connection: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    cursor = connection.execute(
        """
        INSERT INTO knowledge_entries (title, source_url, notes)
        VALUES (?, ?, ?)
        """,
        (payload["title"], payload["source_url"], payload["notes"]),
    )
    connection.commit()
    row = connection.execute(
        """
        SELECT id, title, source_url, notes, created_at
        FROM knowledge_entries WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return dict(row)


def delete_knowledge_entry(connection: sqlite3.Connection, entry_id: int) -> bool:
    cursor = connection.execute("DELETE FROM knowledge_entries WHERE id = ?", (entry_id,))
    connection.commit()
    return cursor.rowcount > 0


def insert_sample_node(connection: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    parameters = (
        payload["slug"],
        payload["label"],
        payload["description"],
        payload["accent_color"],
        payload["x"],
        payload["y"],
        payload["radius"],
    )
    for delay in (*WRITE_RETRY_DELAYS, None):
        try:
            cursor = connection.execute(
                """
                INSERT INTO sample_nodes (slug, label, description, accent_color, x, y, radius)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                parameters,
            )
            connection.commit()
            break
        except sqlite3.OperationalError as exc:
            connection.rollback()
            if "locked" not in str(exc).lower() or delay is None:
                raise
            time.sleep(delay)

    row = connection.execute(
        """
        SELECT id, slug, label, description, accent_color, x, y, radius, created_at
        FROM sample_nodes
        WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return dict(row)


def database_summary(config: dict) -> dict[str, Any]:
    connection = _connect(str(config["DB_PATH"]))
    try:
        count = connection.execute("SELECT COUNT(*) FROM sample_nodes").fetchone()[0]
        state_count = connection.execute("SELECT COUNT(*) FROM app_state").fetchone()[0]
        event_count = connection.execute("SELECT COUNT(*) FROM app_events").fetchone()[0]
        history_count = connection.execute("SELECT COUNT(*) FROM article_history").fetchone()[0]
        knowledge_count = connection.execute("SELECT COUNT(*) FROM knowledge_entries").fetchone()[0]
        current_schema_version = schema_version(connection)
    finally:
        connection.close()

    return {
        "database_path": str(config["DB_PATH"]),
        "sample_node_count": count,
        "app_state_count": state_count,
        "app_event_count": event_count,
        "article_history_count": history_count,
        "knowledge_entry_count": knowledge_count,
        "schema_version": current_schema_version,
    }
