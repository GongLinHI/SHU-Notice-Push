from __future__ import annotations

import sqlite3

from notice_push.storage.migrations import ensure_schema_migrations, record_baseline_migration


def initialize_schema(conn: sqlite3.Connection, now: str) -> None:
    ensure_schema_migrations(conn)
    conn.executescript(
        """
        create table if not exists sources (
            id text primary key,
            name text not null,
            base_url text not null,
            list_url text not null,
            enabled integer not null,
            adapter text not null,
            created_at text not null,
            updated_at text not null
        );

        create table if not exists notices (
            id integer primary key autoincrement,
            source_id text not null,
            url text not null,
            canonical_url text not null,
            title text not null,
            list_excerpt text not null default '',
            content text not null default '',
            content_kind text not null default 'text',
            assets_json text not null default '[]',
            attachments_json text not null default '[]',
            published_at text,
            first_seen_at text not null,
            last_seen_at text not null,
            content_hash text not null default '',
            status text not null,
            summary text not null default '',
            summary_model text not null default '',
            summary_prompt_version text not null default '',
            summary_generated_at text,
            detail_fetched_at text,
            error_message text not null default '',
            failure_type text not null default '',
            failure_count integer not null default 0,
            last_failed_at text,
            next_retry_at text,
            foreign key(source_id) references sources(id),
            unique(source_id, canonical_url)
        );

        create index if not exists idx_notices_dates
        on notices(published_at, first_seen_at);
        """
    )
    ensure_notice_columns(conn)
    record_baseline_migration(conn, now)


def ensure_notice_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("pragma table_info(notices)").fetchall()}
    columns = {
        "content_kind": "text not null default 'text'",
        "assets_json": "text not null default '[]'",
        "attachments_json": "text not null default '[]'",
        "failure_type": "text not null default ''",
        "failure_count": "integer not null default 0",
        "last_failed_at": "text",
        "next_retry_at": "text",
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"alter table notices add column {name} {definition}")
