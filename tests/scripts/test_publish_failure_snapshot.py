from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import scripts.workflow.publish_failure_snapshot as publisher_module
from scripts.workflow.publish_failure_snapshot import SnapshotPublishRequest, publish_failure_snapshot


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _checkout(tmp_path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    _git(tmp_path, "init", "--bare", "--initial-branch=master", str(remote))
    _git(tmp_path, "clone", str(remote), str(seed))
    _git(seed, "config", "user.name", "Test User")
    _git(seed, "config", "user.email", "test@example.com")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "push", "-u", "origin", "master")
    _git(tmp_path, "clone", str(remote), str(checkout))
    return checkout, remote


def _source_snapshot(tmp_path, *, run_id: str = "123") -> Path:
    source = tmp_path / f"run-{run_id}"
    source.mkdir()
    (source / "publication.json").write_text('{"schema_version": 1}\n', encoding="utf-8")
    (source / "notice_pipeline.log").write_text("pipeline failed\n", encoding="utf-8")
    return source


def _request(checkout: Path, source: Path, *, run_id: str = "123") -> SnapshotPublishRequest:
    return SnapshotPublishRequest(
        checkout=checkout,
        source_snapshot=source,
        branch="bot/failure-snapshots",
        report_date=date(2026, 7, 10),
        run_id=run_id,
        retention_days=90,
        max_scan_entries=200,
        pipeline_exit_code=2,
        source_error_count=1,
        audit_error_count=0,
        artifact_name=f"notice-failure-snapshot-2026-07-10-{run_id}",
        blockers=("pipeline_exit_code=2",),
    )


def test_publish_failure_snapshot_creates_orphan_branch_and_commits_snapshot(tmp_path):
    checkout, _ = _checkout(tmp_path)
    source = _source_snapshot(tmp_path)

    result = publish_failure_snapshot(_request(checkout, source))

    assert result.status == "succeeded"
    assert (checkout / "failure-snapshots" / "2026-07-10" / "run-123" / "notice_pipeline.log").exists()
    assert _git(checkout, "branch", "--show-current").stdout.strip() == "bot/failure-snapshots"
    assert "异常快照 2026-07-10" in _git(checkout, "log", "-1", "--format=%s").stdout


def test_publish_failure_snapshot_adds_second_run_to_existing_branch(tmp_path):
    checkout, _ = _checkout(tmp_path)

    assert publish_failure_snapshot(_request(checkout, _source_snapshot(tmp_path, run_id="123"), run_id="123")).status == "succeeded"
    result = publish_failure_snapshot(_request(checkout, _source_snapshot(tmp_path, run_id="456"), run_id="456"))

    assert result.status == "succeeded"
    assert (checkout / "failure-snapshots" / "2026-07-10" / "run-123").exists()
    assert (checkout / "failure-snapshots" / "2026-07-10" / "run-456").exists()


def test_publish_failure_snapshot_reports_push_failure_without_overwriting_source(tmp_path):
    checkout, _ = _checkout(tmp_path)
    source = _source_snapshot(tmp_path)
    _git(checkout, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    result = publish_failure_snapshot(_request(checkout, source))

    assert result.status == "failed"
    assert result.error == "git inspect snapshot branch failed"
    assert (source / "notice_pipeline.log").read_text(encoding="utf-8") == "pipeline failed\n"


def test_publish_failure_snapshot_retries_one_failed_push(monkeypatch, tmp_path):
    checkout, _ = _checkout(tmp_path)
    assert publish_failure_snapshot(
        _request(checkout, _source_snapshot(tmp_path, run_id="123"), run_id="123")
    ).status == "succeeded"
    original_git = publisher_module._git
    push_count = 0

    def fail_first_push(repository, *args):
        nonlocal push_count
        if args and args[0] == "push":
            push_count += 1
            if push_count == 1:
                return publisher_module._GitResult(1, "", "non-fast-forward")
        return original_git(repository, *args)

    monkeypatch.setattr(publisher_module, "_git", fail_first_push)

    result = publish_failure_snapshot(
        _request(checkout, _source_snapshot(tmp_path, run_id="456"), run_id="456")
    )

    assert result.status == "succeeded"
    assert push_count == 2


def test_publish_failure_snapshot_aborts_failed_rebase(monkeypatch, tmp_path):
    checkout, _ = _checkout(tmp_path)
    assert publish_failure_snapshot(
        _request(checkout, _source_snapshot(tmp_path, run_id="123"), run_id="123")
    ).status == "succeeded"
    original_git = publisher_module._git
    commands = []

    def fail_push_and_rebase(repository, *args):
        commands.append(args)
        if args and args[0] == "push":
            return publisher_module._GitResult(1, "", "non-fast-forward")
        if args[:1] == ("rebase",) and args[1:] != ("--abort",):
            return publisher_module._GitResult(1, "", "conflict")
        return original_git(repository, *args)

    monkeypatch.setattr(publisher_module, "_git", fail_push_and_rebase)

    result = publish_failure_snapshot(
        _request(checkout, _source_snapshot(tmp_path, run_id="456"), run_id="456")
    )

    assert result.status == "failed"
    assert result.error == "git rebase after push failure failed"
    assert ("rebase", "--abort") in commands
