from __future__ import annotations

import argparse
import re
from pathlib import Path


DATE_STEM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_empty_result_report(filename: str, content: str) -> bool:
    path = Path(filename)
    report_date = path.stem
    if path.suffix.lower() != ".md" or not DATE_STEM_RE.fullmatch(report_date):
        return False

    normalized = content.strip()
    patterns = (
        rf"^##\s+No new notices found today \({re.escape(report_date)}\)\.$",
        rf"^{re.escape(report_date)}没有新通知\.$",
    )
    return any(re.fullmatch(pattern, normalized) for pattern in patterns)


def find_empty_result_files(results_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in results_dir.glob("*.md")
        if path.is_file() and is_empty_result_report(path.name, path.read_text(encoding="utf-8-sig"))
    )


def clean_empty_results(results_dir: Path, dry_run: bool = True) -> list[Path]:
    matches = find_empty_result_files(results_dir)
    if not dry_run:
        for path in matches:
            path.unlink()
    return matches


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove generated Markdown reports that only say no notices were found.",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("resources/results"),
        help="Directory containing date-named Markdown result files.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete matching files. Without this flag, only print a dry-run preview.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    matches = clean_empty_results(args.results_dir, dry_run=not args.delete)
    action = "Deleted" if args.delete else "Would delete"
    print(f"{action} {len(matches)} empty result file(s).")
    for path in matches:
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
