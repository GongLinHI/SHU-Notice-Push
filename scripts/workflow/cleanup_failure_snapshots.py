from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from notice_push.observability.failure_snapshot import cleanup_expired_snapshot_dates


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete expired date directories from a failure snapshot branch.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--today", required=True)
    parser.add_argument("--retention-days", type=int, default=90)
    parser.add_argument("--max-scan-entries", type=int, default=200)
    args = parser.parse_args()
    result = cleanup_expired_snapshot_dates(
        args.root,
        today=date.fromisoformat(args.today),
        retention_days=args.retention_days,
        max_scan_entries=args.max_scan_entries,
    )
    for path in result.removed:
        print(path)
    if result.limit_exceeded:
        print(
            f"warning: preserved failure snapshots because {result.scanned_entry_count} date directories "
            f"exceed max_scan_entries={args.max_scan_entries}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
