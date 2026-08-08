from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

from notice_push.observability.failure_snapshot import cleanup_expired_snapshot_dates
from notice_push.observability.workflow_monitor import MonitorFailureType, failure_type_label


SnapshotPublishStatus = Literal["succeeded", "failed"]


@dataclass(frozen=True)
class SnapshotPublishRequest:
    checkout: Path
    source_snapshot: Path
    branch: str
    report_date: date
    run_id: str
    retention_days: int
    max_scan_entries: int
    pipeline_exit_code: int | None
    source_error_count: int | None
    audit_error_count: int | None
    artifact_name: str
    blockers: tuple[str, ...]
    failure_type: str = MonitorFailureType.BUSINESS_BLOCKED.value


class SnapshotPublishResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: SnapshotPublishStatus
    error: StrictStr = ""
    cleanup_limit_exceeded: StrictBool = False


def publish_failure_snapshot(request: SnapshotPublishRequest) -> SnapshotPublishResult:
    checkout = Path(request.checkout).resolve()
    source_snapshot = Path(request.source_snapshot).resolve()
    if not checkout.is_dir() or not source_snapshot.is_dir():
        return _failure("checkout or source snapshot directory is missing")
    for command in (
        ("config", "user.name", "github-actions[bot]"),
        ("config", "user.email", "github-actions[bot]@users.noreply.github.com"),
    ):
        if not _git(checkout, *command).success:
            return _failure("git configuration failed")
    branch_result = _checkout_snapshot_branch(checkout, request.branch)
    if branch_result is not None:
        return branch_result

    relative_target = Path("failure-snapshots") / request.report_date.isoformat() / f"run-{request.run_id}"
    target = checkout / relative_target
    if target.exists():
        if _same_monitor_decision(source_snapshot, target):
            return SnapshotPublishResult(status="succeeded")
        return _failure("snapshot target already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_snapshot, target)

    cleanup = cleanup_expired_snapshot_dates(
        checkout / "failure-snapshots",
        today=request.report_date,
        retention_days=request.retention_days,
        max_scan_entries=request.max_scan_entries,
    )
    add_paths = [str(relative_target), *(str(path.relative_to(checkout)) for path in cleanup.removed)]
    if not _git(checkout, "add", "--", *add_paths).success:
        return _failure("git add failed", cleanup.limit_exceeded)
    if _git(checkout, "diff", "--cached", "--quiet").returncode == 0:
        return _failure("failure snapshot staging is empty", cleanup.limit_exceeded)

    if not _git(checkout, "commit", "-m", _commit_subject(request), "-m", _commit_body(request)).success:
        return _failure("git commit failed", cleanup.limit_exceeded)
    first_push = _git(checkout, "push", "origin", f"HEAD:{request.branch}")
    if first_push.success:
        return SnapshotPublishResult(status="succeeded", cleanup_limit_exceeded=cleanup.limit_exceeded)
    if not _git(checkout, "fetch", "origin", request.branch).success:
        return _failure("git fetch after push failure failed", cleanup.limit_exceeded)
    rebase = _git(checkout, "rebase", f"origin/{request.branch}")
    if not rebase.success:
        _git(checkout, "rebase", "--abort")
        return _failure("git rebase after push failure failed", cleanup.limit_exceeded)
    if not _git(checkout, "push", "origin", f"HEAD:{request.branch}").success:
        return _failure("git push retry failed", cleanup.limit_exceeded)
    return SnapshotPublishResult(status="succeeded", cleanup_limit_exceeded=cleanup.limit_exceeded)


def _checkout_snapshot_branch(checkout: Path, branch: str) -> SnapshotPublishResult | None:
    exists = _git(checkout, "ls-remote", "--exit-code", "--heads", "origin", branch)
    if exists.success:
        if not _git(checkout, "fetch", "origin", branch).success:
            return _failure("git fetch snapshot branch failed")
        if not _git(checkout, "switch", "-C", branch, "--track", f"origin/{branch}").success:
            return _failure("git switch snapshot branch failed")
        return None
    if exists.returncode != 2:
        return _failure("git inspect snapshot branch failed")
    if not _git(checkout, "switch", "--orphan", branch).success:
        return _failure("git create orphan snapshot branch failed")
    for child in checkout.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    return None


def _same_monitor_decision(source: Path, target: Path) -> bool:
    source_decision = source / "monitor_decision.json"
    target_decision = target / "monitor_decision.json"
    return (
        source_decision.is_file()
        and target_decision.is_file()
        and source_decision.read_bytes() == target_decision.read_bytes()
    )


def _commit_subject(request: SnapshotPublishRequest) -> str:
    if (
        request.failure_type == MonitorFailureType.BUSINESS_BLOCKED.value
        and request.source_error_count is not None
        and request.audit_error_count is not None
    ):
        return (
            f"异常快照 {request.report_date.isoformat()}: 源站异常 {request.source_error_count} "
            f"巡检异常 {request.audit_error_count} [bot]"
        )
    try:
        label = failure_type_label(MonitorFailureType(request.failure_type))
    except ValueError:
        label = request.failure_type or "未知异常"
    return f"异常快照 {request.report_date.isoformat()}: {label} [bot]"


def _commit_body(request: SnapshotPublishRequest) -> str:
    return "\n".join(
        (
            f"运行 ID: {request.run_id}",
            f"异常类型: {request.failure_type}",
            f"退出码: {_display_optional_count(request.pipeline_exit_code)}",
            f"阻断原因: {','.join(request.blockers)}",
            f"Artifact: {request.artifact_name}",
        )
    )


def _display_optional_count(value: int | None) -> str:
    return str(value) if value is not None else "不可用"


@dataclass(frozen=True)
class _GitResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


def _git(checkout: Path, *args: str) -> _GitResult:
    completed = subprocess.run(
        ("git", *args),
        cwd=checkout,
        check=False,
        capture_output=True,
        text=True,
    )
    return _GitResult(completed.returncode, completed.stdout, completed.stderr)


def _failure(error: str, cleanup_limit_exceeded: bool = False) -> SnapshotPublishResult:
    return SnapshotPublishResult(
        status="failed",
        error=error,
        cleanup_limit_exceeded=cleanup_limit_exceeded,
    )
