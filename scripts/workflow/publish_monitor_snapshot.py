from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from notice_push.observability.snapshot_publisher import (
    SnapshotPublishRequest,
    publish_failure_snapshot,
)
from notice_push.observability.workflow_monitor import WorkflowMonitorDecision
from scripts.workflow._outputs import append_github_outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a monitor snapshot to its isolated branch.")
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--source-snapshot", type=Path, required=True)
    parser.add_argument("--decision-json", type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--retention-days", type=int, required=True)
    parser.add_argument("--max-scan-entries", type=int, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    decision = WorkflowMonitorDecision.from_json_text(
        args.decision_json.read_text(encoding="utf-8")
    )
    counts = decision.counts
    result = publish_failure_snapshot(
        SnapshotPublishRequest(
            checkout=args.checkout,
            source_snapshot=args.source_snapshot,
            branch=args.branch,
            report_date=date.fromisoformat(decision.report_date),
            run_id=decision.source_run_key,
            retention_days=args.retention_days,
            max_scan_entries=args.max_scan_entries,
            pipeline_exit_code=decision.pipeline_exit_code,
            source_error_count=counts.source_error_count if counts else None,
            audit_error_count=counts.audit_error_count if counts else None,
            artifact_name=f"notice-monitor-snapshot-{decision.report_date}-{decision.source_run_key}",
            blockers=decision.blockers,
            failure_type=decision.failure_type.value if decision.failure_type else "unknown_failure",
        )
    )
    args.result_json.parent.mkdir(parents=True, exist_ok=True)
    args.result_json.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    append_github_outputs(
        args.github_output,
        {
            "status": result.status,
            "cleanup_limit_exceeded": str(result.cleanup_limit_exceeded).lower(),
            "error": result.error,
        },
    )
    return 0 if result.status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
