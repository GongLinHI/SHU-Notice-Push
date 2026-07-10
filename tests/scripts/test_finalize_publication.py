from __future__ import annotations

from notice_push.observability.publication import PublicationFacts, decide_pipeline_publication
from notice_push.observability.publication_manifest import PublicationCounts, PublicationManifest
from scripts.workflow.finalize_publication import finalize_publication, load_candidate_or_fallback
from scripts.workflow.validate_publication_result import publication_result_is_valid
from scripts.workflow.write_blocked_publication_fallback import main as fallback_main


def _candidate() -> PublicationManifest:
    return PublicationManifest.from_decision(
        report_date="2026-07-10",
        run_id="123",
        workflow_url="https://github.com/example/repo/actions/runs/123",
        trigger="workflow_dispatch",
        git_sha="abc",
        pipeline_exit_code=0,
        decision=decide_pipeline_publication(
            PublicationFacts(report_path="resources/results/2026-07-10.md", source_error_count=0, audit_error_count=0)
        ),
        counts=PublicationCounts(new_count=1, summarized_count=1),
        report_path="resources/results/2026-07-10.md",
        report_exists=True,
        run_summary_path="resources/results/json/2026-07-10.json",
    )


def test_load_candidate_or_fallback_blocks_when_candidate_is_missing(tmp_path):
    manifest = load_candidate_or_fallback(
        candidate_path=tmp_path / "missing.json",
        report_date="2026-07-10",
        run_id="123",
        workflow_url="https://github.com/example/repo/actions/runs/123",
        trigger="workflow_dispatch",
        git_sha="abc",
        raw_exit_code=1,
    )

    assert manifest.status.value == "blocked"
    assert manifest.blockers == ("publication_evaluator_failed",)
    assert manifest.pipeline_exit_code == 2


def test_finalize_publication_blocks_master_push_failure():
    manifest = finalize_publication(
        _candidate(),
        render_html_status="succeeded",
        master_publish_status="failed",
        master_state_updated=False,
        master_publish_error="git push failed: remote rejected",
    )

    assert manifest.status.value == "blocked"
    assert manifest.blockers == ("master_publish_failed",)
    assert manifest.alert_email_requested is True
    assert manifest.failure_detail == "git push failed: remote rejected"


def test_finalize_publication_accepts_github_success_outcome():
    manifest = finalize_publication(
        _candidate(),
        render_html_status="success",
        master_publish_status="succeeded",
        master_state_updated=True,
    )

    assert manifest.status.value == "published"
    assert manifest.blockers == ()
    assert manifest.master_state_updated is True


def test_finalize_publication_preserves_known_master_update_when_later_step_fails():
    manifest = finalize_publication(
        _candidate(),
        render_html_status="success",
        master_publish_status="failed",
        master_state_updated=True,
        master_publish_error="result serialization failed after push",
    )

    assert manifest.status.value == "blocked"
    assert manifest.master_state_updated is True


def test_finalize_publication_merges_known_master_update_into_blocked_candidate():
    candidate = PublicationManifest.blocked_fallback(
        report_date="2026-07-10",
        run_id="123",
        workflow_url="https://github.com/example/repo/actions/runs/123",
        trigger="workflow_dispatch",
        git_sha="abc",
        pipeline_exit_code=2,
        blocker="publication_evaluator_failed",
    )

    manifest = finalize_publication(
        candidate,
        render_html_status="success",
        master_publish_status="succeeded",
        master_state_updated=True,
    )

    assert manifest.status.value == "blocked"
    assert manifest.master_state_updated is True


def test_finalize_publication_preserves_no_report_without_master_change():
    candidate = PublicationManifest.from_decision(
        report_date="2026-07-10",
        run_id="123",
        workflow_url="https://github.com/example/repo/actions/runs/123",
        trigger="workflow_dispatch",
        git_sha="abc",
        pipeline_exit_code=1,
        decision=decide_pipeline_publication(PublicationFacts(report_path="", source_error_count=0, audit_error_count=0)),
        counts=PublicationCounts(),
        report_path="",
        report_exists=False,
        run_summary_path="resources/results/json/2026-07-10.json",
    )

    manifest = finalize_publication(
        candidate,
        render_html_status="skipped",
        master_publish_status="no_changes",
        master_state_updated=False,
    )

    assert manifest.status.value == "no_report"
    assert manifest.master_state_updated is False


def test_fallback_cli_overwrites_candidate_with_complete_blocked_manifest(monkeypatch, tmp_path):
    publication_path = tmp_path / "publication.json"
    github_output = tmp_path / "github-output.txt"
    monkeypatch.setattr(
        "sys.argv",
        [
            "write_blocked_publication_fallback",
            "--report-date",
            "2026-07-10",
            "--run-id",
            "123",
            "--workflow-url",
            "https://github.com/example/repo/actions/runs/123",
            "--trigger",
            "workflow_dispatch",
            "--git-sha",
            "abc",
            "--blocker",
            "publication_evaluator_failed",
            "--publication-json",
            str(publication_path),
            "--github-output",
            str(github_output),
        ],
    )

    assert fallback_main() == 0

    manifest = PublicationManifest.from_json(__import__("json").loads(publication_path.read_text(encoding="utf-8")))
    assert manifest.blockers == ("publication_evaluator_failed",)
    assert "publication_status=blocked" in github_output.read_text(encoding="utf-8")


def test_fallback_cli_supports_initial_output_prefix(monkeypatch, tmp_path):
    publication_path = tmp_path / "candidate.json"
    github_output = tmp_path / "github-output.txt"
    monkeypatch.setattr(
        "sys.argv",
        [
            "write_blocked_publication_fallback",
            "--report-date",
            "2026-07-10",
            "--run-id",
            "123",
            "--workflow-url",
            "https://github.com/example/repo/actions/runs/123",
            "--trigger",
            "workflow_dispatch",
            "--git-sha",
            "abc",
            "--blocker",
            "publication_evaluator_failed",
            "--output-prefix",
            "initial_",
            "--publication-json",
            str(publication_path),
            "--github-output",
            str(github_output),
        ],
    )

    assert fallback_main() == 0

    output = github_output.read_text(encoding="utf-8")
    assert "initial_publication_status=blocked" in output
    assert "publication_status=blocked" not in output.splitlines()


def test_fallback_cli_preserves_known_master_update(monkeypatch, tmp_path):
    publication_path = tmp_path / "publication.json"
    github_output = tmp_path / "github-output.txt"
    monkeypatch.setattr(
        "sys.argv",
        [
            "write_blocked_publication_fallback",
            "--report-date",
            "2026-07-10",
            "--run-id",
            "123",
            "--workflow-url",
            "https://github.com/example/repo/actions/runs/123",
            "--trigger",
            "workflow_dispatch",
            "--git-sha",
            "abc",
            "--blocker",
            "publication_finalizer_failed",
            "--master-state-updated",
            "true",
            "--publication-json",
            str(publication_path),
            "--github-output",
            str(github_output),
        ],
    )

    assert fallback_main() == 0

    manifest = PublicationManifest.from_json(__import__("json").loads(publication_path.read_text(encoding="utf-8")))
    assert manifest.master_state_updated is True
    assert "master_state_updated=true" in github_output.read_text(encoding="utf-8")


def test_publication_result_validator_requires_matching_manifest_and_output(tmp_path):
    publication_path = tmp_path / "publication.json"
    publication_path.write_text(__import__("json").dumps(_candidate().to_json()), encoding="utf-8")
    github_output = tmp_path / "github-output.txt"
    github_output.write_text("publication_status=published\n", encoding="utf-8")

    assert publication_result_is_valid(publication_path, github_output) is True

    github_output.write_text("new_count=1\n", encoding="utf-8")
    assert publication_result_is_valid(publication_path, github_output) is False

    publication_path.write_text("not-json", encoding="utf-8")
    assert publication_result_is_valid(publication_path, github_output) is False
