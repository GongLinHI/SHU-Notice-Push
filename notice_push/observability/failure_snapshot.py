from __future__ import annotations

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from notice_push.observability.publication_manifest import PublicationManifest
from notice_push.observability.sqlite_backup import backup_sqlite


DATE_DIRECTORY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BEIJING_TIMEZONE = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class FailureSnapshotContext:
    snapshot_root: Path
    report_date: date
    run_id: str
    pipeline_log_path: Path
    publication: PublicationManifest
    run_summary_path: Path | None = None
    state_path: Path | None = None
    partial_report_path: Path | None = None
    secrets: tuple[str, ...] = ()


@dataclass(frozen=True)
class SnapshotCleanupResult:
    removed: tuple[Path, ...]
    scanned_entry_count: int
    limit_exceeded: bool


def build_failure_snapshot(context: FailureSnapshotContext) -> Path:
    destination = (
        Path(context.snapshot_root)
        / "failure-snapshots"
        / context.report_date.isoformat()
        / f"run-{context.run_id}"
    )
    destination.mkdir(parents=True, exist_ok=True)
    write_sanitized_log(context.pipeline_log_path, destination / "notice_pipeline.log", context.secrets)
    state_snapshot_available, state_snapshot_failed = _backup_state_snapshot(
        context.state_path,
        destination / "notice_state.sqlite3",
    )
    blockers = context.publication.blockers
    if state_snapshot_failed and "state_snapshot_backup_failed" not in blockers:
        blockers = (*blockers, "state_snapshot_backup_failed")
    snapshot_publication = replace(
        context.publication,
        blockers=blockers,
        state_snapshot_available=state_snapshot_available,
    )
    _copy_or_write_summary(
        context.run_summary_path,
        destination / "run_summary.json",
        snapshot_publication,
        context.secrets,
    )

    if context.partial_report_path and context.partial_report_path.is_file():
        write_sanitized_log(
            context.partial_report_path,
            destination / "partial_report.md",
            context.secrets,
        )

    publication_payload = snapshot_publication.to_json()
    _write_json(destination / "publication.json", publication_payload)
    _write_metadata(destination / "metadata.md", snapshot_publication, state_snapshot_available)
    return destination


def _backup_state_snapshot(state_path: Path | None, destination: Path) -> tuple[bool, bool]:
    if state_path is None:
        return False, False
    try:
        return backup_sqlite(state_path, destination), False
    except (OSError, RuntimeError, sqlite3.Error):
        destination.unlink(missing_ok=True)
        return False, True


def cleanup_expired_snapshot_dates(
    root: Path,
    *,
    today: date,
    retention_days: int,
    max_scan_entries: int,
) -> SnapshotCleanupResult:
    snapshots_root = Path(root)
    if not snapshots_root.exists():
        return SnapshotCleanupResult(removed=(), scanned_entry_count=0, limit_exceeded=False)
    date_directories = tuple(
        child
        for child in sorted(snapshots_root.iterdir())
        if child.is_dir() and DATE_DIRECTORY_RE.fullmatch(child.name)
    )
    if len(date_directories) > max(0, max_scan_entries):
        return SnapshotCleanupResult(
            removed=(),
            scanned_entry_count=len(date_directories),
            limit_exceeded=True,
        )
    cutoff = today - timedelta(days=max(0, retention_days))
    removed: list[Path] = []
    for child in date_directories:
        try:
            snapshot_date = date.fromisoformat(child.name)
        except ValueError:
            continue
        if snapshot_date < cutoff:
            shutil.rmtree(child)
            removed.append(child)
    return SnapshotCleanupResult(
        removed=tuple(removed),
        scanned_entry_count=len(date_directories),
        limit_exceeded=False,
    )


def write_sanitized_log(source: Path, destination: Path, secrets: tuple[str, ...]) -> None:
    text = _read_sanitized_text(source, secrets)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def _read_sanitized_text(source: Path, secrets: tuple[str, ...]) -> str:
    text = Path(source).read_text(encoding="utf-8", errors="replace") if Path(source).is_file() else ""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def _copy_or_write_summary(
    source: Path | None,
    destination: Path,
    publication: PublicationManifest,
    secrets: tuple[str, ...],
) -> None:
    if source and Path(source).is_file():
        text = _read_sanitized_text(source, secrets)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(payload, dict):
                destination.write_text(text, encoding="utf-8")
                return
    _write_json(
        destination,
        {
            "schema_version": 2,
            "report_date": publication.report_date,
            "publication_eligibility": publication.status.value,
            "publication_blockers": list(publication.blockers),
            "pipeline_exit_code": publication.pipeline_exit_code,
            "pipeline_log_path": "notice_pipeline.log",
            "counts": publication.counts.to_json(),
            "fallback": True,
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_metadata(path: Path, publication: PublicationManifest, state_snapshot_available: bool) -> None:
    blockers_text = ", ".join(publication.blockers) if publication.blockers else "无"
    created_at = datetime.now(BEIJING_TIMEZONE).isoformat(timespec="seconds")
    lines = [
        "# 通知推送异常快照",
        "",
        f"- 生成时间（北京时间）: {created_at}",
        f"- 报告日期: {publication.report_date}",
        f"- Workflow Run ID: {publication.workflow_run_id}",
        f"- Workflow: {publication.workflow_url}",
        f"- 触发方式: {publication.trigger}",
        f"- Git SHA: {publication.git_sha}",
        f"- 发布状态: {publication.status.value}",
        f"- 阻断原因: {blockers_text}",
        f"- 失败详情: {publication.failure_detail or '无'}",
        f"- Pipeline 退出码: {publication.pipeline_exit_code}",
        f"- Artifact: {publication.artifact_name}",
        f"- SQLite 状态库快照: {'可用' if state_snapshot_available else '不可用'}",
        "",
        "## 运行计数",
        "",
    ]
    for key, value in sorted(publication.counts.to_json().items()):
        lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
