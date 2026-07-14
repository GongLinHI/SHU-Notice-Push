from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from notice_push.observability.failure_snapshot import FailureSnapshotContext, build_failure_snapshot
from notice_push.observability.publication_manifest import PublicationManifest


def _resolve_path(raw_path: str, workspace: Path) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    return path if path.is_absolute() else workspace / path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a self-contained notice pipeline failure snapshot.")
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--pipeline-log", type=Path, required=True)
    parser.add_argument("--publication-json", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--state-path", default="")
    parser.add_argument("--run-summary-path", default="")
    parser.add_argument("--partial-report-path", default="")
    parser.add_argument("--secret-env", action="append", default=[])
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    publication = PublicationManifest.from_json_text(
        args.publication_json.read_text(encoding="utf-8")
    )
    secrets = tuple(os.getenv(name, "") for name in args.secret_env)
    snapshot_path = build_failure_snapshot(
        FailureSnapshotContext(
            snapshot_root=args.snapshot_root,
            report_date=date.fromisoformat(args.report_date),
            run_id=args.run_id,
            pipeline_log_path=args.pipeline_log,
            publication=publication,
            run_summary_path=_resolve_path(args.run_summary_path, args.workspace),
            state_path=_resolve_path(args.state_path, args.workspace),
            partial_report_path=_resolve_path(args.partial_report_path, args.workspace),
            secrets=secrets,
        )
    )
    output_path = args.github_output or Path(os.environ.get("GITHUB_OUTPUT", ""))
    if output_path:
        with output_path.open("a", encoding="utf-8") as stream:
            stream.write(f"snapshot_directory={snapshot_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
