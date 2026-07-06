from __future__ import annotations

import sqlite3


BASELINE_SCHEMA_VERSION = "2026_07_06_baseline"


def ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists schema_migrations (
            version text primary key,
            applied_at text not null
        )
        """
    )


def record_baseline_migration(conn: sqlite3.Connection, applied_at: str) -> None:
    conn.execute(
        """
        insert or ignore into schema_migrations(version, applied_at)
        values (?, ?)
        """,
        (BASELINE_SCHEMA_VERSION, applied_at),
    )
