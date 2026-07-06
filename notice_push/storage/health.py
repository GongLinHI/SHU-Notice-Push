from __future__ import annotations

import sqlite3


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            "select 1 from sqlite_master where type = 'table' and name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def table_count(conn: sqlite3.Connection, table_name: str) -> int:
    if not table_exists(conn, table_name):
        return 0
    return int(conn.execute(f"select count(*) from {table_name}").fetchone()[0])


def storage_health(conn: sqlite3.Connection) -> tuple[int, int, tuple[str, ...]]:
    source_count = table_count(conn, "sources")
    notice_count = table_count(conn, "notices")
    schema_versions = (
        tuple(
            row["version"]
            for row in conn.execute(
                "select version from schema_migrations order by applied_at, version"
            ).fetchall()
        )
        if table_exists(conn, "schema_migrations")
        else ()
    )
    return source_count, notice_count, schema_versions
