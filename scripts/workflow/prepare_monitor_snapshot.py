from __future__ import annotations

import argparse
import os
from pathlib import Path

from notice_push.observability.monitor_snapshot import MonitorSnapshotContext, build_monitor_snapshot
from notice_push.observability.workflow_monitor import WorkflowMonitorDecision
from scripts.workflow._outputs import append_github_outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a canonical snapshot for one monitoring alert.")
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--decision-json", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, default=None)
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    decision = WorkflowMonitorDecision.from_json_text(
        args.decision_json.read_text(encoding="utf-8")
    )
    snapshot = build_monitor_snapshot(
        MonitorSnapshotContext(
            snapshot_root=args.snapshot_root,
            decision=decision,
            evidence_root=args.evidence_root,
        )
    )
    output_path = args.github_output or _environment_output_path()
    append_github_outputs(output_path, {"snapshot_directory": str(snapshot)})
    return 0


def _environment_output_path() -> Path | None:
    value = os.getenv("GITHUB_OUTPUT", "")
    return Path(value) if value else None


if __name__ == "__main__":
    raise SystemExit(main())
