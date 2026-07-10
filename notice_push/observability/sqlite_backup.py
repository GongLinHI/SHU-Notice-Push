from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


def backup_sqlite(source_path: Path, destination_path: Path) -> bool:
    source = Path(source_path)
    destination = Path(destination_path)
    if not source.exists():
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source)) as source_connection, closing(
        sqlite3.connect(destination)
    ) as destination_connection:
        source_connection.backup(destination_connection)
        integrity_check = destination_connection.execute("pragma integrity_check").fetchone()
    if integrity_check is None or integrity_check[0] != "ok":
        raise RuntimeError(f"SQLite backup integrity check failed for {destination}")
    return True
