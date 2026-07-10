from __future__ import annotations

import argparse
import json
from pathlib import Path


PUBLICATION_STATUSES = {"published", "no_report", "blocked"}


def publication_result_is_valid(publication_path: Path, github_output_path: Path) -> bool:
    try:
        payload = json.loads(publication_path.read_text(encoding="utf-8"))
        output_lines = github_output_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return False
    status = payload.get("publication_status")
    blockers = payload.get("publication_blockers")
    counts = payload.get("counts")
    failure_detail = payload.get("failure_detail")
    if status not in PUBLICATION_STATUSES:
        return False
    if not isinstance(blockers, list) or not all(isinstance(value, str) for value in blockers):
        return False
    if not isinstance(counts, dict):
        return False
    if not isinstance(failure_detail, str):
        return False
    return f"publication_status={status}" in output_lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate final publication JSON and GitHub outputs.")
    parser.add_argument("--publication-json", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()
    return 0 if publication_result_is_valid(args.publication_json, args.github_output) else 1


if __name__ == "__main__":
    raise SystemExit(main())
