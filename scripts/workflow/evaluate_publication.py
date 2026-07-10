from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

from notice_push.observability.publication import (
    PublicationDecision,
    PublicationFacts,
    WorkflowPublicationInput,
    decide_pipeline_publication,
    decide_workflow_publication,
)
from notice_push.observability.publication_manifest import PublicationCounts, PublicationManifest


COUNTER_KEYS = (
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


@dataclass(frozen=True)
class PipelineOutputEvaluation:
    decision: PublicationDecision
    pipeline_exit_code: int
    counters: PublicationCounts
    report_path: str
    report_exists: bool
    run_summary_path: str


def evaluate_pipeline_output(output: str, *, raw_exit_code: int, workspace: Path) -> PipelineOutputEvaluation:
    values = _parse_key_value_lines(output)
    counters, expected_counts_present = _parse_counters(values)
    report_path = values.get("report_path", "")
    report_exists = bool(report_path and (Path(workspace) / report_path).is_file())
    pipeline_decision = None
    if expected_counts_present:
        pipeline_decision = decide_pipeline_publication(
            PublicationFacts(
                report_path=report_path if report_exists else "",
                source_error_count=counters.source_error_count,
                audit_error_count=counters.audit_error_count,
            )
        )
    decision = decide_workflow_publication(
        WorkflowPublicationInput(
            raw_exit_code=raw_exit_code,
            expected_counts_present=expected_counts_present,
            pipeline_decision=pipeline_decision,
        )
    )
    if raw_exit_code == 0 and expected_counts_present and report_path and not report_exists:
        decision = decide_workflow_publication(
            WorkflowPublicationInput(raw_exit_code=2, expected_counts_present=False, pipeline_decision=None)
        )
    return PipelineOutputEvaluation(
        decision=decision,
        pipeline_exit_code=raw_exit_code if raw_exit_code in (0, 1) and expected_counts_present else 2,
        counters=counters,
        report_path=report_path,
        report_exists=report_exists,
        run_summary_path=values.get("run_summary_path", ""),
    )


def _parse_key_value_lines(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator and key:
            values[key] = value
    return values


def _parse_counters(values: dict[str, str]) -> tuple[PublicationCounts, bool]:
    counters: dict[str, int] = {}
    complete = True
    for key in COUNTER_KEYS:
        try:
            counters[key] = int(values[key])
        except (KeyError, ValueError):
            counters[key] = 0
            complete = False
    return PublicationCounts(**counters), complete


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate one notice pipeline run for GitHub Actions publication.")
    parser.add_argument("--pipeline-log", type=Path, required=True)
    parser.add_argument("--raw-exit-code", type=int, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workflow-url", required=True)
    parser.add_argument("--trigger", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--failure-snapshot-branch", default="bot/failure-snapshots")
    parser.add_argument("--candidate-publication-json", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    output = args.pipeline_log.read_text(encoding="utf-8", errors="replace") if args.pipeline_log.exists() else ""
    evaluation = evaluate_pipeline_output(output, raw_exit_code=args.raw_exit_code, workspace=args.workspace)
    publication = PublicationManifest.from_decision(
        report_date=args.report_date,
        run_id=args.run_id,
        workflow_url=args.workflow_url,
        trigger=args.trigger,
        git_sha=args.git_sha,
        pipeline_exit_code=evaluation.pipeline_exit_code,
        decision=evaluation.decision,
        counts=evaluation.counters,
        report_path=evaluation.report_path,
        report_exists=evaluation.report_exists,
        run_summary_path=evaluation.run_summary_path,
        failure_snapshot_branch=args.failure_snapshot_branch,
    )
    args.candidate_publication_json.parent.mkdir(parents=True, exist_ok=True)
    args.candidate_publication_json.write_text(
        json.dumps(publication.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    output_path = args.github_output or Path(os.environ.get("GITHUB_OUTPUT", ""))
    if output_path:
        lines = publication.workflow_outputs(prefix="initial_")
        with output_path.open("a", encoding="utf-8") as stream:
            for key, value in lines.items():
                stream.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
