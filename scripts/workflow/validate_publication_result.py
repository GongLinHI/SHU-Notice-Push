from __future__ import annotations

import argparse
from pathlib import Path

from notice_push.observability.publication_manifest import PublicationManifest


def publication_result_is_valid(publication_path: Path, github_output_path: Path) -> bool:
    try:
        publication = PublicationManifest.from_json_text(
            publication_path.read_text(encoding="utf-8")
        )
        output_lines = github_output_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError, ValueError):
        return False
    return f"publication_status={publication.status.value}" in output_lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate final publication JSON and GitHub outputs."
    )
    parser.add_argument("--publication-json", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()
    return 0 if publication_result_is_valid(args.publication_json, args.github_output) else 1


if __name__ == "__main__":
    raise SystemExit(main())
