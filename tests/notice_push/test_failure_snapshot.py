import json
import sqlite3
from datetime import date

from notice_push.observability.failure_snapshot import (
    FailureSnapshotContext,
    build_failure_snapshot,
    cleanup_expired_snapshot_dates,
)
from notice_push.observability.publication_manifest import PublicationCounts, PublicationManifest


def _context(tmp_path, *, state_path=None, run_summary_path=None, report_path=None, secrets=()):
    log_path = tmp_path / "notice_pipeline.log"
    log_path.write_text("pipeline failed\napi key=secret-value\n", encoding="utf-8")
    return FailureSnapshotContext(
        snapshot_root=tmp_path / "snapshot",
        report_date=date(2026, 7, 10),
        run_id="123456789",
        pipeline_log_path=log_path,
        run_summary_path=run_summary_path,
        state_path=state_path,
        partial_report_path=report_path,
        publication=PublicationManifest.blocked_fallback(
            report_date="2026-07-10",
            run_id="123456789",
            workflow_url="https://github.com/example/repo/actions/runs/123456789",
            trigger="schedule",
            git_sha="abc123",
            pipeline_exit_code=2,
            blocker="pipeline_exit_code=2",
            counts=PublicationCounts(source_error_count=1),
        ),
        secrets=secrets,
    )


def test_build_failure_snapshot_redacts_log_creates_fallback_and_copies_sqlite(tmp_path):
    state_path = tmp_path / "state.sqlite3"
    with sqlite3.connect(state_path) as connection:
        connection.execute("create table notices (id integer primary key, title text)")
        connection.execute("insert into notices(title) values ('测试通知')")
    report_path = tmp_path / "partial.md"
    report_path.write_text("## 部分日报\nsecret-value\n", encoding="utf-8")

    snapshot_path = build_failure_snapshot(
        _context(
            tmp_path,
            state_path=state_path,
            report_path=report_path,
            secrets=("secret-value",),
        )
    )

    assert snapshot_path == tmp_path / "snapshot" / "failure-snapshots" / "2026-07-10" / "run-123456789"
    assert "secret-value" not in (snapshot_path / "notice_pipeline.log").read_text(encoding="utf-8")
    assert "***" in (snapshot_path / "notice_pipeline.log").read_text(encoding="utf-8")
    partial_report = (snapshot_path / "partial_report.md").read_text(encoding="utf-8")
    assert partial_report == "## 部分日报\n***\n"
    assert json.loads((snapshot_path / "run_summary.json").read_text(encoding="utf-8"))["schema_version"] == 2
    assert json.loads((snapshot_path / "run_summary.json").read_text(encoding="utf-8"))["pipeline_log_path"] == "notice_pipeline.log"
    assert json.loads((snapshot_path / "publication.json").read_text(encoding="utf-8"))["state_snapshot_available"] is True
    snapshot_manifest = PublicationManifest.from_json(
        json.loads((snapshot_path / "publication.json").read_text(encoding="utf-8"))
    )
    assert snapshot_manifest.state_snapshot_available is True
    assert "生成时间（北京时间）:" in (snapshot_path / "metadata.md").read_text(encoding="utf-8")
    with sqlite3.connect(snapshot_path / "notice_state.sqlite3") as connection:
        assert connection.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert connection.execute("select title from notices").fetchone()[0] == "测试通知"


def test_build_failure_snapshot_replaces_non_contract_summary_and_handles_missing_state(tmp_path):
    run_summary_path = tmp_path / "summary.json"
    run_summary_path.write_text(
        '{"schema_version": 2, "existing": true, "error": "secret-value"}\n',
        encoding="utf-8",
    )

    snapshot_path = build_failure_snapshot(
        _context(
            tmp_path,
            run_summary_path=run_summary_path,
            secrets=("secret-value",),
        )
    )

    summary = json.loads((snapshot_path / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["fallback"] is True
    assert "secret-value" not in (snapshot_path / "run_summary.json").read_text(encoding="utf-8")
    assert not (snapshot_path / "notice_state.sqlite3").exists()
    manifest = json.loads((snapshot_path / "publication.json").read_text(encoding="utf-8"))
    assert manifest["state_snapshot_available"] is False
    assert "SQLite 状态库快照: 不可用" in (snapshot_path / "metadata.md").read_text(encoding="utf-8")


def test_build_failure_snapshot_treats_directory_inputs_as_missing_optional_files(tmp_path):
    snapshot_path = build_failure_snapshot(
        _context(
            tmp_path,
            run_summary_path=tmp_path,
            report_path=tmp_path,
        )
    )

    summary = json.loads((snapshot_path / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["fallback"] is True
    assert summary["pipeline_log_path"] == "notice_pipeline.log"
    assert not (snapshot_path / "partial_report.md").exists()


def test_build_failure_snapshot_replaces_invalid_run_summary_with_fallback(tmp_path):
    run_summary_path = tmp_path / "summary.json"
    run_summary_path.write_text("{not-valid-json", encoding="utf-8")

    snapshot_path = build_failure_snapshot(
        _context(tmp_path, run_summary_path=run_summary_path)
    )

    summary = json.loads((snapshot_path / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["fallback"] is True
    assert summary["pipeline_log_path"] == "notice_pipeline.log"


def test_build_failure_snapshot_survives_invalid_sqlite_backup(tmp_path):
    state_path = tmp_path / "invalid.sqlite3"
    state_path.write_bytes(b"not a sqlite database")

    snapshot_path = build_failure_snapshot(_context(tmp_path, state_path=state_path))

    manifest = json.loads((snapshot_path / "publication.json").read_text(encoding="utf-8"))
    assert manifest["state_snapshot_available"] is False
    assert "state_snapshot_backup_failed" in manifest["publication_blockers"]
    assert not (snapshot_path / "notice_state.sqlite3").exists()
    assert "state_snapshot_backup_failed" in (snapshot_path / "metadata.md").read_text(encoding="utf-8")


def test_cleanup_expired_snapshot_dates_only_removes_valid_old_dates(tmp_path):
    root = tmp_path / "failure-snapshots"
    for name in ("2026-04-10", "2026-04-11", "2026-07-10", "not-a-date"):
        (root / name / "run-1").mkdir(parents=True)

    result = cleanup_expired_snapshot_dates(root, today=date(2026, 7, 10), retention_days=90, max_scan_entries=200)

    assert result.removed == (root / "2026-04-10",)
    assert result.limit_exceeded is False
    assert not (root / "2026-04-10").exists()
    assert (root / "2026-04-11").exists()
    assert (root / "2026-07-10").exists()
    assert (root / "not-a-date").exists()


def test_cleanup_preserves_all_dates_when_scan_limit_is_exceeded(tmp_path):
    root = tmp_path / "failure-snapshots"
    for name in ("2026-01-01", "2026-01-02", "2026-01-03"):
        (root / name / "run-1").mkdir(parents=True)

    result = cleanup_expired_snapshot_dates(
        root,
        today=date(2026, 7, 10),
        retention_days=90,
        max_scan_entries=2,
    )

    assert result.limit_exceeded is True
    assert result.removed == ()
    assert (root / "2026-01-01").exists()
