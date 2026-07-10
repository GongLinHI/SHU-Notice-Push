from __future__ import annotations

import subprocess
import json
from pathlib import Path

from notice_push.observability.publication_manifest import PublicationCounts
from notice_push.observability.publication import PublicationFacts, decide_pipeline_publication
from notice_push.observability.publication_manifest import PublicationManifest
from scripts.workflow.publish_master import PublishMasterRequest, main as publish_master_main, publish_master


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _repository(tmp_path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "--bare", "--initial-branch=master", str(remote))
    _git(tmp_path, "clone", str(remote), str(repo))
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    state_path = repo / "resources" / "notice_state.sqlite3"
    state_path.parent.mkdir(parents=True)
    state_path.write_bytes(b"baseline-state")
    _git(repo, "add", "resources/notice_state.sqlite3")
    _git(repo, "commit", "-m", "initial state")
    _git(repo, "push", "-u", "origin", "master")
    return repo, remote


def _request(repo: Path, *, mode: str, report_path: Path | None = None) -> PublishMasterRequest:
    return PublishMasterRequest(
        repository=repo,
        branch="master",
        mode=mode,
        state_path=repo / "resources" / "notice_state.sqlite3",
        report_path=report_path,
        report_date="2026-07-10",
        counts=PublicationCounts(
            new_count=2,
            updated_count=1,
            retried_count=1,
            summarized_count=3,
            failed_count=0,
            manual_review_count=0,
        ),
    )


def test_publish_master_commits_and_pushes_chinese_report_context(tmp_path):
    repo, _ = _repository(tmp_path)
    report_path = repo / "resources" / "results" / "2026-07-10.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("## 日报\n", encoding="utf-8")
    (repo / "resources" / "notice_state.sqlite3").write_bytes(b"updated-state")

    result = publish_master(_request(repo, mode="published", report_path=report_path))

    assert result.status == "succeeded"
    assert result.master_state_updated is True
    subject = _git(repo, "log", "-1", "--format=%s").stdout.strip()
    body = _git(repo, "log", "-1", "--format=%b").stdout
    assert subject == "日报 2026-07-10: 新增 2 更新 1 复核 0 [bot]"
    assert "成功摘要: 3" in body


def test_publish_master_returns_no_changes_without_creating_empty_commit(tmp_path):
    repo, _ = _repository(tmp_path)
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    result = publish_master(_request(repo, mode="no_report"))

    assert result.status == "no_changes"
    assert result.master_state_updated is False
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == before


def test_publish_master_reports_push_failure_without_claiming_remote_update(tmp_path):
    repo, _ = _repository(tmp_path)
    (repo / "resources" / "notice_state.sqlite3").write_bytes(b"unpublished-state")
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    result = publish_master(_request(repo, mode="no_report"))

    assert result.status == "failed"
    assert result.master_state_updated is False
    assert result.error.startswith("git push failed:")
    assert "missing.git" in result.error


def test_publish_master_configures_bot_identity_before_commit(tmp_path):
    repo, _ = _repository(tmp_path)
    _git(repo, "config", "user.name", "")
    _git(repo, "config", "user.email", "")
    (repo / "resources" / "notice_state.sqlite3").write_bytes(b"updated-state")

    result = publish_master(_request(repo, mode="no_report"))

    assert result.status == "succeeded"
    assert _git(repo, "log", "-1", "--format=%an <%ae>").stdout.strip() == (
        "github-actions[bot] <github-actions[bot]@users.noreply.github.com>"
    )


def test_publish_master_cli_reads_candidate_manifest(monkeypatch, tmp_path):
    repo, _ = _repository(tmp_path)
    report_path = repo / "resources" / "results" / "2026-07-10.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("## 日报\n", encoding="utf-8")
    (repo / "resources" / "notice_state.sqlite3").write_bytes(b"updated-state")
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(
        json.dumps(
            PublicationManifest.from_decision(
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
            ).to_json(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result_path = tmp_path / "result.json"
    github_output = tmp_path / "github-output.txt"
    monkeypatch.setattr(
        "sys.argv",
        [
            "publish_master",
            "--repository",
            str(repo),
            "--branch",
            "master",
            "--candidate-publication-json",
            str(candidate_path),
            "--result-json",
            str(result_path),
            "--github-output",
            str(github_output),
        ],
    )

    assert publish_master_main() == 0

    assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "succeeded"
    assert "master_state_updated=true" in github_output.read_text(encoding="utf-8")
