from __future__ import annotations

import argparse
import os
from pathlib import Path

from notice_push.observability.failure_snapshot import write_sanitized_log


def main() -> int:
    parser = argparse.ArgumentParser(description="Redact configured secrets from a pipeline log.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--secret-env", action="append", default=[])
    args = parser.parse_args()

    secrets = tuple(os.getenv(name, "") for name in args.secret_env)
    write_sanitized_log(args.source, args.destination, secrets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
