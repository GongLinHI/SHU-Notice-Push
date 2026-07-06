from dataclasses import replace
from pathlib import Path

import pytest

from src.notice_push.__main__ import build_pipeline, main
from src.notice_push.config import load_config
from src.notice_push.models import MediaPolicy, PipelineResult, PipelineRunOptions, SourceAuditIssue, SourceAuditResult
from src.notice_push.summarizer import KimiMultimodalSummarizer, NoticeSummarizer, SummarizerRouter


class FakePipeline:
    def __init__(self):
        self.last_options = None

    def run(self, options):
        self.last_options = options
        return PipelineResult(report_path=None, new_count=0, summarized_count=0)


def _write_doctor_repo_files(root: Path, prompt_text: str | None = None) -> None:
    (root / "resources" / "config").mkdir(parents=True)
    (root / "resources" / "config" / "runtime.yml").write_text("sources: {}\n", encoding="utf-8")
    (root / "resources" / "prompts").mkdir(parents=True)
    (root / "resources" / "prompts" / "notice_summary_v1.md").write_text(
        prompt_text
        or "\n".join(
            [
                "- **发布时间**: ...",
                "- **影响对象**: ...",
                "- **核心信息**: ...",
                "- **行动指引**: ...",
                "- **截止时间**: ...",
                "- **相关链接**: ...",
            ]
        ),
        encoding="utf-8",
    )
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "daily_report.yml").write_text(
        "name: Daily\non: workflow_dispatch\njobs: {}\n",
        encoding="utf-8",
    )
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "name: CI\non: workflow_dispatch\njobs: {}\n",
        encoding="utf-8",
    )


def test_cli_passes_runtime_flags_and_dry_run_returns_success(monkeypatch, tmp_path):
    fake_pipeline = FakePipeline()
    captured = {}
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    def fake_build_pipeline(config, profile):
        captured["config"] = config
        captured["profile"] = profile
        return fake_pipeline

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", fake_build_pipeline)

    exit_code = main(
        [
            "--dry-run",
            "--source",
            "shu_official",
            "--limit",
            "1",
            "--date",
            "2026-06-30",
            "--state-path",
            str(tmp_path / "state.sqlite3"),
            "--output-dir",
            str(tmp_path / "results"),
            "--max-pages-per-source",
            "2",
            "--stop-after-seen-pages",
            "1",
        ]
    )

    assert exit_code == 0
    assert captured["config"].state_path == tmp_path / "state.sqlite3"
    assert captured["config"].output_dir == tmp_path / "results"
    assert fake_pipeline.last_options == PipelineRunOptions(
        source_ids=("shu_official",),
        dry_run=True,
        limit=1,
        report_date=fake_pipeline.last_options.report_date,
        max_pages_per_source=2,
        stop_after_seen_pages=1,
        detail_max_workers=2,
        summary_max_workers=3,
        lookback_days=365,
        retry_failed=True,
        failed_retry_limit=3,
        failed_retry_after_hours=12,
        refresh_seen_details=False,
        refresh_seen_max_workers=1,
        refresh_seen_limit=0,
        audit_sources=True,
    )
    assert fake_pipeline.last_options.report_date.isoformat() == "2026-06-30"


def test_cli_applies_daily_profile_defaults(monkeypatch):
    fake_pipeline = FakePipeline()
    captured = {}

    def fake_build_pipeline(config, profile):
        captured["config"] = config
        captured["profile"] = profile
        return fake_pipeline

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", fake_build_pipeline)

    exit_code = main(["--dry-run", "--profile", "daily"])

    assert exit_code == 0
    assert fake_pipeline.last_options.max_pages_per_source == 5
    assert fake_pipeline.last_options.stop_after_seen_pages == 2
    assert fake_pipeline.last_options.detail_max_workers == 2
    assert fake_pipeline.last_options.summary_max_workers == 3
    assert fake_pipeline.last_options.lookback_days == 365
    assert fake_pipeline.last_options.retry_failed is True
    assert fake_pipeline.last_options.failed_retry_limit == 3
    assert fake_pipeline.last_options.refresh_seen_details is False
    assert captured["config"].runtime_profiles["daily"].http_timeout == 12
    assert captured["config"].runtime_profiles["daily"].http_max_retries == 2
    assert captured["config"].runtime_profiles["daily"].http_initial_retry_delay == 0.8


def test_cli_applies_backfill_profile_defaults(monkeypatch):
    fake_pipeline = FakePipeline()

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: fake_pipeline)

    exit_code = main(["--dry-run", "--profile", "backfill"])

    assert exit_code == 0
    assert fake_pipeline.last_options.max_pages_per_source is None
    assert fake_pipeline.last_options.stop_after_seen_pages is None
    assert fake_pipeline.last_options.detail_max_workers == 4
    assert fake_pipeline.last_options.summary_max_workers == 3
    assert fake_pipeline.last_options.lookback_days == 365
    assert fake_pipeline.last_options.refresh_seen_details is True


def test_cli_prefers_explicit_runtime_flags_over_profile(monkeypatch):
    fake_pipeline = FakePipeline()

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: fake_pipeline)

    exit_code = main(
        [
            "--dry-run",
            "--profile",
            "daily",
            "--max-pages-per-source",
            "9",
            "--stop-after-seen-pages",
            "4",
            "--detail-max-workers",
            "6",
            "--summary-max-workers",
            "7",
        ]
    )

    assert exit_code == 0
    assert fake_pipeline.last_options.max_pages_per_source == 9
    assert fake_pipeline.last_options.stop_after_seen_pages == 4
    assert fake_pipeline.last_options.detail_max_workers == 6
    assert fake_pipeline.last_options.summary_max_workers == 7


def test_cli_can_skip_source_audit(monkeypatch):
    fake_pipeline = FakePipeline()

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: fake_pipeline)

    exit_code = main(["--dry-run", "--skip-source-audit"])

    assert exit_code == 0
    assert fake_pipeline.last_options.audit_sources is False


def test_cli_rejects_unknown_source_before_running_pipeline(monkeypatch):
    fake_pipeline = FakePipeline()
    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: fake_pipeline)

    with pytest.raises(SystemExit) as exc_info:
        main(["--dry-run", "--source", "missing_source"])

    assert exc_info.value.code == 2
    assert fake_pipeline.last_options is None


def test_cli_returns_one_when_normal_run_has_no_new_notices(monkeypatch):
    class EmptyPipeline:
        def run(self, options):
            return PipelineResult(report_path=None, new_count=0, summarized_count=0)

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: EmptyPipeline())

    assert main([]) == 1


def test_cli_returns_zero_when_report_is_generated(monkeypatch, tmp_path):
    class ReportPipeline:
        def run(self, options):
            return PipelineResult(report_path=Path("resources/results/2026-06-30.md"), new_count=1, summarized_count=1)

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: ReportPipeline())

    assert main(["--state-path", str(tmp_path / "state.sqlite3"), "--output-dir", str(tmp_path)]) == 0


def test_cli_returns_zero_when_failure_only_report_is_generated(monkeypatch, tmp_path):
    class FailureOnlyPipeline:
        def run(self, options):
            return PipelineResult(
                report_path=Path("resources/results/2026-06-30.md"),
                new_count=0,
                summarized_count=0,
            )

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: FailureOnlyPipeline())

    assert main(["--state-path", str(tmp_path / "state.sqlite3"), "--output-dir", str(tmp_path)]) == 0


def test_cli_prints_source_error_count_for_no_report(monkeypatch, tmp_path, capsys):
    class SourceErrorPipeline:
        def run(self, options):
            from src.notice_push.models import SourceError

            return PipelineResult(
                report_path=None,
                new_count=0,
                summarized_count=0,
                source_errors=(
                    SourceError(
                        source_id="shu_official",
                        source_name="上海大学官网",
                        url="https://www.shu.edu.cn/tzgg.htm",
                        reason="timeout",
                    ),
                ),
            )

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: SourceErrorPipeline())

    assert main(["--state-path", str(tmp_path / "state.sqlite3"), "--output-dir", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "new_count=0" in output
    assert "summarized_count=0" in output
    assert "failed_count=0" in output
    assert "source_error_count=1" in output


def test_cli_prints_audit_counts(monkeypatch, tmp_path, capsys):
    class AuditPipeline:
        def run(self, options):
            return PipelineResult(
                report_path=None,
                new_count=0,
                summarized_count=0,
                audit_results=(
                    SourceAuditResult(
                        source_id="shu_official",
                        source_name="上海大学官网",
                        list_url="https://www.shu.edu.cn/tzgg.htm",
                        list_item_count=0,
                        issues=(
                            SourceAuditIssue(
                                source_id="shu_official",
                                source_name="上海大学官网",
                                url="https://www.shu.edu.cn/tzgg.htm",
                                severity="error",
                                reason="list page parsed 0 items",
                            ),
                            SourceAuditIssue(
                                source_id="shu_official",
                                source_name="上海大学官网",
                                url="https://www.shu.edu.cn/info/1051/test.htm",
                                severity="warning",
                                reason="sample detail failed",
                            ),
                        ),
                    ),
                ),
            )

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: AuditPipeline())

    assert main(["--state-path", str(tmp_path / "state.sqlite3"), "--output-dir", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "audit_error_count=1" in output
    assert "audit_warning_count=1" in output


def test_cli_audit_only_returns_one_for_audit_errors_without_building_pipeline(monkeypatch, tmp_path, capsys):
    def fail_build_pipeline(config, profile):
        raise AssertionError("audit-only should not initialize the full pipeline")

    def fake_run_source_audit(config, profile, source_ids):
        return (
            SourceAuditResult(
                source_id="shu_official",
                source_name="上海大学官网",
                list_url="https://www.shu.edu.cn/tzgg.htm",
                list_item_count=0,
                issues=(
                    SourceAuditIssue(
                        source_id="shu_official",
                        source_name="上海大学官网",
                        url="https://www.shu.edu.cn/tzgg.htm",
                        severity="error",
                        reason="list page parsed 0 items",
                    ),
                ),
            ),
        )

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", fail_build_pipeline)
    monkeypatch.setattr("src.notice_push.__main__.run_source_audit", fake_run_source_audit)

    exit_code = main(["--audit-only", "--state-path", str(tmp_path / "state.sqlite3")])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "audit_error_count=1" in output
    assert "audit_warning_count=0" in output


def test_cli_doctor_warns_without_building_pipeline(monkeypatch, tmp_path, capsys):
    def fail_build_pipeline(config, profile):
        raise AssertionError("doctor should not initialize the full pipeline")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("KIMI_API_KEY", "")
    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", fail_build_pipeline)

    exit_code = main(["--doctor", "--state-path", str(tmp_path / "state.sqlite3")])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "doctor_warning=DEEPSEEK_API_KEY is not set" in output
    assert "doctor_warning=KIMI_API_KEY is not set" in output


def test_cli_doctor_returns_two_for_structural_errors(monkeypatch, tmp_path, capsys):
    def fake_run_doctor(config):
        return ("error: no enabled sources", "warning: KIMI_API_KEY is not set")

    monkeypatch.setattr("src.notice_push.__main__.run_doctor", fake_run_doctor)

    exit_code = main(["--doctor", "--state-path", str(tmp_path / "state.sqlite3")])

    assert exit_code == 2
    output = capsys.readouterr().out
    assert "doctor_error=no enabled sources" in output
    assert "doctor_warning=KIMI_API_KEY is not set" in output


def test_cli_doctor_reports_prompt_field_errors(monkeypatch, tmp_path, capsys):
    _write_doctor_repo_files(tmp_path, prompt_text="输出要求缺少结构化字段")
    config = load_config(env={}, repo_root=tmp_path, state_path=tmp_path / "state.sqlite3")
    monkeypatch.setattr("src.notice_push.__main__.load_config", lambda **kwargs: config)

    exit_code = main(["--doctor"])

    assert exit_code == 2
    output = capsys.readouterr().out
    assert "doctor_error=prompt missing summary fields" in output


def test_cli_doctor_reports_invalid_media_policy(monkeypatch, tmp_path, capsys):
    _write_doctor_repo_files(tmp_path)
    config = load_config(env={}, repo_root=tmp_path, state_path=tmp_path / "state.sqlite3")
    config = replace(config, media_policy=MediaPolicy(pdf_max_bytes=0, image_max_bytes=1, pdf_extracted_text_max_chars=1))
    monkeypatch.setattr("src.notice_push.__main__.load_config", lambda **kwargs: config)

    exit_code = main(["--doctor"])

    assert exit_code == 2
    output = capsys.readouterr().out
    assert "doctor_error=media policy values must be positive" in output


def test_cli_prints_retry_and_manual_review_counts(monkeypatch, tmp_path, capsys):
    class RetryPipeline:
        def run(self, options):
            return PipelineResult(
                report_path=Path("resources/results/2026-06-30.md"),
                new_count=0,
                retried_count=1,
                summarized_count=0,
                manual_review_count=1,
            )

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: RetryPipeline())

    assert main(["--state-path", str(tmp_path / "state.sqlite3"), "--output-dir", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "new_count=0" in output
    assert "retried_count=1" in output
    assert "manual_review_count=1" in output


def test_cli_prints_run_summary_path(monkeypatch, tmp_path, capsys):
    class RunSummaryPipeline:
        def run(self, options):
            return PipelineResult(
                report_path=Path("resources/results/2026-06-30.md"),
                run_summary_path=Path("resources/results/json/2026-06-30.json"),
                new_count=1,
                summarized_count=1,
            )

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: RunSummaryPipeline())

    assert main(["--state-path", str(tmp_path / "state.sqlite3"), "--output-dir", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "run_summary_path=resources\\results\\json\\2026-06-30.json" in output or (
        "run_summary_path=resources/results/json/2026-06-30.json" in output
    )


def test_build_pipeline_constructs_router_from_llm_provider_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("KIMI_API_KEY", "kimi-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-unit")
    monkeypatch.setenv("KIMI_MODEL", "kimi-unit")
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )

    pipeline = build_pipeline(config, config.runtime_profile("daily"))

    assert isinstance(pipeline.summarizer, SummarizerRouter)
    assert pipeline.summarizer.routing == {"text": "deepseek", "pdf": "kimi", "image": "kimi"}
    text_summarizer = pipeline.summarizer.provider_summarizers["deepseek"]
    kimi_summarizer = pipeline.summarizer.provider_summarizers["kimi"]
    assert isinstance(text_summarizer, NoticeSummarizer)
    assert isinstance(kimi_summarizer, KimiMultimodalSummarizer)
    assert text_summarizer.model == "deepseek-unit"
    assert text_summarizer.api_key == "deepseek-key"
    assert text_summarizer.base_url == "https://api.deepseek.com"
    assert kimi_summarizer.model == "kimi-unit"
    assert kimi_summarizer.api_key == "kimi-key"
    assert kimi_summarizer.base_url == "https://api.moonshot.cn/v1"


def test_build_pipeline_allows_missing_kimi_key_until_multimodal_summary_is_needed(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-unit")
    monkeypatch.setenv("KIMI_MODEL", "kimi-unit")
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )

    pipeline = build_pipeline(config, config.runtime_profile("daily"))

    assert isinstance(pipeline.summarizer, SummarizerRouter)
    kimi_summarizer = pipeline.summarizer.provider_summarizers["kimi"]
    assert isinstance(kimi_summarizer, KimiMultimodalSummarizer)
    assert kimi_summarizer.model == "kimi-unit"
    assert kimi_summarizer.api_key == ""
    assert kimi_summarizer.base_url == "https://api.moonshot.cn/v1"


def test_build_pipeline_allows_missing_deepseek_key_until_text_summary_is_needed(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-unit")
    monkeypatch.setenv("KIMI_MODEL", "kimi-unit")
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )

    pipeline = build_pipeline(config, config.runtime_profile("daily"))

    assert isinstance(pipeline.summarizer, SummarizerRouter)
    text_summarizer = pipeline.summarizer.provider_summarizers["deepseek"]
    assert isinstance(text_summarizer, NoticeSummarizer)
    assert text_summarizer.model == "deepseek-unit"
    assert text_summarizer.api_key == ""
    assert text_summarizer.base_url == "https://api.deepseek.com"
