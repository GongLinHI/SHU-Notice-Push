from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

from notice_push.observability.publication import PublicationStatus
from notice_push.observability.publication_manifest import PublicationCounts, PublicationManifest


PublishMode = Literal["published", "no_report"]
PublishStatus = Literal["succeeded", "no_changes", "failed"]


@dataclass(frozen=True)
class PublishMasterRequest:
    repository: Path
    branch: str
    mode: PublishMode
    state_path: Path
    report_path: Path | None
    report_date: str
    counts: PublicationCounts


class PublishMasterResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: PublishStatus
    master_state_updated: StrictBool
    error: StrictStr = ""
    commit_subject: StrictStr = ""


def publish_master(request: PublishMasterRequest) -> PublishMasterResult:
    repository = Path(request.repository).resolve()
    state_path = _repository_relative_path(repository, request.state_path)
    report_path = _repository_relative_path(repository, request.report_path) if request.report_path else None
    if request.mode == "published":
        if report_path is None or not (repository / report_path).is_file():
            return PublishMasterResult(status="failed", master_state_updated=False, error="published report is missing")
    if not (repository / state_path).is_file():
        return PublishMasterResult(status="failed", master_state_updated=False, error="state database is missing")

    for key, value in (
        ("user.name", "github-actions[bot]"),
        ("user.email", "github-actions[bot]@users.noreply.github.com"),
    ):
        config_result = _git(repository, "config", key, value)
        if config_result.returncode != 0:
            return PublishMasterResult(
                status="failed",
                master_state_updated=False,
                error=_git_error("git configuration failed", config_result),
            )

    paths = [str(state_path)] if request.mode == "no_report" else [str(report_path), str(state_path)]
    add_result = _git(repository, "add", "--", *paths)
    if add_result.returncode != 0:
        return PublishMasterResult(
            status="failed",
            master_state_updated=False,
            error=_git_error("git add failed", add_result),
        )
    if _git(repository, "diff", "--cached", "--quiet").returncode == 0:
        return PublishMasterResult(status="no_changes", master_state_updated=False)

    subject, body = _commit_message(request)
    commit_result = _git(repository, "commit", "-m", subject, "-m", body)
    if commit_result.returncode != 0:
        return PublishMasterResult(
            status="failed",
            master_state_updated=False,
            error=_git_error("git commit failed", commit_result),
            commit_subject=subject,
        )
    push_result = _git(repository, "push", "origin", f"HEAD:{request.branch}")
    if push_result.returncode != 0:
        return PublishMasterResult(
            status="failed",
            master_state_updated=False,
            error=_git_error("git push failed", push_result),
            commit_subject=subject,
        )
    return PublishMasterResult(status="succeeded", master_state_updated=True, commit_subject=subject)


def _repository_relative_path(repository: Path, path: Path | None) -> Path:
    if path is None:
        raise ValueError("path is required")
    candidate = Path(path)
    resolved = (repository / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        return resolved.relative_to(repository)
    except ValueError as exc:
        raise ValueError(f"path must be inside repository: {path}") from exc


def _commit_message(request: PublishMasterRequest) -> tuple[str, str]:
    counts = request.counts
    if request.mode == "no_report":
        return (
            f"日报 {request.report_date}: 无新通知 [bot]",
            f"重试通知: {counts.retried_count}\n源站异常: {counts.source_error_count}\n巡检异常: {counts.audit_error_count}",
        )
    return (
        f"日报 {request.report_date}: 新增 {counts.new_count} 更新 {counts.updated_count} 复核 {counts.manual_review_count} [bot]",
        "\n".join(
            (
                f"重试通知: {counts.retried_count}",
                f"成功摘要: {counts.summarized_count}",
                f"失败通知: {counts.failed_count}",
                f"源站异常: {counts.source_error_count}",
                f"巡检异常: {counts.audit_error_count}",
                f"巡检警告: {counts.audit_warning_count}",
                f"详情刷新异常: {counts.refresh_seen_error_count}",
            )
        ),
    )


def _git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )


def _git_error(message: str, result: subprocess.CompletedProcess[str]) -> str:
    detail = " ".join((*result.stdout.split(), *result.stderr.split()))
    detail = re.sub(r"(https?://)[^/@\s]+@", r"\1***@", detail)
    return f"{message}: {detail[:1000]}" if detail else message


def _write_github_output(path: Path | None, result: PublishMasterResult) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"status={result.status}\n")
        stream.write(f"master_state_updated={str(result.master_state_updated).lower()}\n")
        stream.write(f"error={result.error}\n")


def _write_result_json(path: Path, result: PublishMasterResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Commit and push formal notice state to master.")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--candidate-publication-json", type=Path, required=True)
    parser.add_argument("--state-path", type=Path, default=Path("resources/notice_state.sqlite3"))
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    candidate = PublicationManifest.from_json_text(
        args.candidate_publication_json.read_text(encoding="utf-8")
    )
    if candidate.status not in {PublicationStatus.PUBLISHED, PublicationStatus.NO_REPORT}:
        result = PublishMasterResult(status="failed", master_state_updated=False, error="candidate is not publishable")
        _write_result_json(args.result_json, result)
        _write_github_output(args.github_output, result)
        return 1
    result = publish_master(
        PublishMasterRequest(
            repository=args.repository,
            branch=args.branch,
            mode="published" if candidate.status is PublicationStatus.PUBLISHED else "no_report",
            state_path=args.state_path,
            report_path=Path(candidate.report_path) if candidate.report_path else None,
            report_date=candidate.report_date,
            counts=candidate.counts,
        )
    )
    _write_result_json(args.result_json, result)
    _write_github_output(args.github_output, result)
    return 0 if result.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
