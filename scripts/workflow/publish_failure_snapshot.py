from __future__ import annotations

import argparse
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

from notice_push.observability.failure_snapshot import cleanup_expired_snapshot_dates


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
    pipeline_exit_code: int
    source_error_count: int
    audit_error_count: int
    artifact_name: str
    blockers: tuple[str, ...]


class SnapshotPublishResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: SnapshotPublishStatus
    error: StrictStr = ""
    cleanup_limit_exceeded: StrictBool = False


def publish_failure_snapshot(request: SnapshotPublishRequest) -> SnapshotPublishResult:
    checkout = Path(request.checkout).resolve()
    source_snapshot = Path(request.source_snapshot).resolve()
    if not checkout.is_dir() or not source_snapshot.is_dir():
        return SnapshotPublishResult(status="failed", error="checkout or source snapshot directory is missing")
    for command in (("config", "user.name", "github-actions[bot]"), ("config", "user.email", "github-actions[bot]@users.noreply.github.com")):
        if not _git(checkout, *command).success:
            return _failure("git configuration failed")
    branch_result = _checkout_snapshot_branch(checkout, request.branch)
    if branch_result is not None:
        return branch_result

    relative_target = Path("failure-snapshots") / request.report_date.isoformat() / f"run-{request.run_id}"
    target = checkout / relative_target
    if target.exists():
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

    subject = (
        f"异常快照 {request.report_date.isoformat()}: 源站异常 {request.source_error_count} "
        f"巡检异常 {request.audit_error_count} [bot]"
    )
    body = "\n".join(
        (
            f"运行 ID: {request.run_id}",
            f"退出码: {request.pipeline_exit_code}",
            f"阻断原因: {','.join(request.blockers)}",
            f"Artifact: {request.artifact_name}",
        )
    )
    if not _git(checkout, "commit", "-m", subject, "-m", body).success:
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
    return SnapshotPublishResult(status="failed", error=error, cleanup_limit_exceeded=cleanup_limit_exceeded)


def _write_github_output(path: Path | None, result: SnapshotPublishResult) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"status={result.status}\n")
        stream.write(f"cleanup_limit_exceeded={str(result.cleanup_limit_exceeded).lower()}\n")
        stream.write(f"error={result.error}\n")


def _write_result_json(path: Path, result: SnapshotPublishResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish one diagnostic failure snapshot to its isolated branch.")
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--source-snapshot", type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--retention-days", type=int, required=True)
    parser.add_argument("--max-scan-entries", type=int, required=True)
    parser.add_argument("--pipeline-exit-code", type=int, required=True)
    parser.add_argument("--source-error-count", type=int, required=True)
    parser.add_argument("--audit-error-count", type=int, required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--publication-blockers", default="")
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    result = publish_failure_snapshot(
        SnapshotPublishRequest(
            checkout=args.checkout,
            source_snapshot=args.source_snapshot,
            branch=args.branch,
            report_date=date.fromisoformat(args.report_date),
            run_id=args.run_id,
            retention_days=args.retention_days,
            max_scan_entries=args.max_scan_entries,
            pipeline_exit_code=args.pipeline_exit_code,
            source_error_count=args.source_error_count,
            audit_error_count=args.audit_error_count,
            artifact_name=args.artifact_name,
            blockers=tuple(value for value in args.publication_blockers.split(",") if value),
        )
    )
    _write_result_json(args.result_json, result)
    if result.cleanup_limit_exceeded:
        print(
            "warning: failure snapshot retention cleanup was skipped because the scan limit was exceeded"
        )
    _write_github_output(args.github_output, result)
    return 0 if result.status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
