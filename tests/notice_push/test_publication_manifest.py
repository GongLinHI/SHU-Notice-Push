from __future__ import annotations

import pytest

from notice_push.observability.publication import PublicationStatus
from notice_push.observability.publication_manifest import (
    PublicationCounts,
    PublicationManifest,
)


def test_publication_manifest_round_trips_complete_blocked_fallback():
    manifest = PublicationManifest.blocked_fallback(
        report_date="2026-07-10",
        run_id="123",
        workflow_url="https://github.com/example/repo/actions/runs/123",
        trigger="workflow_dispatch",
        git_sha="abc",
        pipeline_exit_code=2,
        blocker="publication_evaluator_failed",
    )

    restored = PublicationManifest.from_json(manifest.to_json())

    assert restored == manifest
    assert restored.status is PublicationStatus.BLOCKED
    assert restored.counts == PublicationCounts()
    assert restored.failure_snapshot_path == "failure-snapshots/2026-07-10/run-123"


def test_publication_manifest_uses_configured_failure_snapshot_branch():
    manifest = PublicationManifest.blocked_fallback(
        report_date="2026-07-10",
        run_id="123",
        workflow_url="https://github.com/example/repo/actions/runs/123",
        trigger="workflow_dispatch",
        git_sha="abc",
        pipeline_exit_code=2,
        blocker="publication_evaluator_failed",
        failure_snapshot_branch="diagnostics/failures",
    )

    assert manifest.failure_snapshot_branch == "diagnostics/failures"


def test_publication_manifest_rejects_incomplete_regular_payload():
    with pytest.raises(ValueError, match="counts"):
        PublicationManifest.from_json({"schema_version": 1})


def test_publication_manifest_rejects_unknown_fields():
    manifest = PublicationManifest.blocked_fallback(
        report_date="2026-07-10",
        run_id="123",
        workflow_url="https://github.com/example/repo/actions/runs/123",
        trigger="workflow_dispatch",
        git_sha="abc",
        pipeline_exit_code=2,
        blocker="publication_evaluator_failed",
    )
    payload = manifest.to_json()
    payload["unexpected"] = "not allowed"

    with pytest.raises(ValueError, match="unexpected fields"):
        PublicationManifest.from_json(payload)


def test_publication_manifest_rejects_unknown_count_fields():
    manifest = PublicationManifest.blocked_fallback(
        report_date="2026-07-10",
        run_id="123",
        workflow_url="https://github.com/example/repo/actions/runs/123",
        trigger="workflow_dispatch",
        git_sha="abc",
        pipeline_exit_code=2,
        blocker="publication_evaluator_failed",
    )
    payload = manifest.to_json()
    counts = payload["counts"]
    assert isinstance(counts, dict)
    counts["unexpected_count"] = 1

    with pytest.raises(ValueError, match="unexpected fields"):
        PublicationManifest.from_json(payload)


def test_publication_manifest_exposes_stable_workflow_outputs():
    manifest = PublicationManifest.blocked_fallback(
        report_date="2026-07-10",
        run_id="123",
        workflow_url="https://github.com/example/repo/actions/runs/123",
        trigger="workflow_dispatch",
        git_sha="abc",
        pipeline_exit_code=1,
        blocker="pipeline_exit_code=2",
    )

    assert manifest.workflow_outputs() == {
        "publication_status": "blocked",
        "publication_blockers": "pipeline_exit_code=2",
        "master_state_updated": "false",
        "report_exists": "false",
        "report_path": "",
        "run_summary_path": "",
        "pipeline_exit_code": "2",
        "snapshot_path": "failure-snapshots/2026-07-10/run-123",
        "artifact_name": "notice-failure-snapshot-2026-07-10-123",
        "new_count": "0",
        "updated_count": "0",
        "retried_count": "0",
        "summarized_count": "0",
        "failed_count": "0",
        "manual_review_count": "0",
        "source_error_count": "0",
        "audit_error_count": "0",
        "audit_warning_count": "0",
        "refresh_seen_error_count": "0",
    }
