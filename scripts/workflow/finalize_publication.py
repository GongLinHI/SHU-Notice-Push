from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from notice_push.observability.publication import PublicationStatus
from notice_push.observability.publication_manifest import FAILURE_SNAPSHOT_BRANCH, PublicationManifest


def load_candidate_or_fallback(
    *,
    candidate_path: Path,
    report_date: str,
    run_id: str,
    workflow_url: str,
    trigger: str,
    git_sha: str,
    raw_exit_code: int,
    failure_snapshot_branch: str = FAILURE_SNAPSHOT_BRANCH,
) -> PublicationManifest:
    try:
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        return PublicationManifest.from_json(payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return PublicationManifest.blocked_fallback(
            report_date=report_date,
            run_id=run_id,
            workflow_url=workflow_url,
            trigger=trigger,
            git_sha=git_sha,
            pipeline_exit_code=raw_exit_code,
            blocker="publication_evaluator_failed",
            failure_snapshot_branch=failure_snapshot_branch,
        )


def finalize_publication(
    candidate: PublicationManifest,
    *,
    render_html_status: str,
    master_publish_status: str,
    master_state_updated: bool,
    master_publish_error: str = "",
) -> PublicationManifest:
    if candidate.status is PublicationStatus.BLOCKED:
        return replace(
            candidate,
            master_state_updated=candidate.master_state_updated or master_state_updated,
        )
    if candidate.status is PublicationStatus.PUBLISHED and render_html_status not in {"success", "succeeded"}:
        return _block(candidate, "html_render_failed", master_state_updated=master_state_updated)
    if master_publish_status not in {"succeeded", "no_changes"}:
        return _block(
            candidate,
            "master_publish_failed",
            master_state_updated=master_state_updated,
            failure_detail=master_publish_error,
        )
    return replace(candidate, master_state_updated=master_state_updated)


def _block(
    candidate: PublicationManifest,
    blocker: str,
    *,
    master_state_updated: bool,
    failure_detail: str = "",
) -> PublicationManifest:
    return replace(
        candidate,
        status=PublicationStatus.BLOCKED,
        blockers=(blocker,),
        master_state_updated=master_state_updated,
        report_email_sent=False,
        alert_email_requested=True,
        failure_snapshot_push_status="pending",
        failure_snapshot_path=f"failure-snapshots/{candidate.report_date}/run-{candidate.workflow_run_id}",
        artifact_name=f"notice-failure-snapshot-{candidate.report_date}-{candidate.workflow_run_id}",
        failure_detail=failure_detail,
    )


def _write_outputs(path: Path | None, outputs: dict[str, str]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as stream:
        for key, value in outputs.items():
            stream.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize notice publication after render and master publication.")
    parser.add_argument("--candidate-publication-json", type=Path, required=True)
    parser.add_argument("--publication-json", type=Path, required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workflow-url", required=True)
    parser.add_argument("--trigger", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--failure-snapshot-branch", default=FAILURE_SNAPSHOT_BRANCH)
    parser.add_argument("--raw-exit-code", type=int, required=True)
    parser.add_argument("--render-html-status", required=True)
    parser.add_argument("--master-publish-status", required=True)
    parser.add_argument("--master-state-updated", choices=("true", "false"), required=True)
    parser.add_argument("--master-publish-error", default="")
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    candidate = load_candidate_or_fallback(
        candidate_path=args.candidate_publication_json,
        report_date=args.report_date,
        run_id=args.run_id,
        workflow_url=args.workflow_url,
        trigger=args.trigger,
        git_sha=args.git_sha,
        raw_exit_code=args.raw_exit_code,
        failure_snapshot_branch=args.failure_snapshot_branch,
    )
    manifest = finalize_publication(
        candidate,
        render_html_status=args.render_html_status,
        master_publish_status=args.master_publish_status,
        master_state_updated=args.master_state_updated == "true",
        master_publish_error=args.master_publish_error,
    )
    args.publication_json.parent.mkdir(parents=True, exist_ok=True)
    args.publication_json.write_text(
        json.dumps(manifest.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output_path = args.github_output or _github_output_path()
    _write_outputs(output_path, manifest.workflow_outputs())
    return 0


def _github_output_path() -> Path | None:
    value = os.environ.get("GITHUB_OUTPUT", "")
    return Path(value) if value else None


if __name__ == "__main__":
    raise SystemExit(main())
