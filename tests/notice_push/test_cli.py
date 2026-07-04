from pathlib import Path

import pytest

from src.notice_push.__main__ import build_pipeline, main
from src.notice_push.config import load_config
from src.notice_push.models import PipelineResult
from src.notice_push.summarizer import KimiMultimodalSummarizer, NoticeSummarizer, SummarizerRouter


class FakePipeline:
    def __init__(self):
        self.last_kwargs = None

    def run(self, **kwargs):
        self.last_kwargs = kwargs
        return PipelineResult(report_path=None, new_count=0, summarized_count=0)


def test_cli_passes_runtime_flags_and_dry_run_returns_success(monkeypatch, tmp_path):
    fake_pipeline = FakePipeline()
    captured = {}

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
    assert fake_pipeline.last_kwargs["source_ids"] == ["shu_official"]
    assert fake_pipeline.last_kwargs["dry_run"] is True
    assert fake_pipeline.last_kwargs["limit"] == 1
    assert fake_pipeline.last_kwargs["report_date"].isoformat() == "2026-06-30"
    assert fake_pipeline.last_kwargs["max_pages_per_source"] == 2
    assert fake_pipeline.last_kwargs["stop_after_seen_pages"] == 1
    assert fake_pipeline.last_kwargs["lookback_days"] == 365


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
    assert fake_pipeline.last_kwargs["max_pages_per_source"] == 5
    assert fake_pipeline.last_kwargs["stop_after_seen_pages"] == 2
    assert fake_pipeline.last_kwargs["detail_max_workers"] == 2
    assert fake_pipeline.last_kwargs["summary_max_workers"] == 3
    assert fake_pipeline.last_kwargs["lookback_days"] == 365
    assert fake_pipeline.last_kwargs["retry_failed"] is True
    assert fake_pipeline.last_kwargs["failed_retry_limit"] == 3
    assert fake_pipeline.last_kwargs["refresh_seen_details"] is False
    assert captured["config"].runtime_profiles["daily"].http_timeout == 12
    assert captured["config"].runtime_profiles["daily"].http_max_retries == 2
    assert captured["config"].runtime_profiles["daily"].http_initial_retry_delay == 0.8


def test_cli_applies_backfill_profile_defaults(monkeypatch):
    fake_pipeline = FakePipeline()

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: fake_pipeline)

    exit_code = main(["--dry-run", "--profile", "backfill"])

    assert exit_code == 0
    assert fake_pipeline.last_kwargs["max_pages_per_source"] is None
    assert fake_pipeline.last_kwargs["stop_after_seen_pages"] is None
    assert fake_pipeline.last_kwargs["detail_max_workers"] == 4
    assert fake_pipeline.last_kwargs["summary_max_workers"] == 3
    assert fake_pipeline.last_kwargs["lookback_days"] == 365
    assert fake_pipeline.last_kwargs["refresh_seen_details"] is True


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
    assert fake_pipeline.last_kwargs["max_pages_per_source"] == 9
    assert fake_pipeline.last_kwargs["stop_after_seen_pages"] == 4
    assert fake_pipeline.last_kwargs["detail_max_workers"] == 6
    assert fake_pipeline.last_kwargs["summary_max_workers"] == 7


def test_cli_rejects_unknown_source_before_running_pipeline(monkeypatch):
    fake_pipeline = FakePipeline()
    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: fake_pipeline)

    with pytest.raises(SystemExit) as exc_info:
        main(["--dry-run", "--source", "missing_source"])

    assert exc_info.value.code == 2
    assert fake_pipeline.last_kwargs is None


def test_cli_returns_one_when_normal_run_has_no_new_notices(monkeypatch):
    class EmptyPipeline:
        def run(self, **kwargs):
            return PipelineResult(report_path=None, new_count=0, summarized_count=0)

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: EmptyPipeline())

    assert main([]) == 1


def test_cli_returns_zero_when_report_is_generated(monkeypatch, tmp_path):
    class ReportPipeline:
        def run(self, **kwargs):
            return PipelineResult(report_path=Path("resources/results/2026-06-30.md"), new_count=1, summarized_count=1)

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: ReportPipeline())

    assert main(["--state-path", str(tmp_path / "state.sqlite3"), "--output-dir", str(tmp_path)]) == 0


def test_cli_returns_zero_when_failure_only_report_is_generated(monkeypatch, tmp_path):
    class FailureOnlyPipeline:
        def run(self, **kwargs):
            return PipelineResult(
                report_path=Path("resources/results/2026-06-30.md"),
                new_count=0,
                summarized_count=0,
            )

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: FailureOnlyPipeline())

    assert main(["--state-path", str(tmp_path / "state.sqlite3"), "--output-dir", str(tmp_path)]) == 0


def test_cli_prints_source_error_count_for_no_report(monkeypatch, tmp_path, capsys):
    class SourceErrorPipeline:
        def run(self, **kwargs):
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
