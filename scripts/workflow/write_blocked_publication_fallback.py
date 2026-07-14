from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


COUNT_KEYS = (
    "new_count",
    "updated_count",
    "retried_count",
    "summarized_count",
    "failed_count",
    "manual_review_count",
    "source_error_count",
    "audit_error_count",
    "audit_warning_count",
    "refresh_seen_error_count",
)
FAILURE_SNAPSHOT_BRANCH = "bot/failure-snapshots"


def _manifest(args) -> dict[str, object]:
    snapshot_path = f"failure-snapshots/{args.report_date}/run-{args.run_id}"
    return {
        "schema_version": 1,
        "report_date": args.report_date,
        "workflow_run_id": args.run_id,
        "workflow_url": args.workflow_url,
        "trigger": args.trigger,
        "git_sha": args.git_sha,
        "pipeline_exit_code": 2,
        "publication_status": "blocked",
        "publication_blockers": [args.blocker],
        "counts": {key: 0 for key in COUNT_KEYS},
        "report_path": "",
        "report_exists": False,
        "run_summary_path": "",
        "master_state_updated": args.master_state_updated == "true",
        "report_email_sent": False,
        "alert_email_requested": True,
        "failure_snapshot_push_status": "pending",
        "failure_snapshot_branch": args.failure_snapshot_branch,
        "failure_snapshot_path": snapshot_path,
        "artifact_name": f"notice-failure-snapshot-{args.report_date}-{args.run_id}",
        "failure_detail": "",
    }


def _write_outputs(path: Path, manifest: dict[str, object], *, prefix: str) -> None:
    counts = manifest["counts"]
    assert isinstance(counts, dict)
    outputs = {
        "publication_status": "blocked",
        "publication_blockers": ",".join(manifest["publication_blockers"]),
        "master_state_updated": str(manifest["master_state_updated"]).lower(),
        "report_exists": "false",
        "report_path": "",
        "run_summary_path": "",
        "pipeline_exit_code": "2",
        "snapshot_path": str(manifest["failure_snapshot_path"]),
        "artifact_name": str(manifest["artifact_name"]),
        **{key: str(counts[key]) for key in COUNT_KEYS},
    }
    with path.open("a", encoding="utf-8") as stream:
        for key, value in outputs.items():
            stream.write(f"{prefix}{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write a minimal blocked publication manifest for workflow recovery."
    )
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workflow-url", required=True)
    parser.add_argument("--trigger", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--blocker", required=True)
    parser.add_argument("--master-state-updated", choices=("true", "false"), default="false")
    parser.add_argument("--failure-snapshot-branch", default=FAILURE_SNAPSHOT_BRANCH)
    parser.add_argument("--output-prefix", default="")
    parser.add_argument("--publication-json", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    manifest = _manifest(args)
    args.publication_json.parent.mkdir(parents=True, exist_ok=True)
    args.publication_json.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    output_path = args.github_output or (Path(github_output) if github_output else None)
    if output_path:
        _write_outputs(output_path, manifest, prefix=args.output_prefix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
