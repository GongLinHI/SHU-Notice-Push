from __future__ import annotations

import argparse
from pathlib import Path

from notice_push.observability.sqlite_backup import backup_sqlite


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a consistent SQLite backup for GitHub Actions.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    return 0 if backup_sqlite(args.source, args.destination) else 1


if __name__ == "__main__":
    raise SystemExit(main())
