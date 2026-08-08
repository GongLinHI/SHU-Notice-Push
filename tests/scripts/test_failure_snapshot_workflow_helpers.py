import json
from pathlib import Path

from scripts.workflow.build_failure_snapshot import main as build_snapshot_main
from scripts.workflow.evaluate_publication import main as evaluate_publication_main
from scripts.workflow.sanitize_pipeline_log import main as sanitize_log_main
from notice_push.observability.publication_manifest import PublicationCounts, PublicationManifest


def _blocked_manifest_payload(*, run_id: str = "123") -> dict[str, object]:
    return PublicationManifest.blocked_fallback(
        report_date="2026-07-10",
        run_id=run_id,
        workflow_url=f"https://github.com/example/repo/actions/runs/{run_id}",
        trigger="schedule",
        git_sha="abc",
        pipeline_exit_code=2,
        blocker="pipeline_exit_code=2",
        counts=PublicationCounts(),
    ).to_json()


def test_evaluate_publication_cli_writes_outputs_and_fallback_manifest(monkeypatch, tmp_path):
    log_path = tmp_path / "pipeline.log"
    log_path.write_text("Traceback: startup failed\n", encoding="utf-8")
    publication_path = tmp_path / "publication.json"
    github_output = tmp_path / "github-output.txt"
    monkeypatch.setattr(
        "sys.argv",
        [
            "evaluate_publication",
            "--pipeline-log",
            str(log_path),
            "--raw-exit-code",
            "1",
            "--workspace",
            str(tmp_path),
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
            "--candidate-publication-json",
            str(publication_path),
            "--github-output",
            str(github_output),
        ],
    )

    assert evaluate_publication_main() == 0

    manifest = json.loads(publication_path.read_text(encoding="utf-8"))
    assert manifest["publication_status"] == "blocked"
    assert manifest["publication_blockers"] == ["pipeline_exit_code=2"]
    assert "initial_publication_status=blocked" in github_output.read_text(encoding="utf-8")


def test_failure_snapshot_helper_handles_missing_summary(monkeypatch, tmp_path):
    log_path = tmp_path / "pipeline.log"
    log_path.write_text("KIMI_API_KEY=visible-secret\n", encoding="utf-8")
    publication_path = tmp_path / "publication.json"
    publication_path.write_text(
        json.dumps(_blocked_manifest_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    github_output = tmp_path / "github-output.txt"
    monkeypatch.setenv("KIMI_API_KEY", "visible-secret")
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_failure_snapshot",
            "--snapshot-root",
            str(tmp_path / "snapshots"),
            "--report-date",
            "2026-07-10",
            "--run-id",
            "123",
            "--pipeline-log",
            str(log_path),
            "--publication-json",
            str(publication_path),
            "--workspace",
            str(tmp_path),
            "--secret-env",
            "KIMI_API_KEY",
            "--github-output",
            str(github_output),
        ],
    )

    assert build_snapshot_main() == 0
    snapshot = Path(github_output.read_text(encoding="utf-8").strip().split("=", 1)[1])
    assert "visible-secret" not in (snapshot / "notice_pipeline.log").read_text(encoding="utf-8")


def test_sanitize_pipeline_log_cli_redacts_configured_secrets(monkeypatch, tmp_path):
    source = tmp_path / "pipeline.log"
    source.write_text("token=visible-secret\n", encoding="utf-8")
    destination = tmp_path / "sanitized" / "pipeline.log"
    monkeypatch.setenv("KIMI_API_KEY", "visible-secret")
    monkeypatch.setattr(
        "sys.argv",
        [
            "sanitize_pipeline_log",
            "--source",
            str(source),
            "--destination",
            str(destination),
            "--secret-env",
            "KIMI_API_KEY",
        ],
    )

    assert sanitize_log_main() == 0
    assert destination.read_text(encoding="utf-8") == "token=***\n"


def test_sanitize_pipeline_log_cli_treats_directory_source_as_missing(monkeypatch, tmp_path):
    destination = tmp_path / "sanitized" / "pipeline.log"
    monkeypatch.setattr(
        "sys.argv",
        [
            "sanitize_pipeline_log",
            "--source",
            str(tmp_path),
            "--destination",
            str(destination),
        ],
    )

    assert sanitize_log_main() == 0
    assert destination.read_text(encoding="utf-8") == ""
