from pathlib import Path
from datetime import datetime

import pytest

from notice_push.domain import LLMProviderConfig, MediaPolicy, NoticeDetail
from notice_push.llm.providers import ResolvedLLMProvider, resolve_optional_provider
from notice_push.llm.registry import (
    SummarizerDependencies,
    build_summarizer,
    summarizer_builder_for,
)
from notice_push.llm.summary_format import SummaryFormatProcessor
from notice_push.llm.text import NoticeSummarizer
from notice_push.settings.loader import load_config


pytestmark = pytest.mark.usefixtures("seed_runtime_config_for_temporary_repo")


def make_dependencies(tmp_path, config):
    return SummarizerDependencies(
        prompt_dir=Path(tmp_path),
        prompt_name="notice_summary_v1",
        profile=config.runtime_profile("daily"),
        http_client=object(),
        media_policy=config.media_policy,
        summary_format_repair_retries=1,
    )


def make_detail(content: str) -> NoticeDetail:
    return NoticeDetail(
        source_id="test_source",
        url="https://example.com/notice.htm",
        canonical_url="https://example.com/notice.htm",
        title="测试通知",
        content=content,
        published_at=datetime(2026, 7, 14),
    )


def test_registry_exposes_builtin_provider_builders(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    dependencies = make_dependencies(tmp_path, config)
    provider = ResolvedLLMProvider(
        name="custom-text",
        base_url="https://llm.example/v1",
        api_key="configured-key",
        model="configured-model",
        kind="openai_text",
    )

    assert summarizer_builder_for("openai_text") is not None
    summarizer = build_summarizer(provider, dependencies)

    assert isinstance(summarizer, NoticeSummarizer)
    assert summarizer.model == "configured-model"
    assert summarizer.api_key == "configured-key"


def test_registry_rejects_unknown_provider_kind(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    provider = ResolvedLLMProvider(
        name="unknown",
        base_url="https://llm.example/v1",
        api_key="configured-key",
        model="configured-model",
        kind="unknown_kind",
    )

    with pytest.raises(ValueError, match="unknown_kind"):
        build_summarizer(provider, make_dependencies(tmp_path, config))


def test_resolved_provider_respects_explicit_empty_environment(monkeypatch):
    monkeypatch.setenv("CUSTOM_API_KEY", "must-not-leak")
    monkeypatch.setenv("CUSTOM_MODEL", "must-not-leak")
    config = LLMProviderConfig(
        name="custom",
        base_url="https://llm.example/v1",
        api_key_env="CUSTOM_API_KEY",
        model_env="CUSTOM_MODEL",
        default_model="configured-default",
        kind="openai_text",
    )

    provider = resolve_optional_provider("custom", config, env={})

    assert provider.api_key == ""
    assert provider.model == "configured-default"


def test_registry_propagates_provider_name_to_missing_key_error(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    provider = ResolvedLLMProvider(
        name="custom-text",
        base_url="https://llm.example/v1",
        api_key="",
        model="configured-model",
        kind="openai_text",
    )
    summarizer = build_summarizer(provider, make_dependencies(tmp_path, config))

    with pytest.raises(ValueError, match="provider 'custom-text'"):
        summarizer._get_client()


def test_summary_format_processor_owns_normalize_validate_and_repair():
    invalid = "## 官网|行政|周常事务|测试通知\n- 缺少结构化字段"
    repaired = make_detail("通知正文")
    prompts = []
    processor = SummaryFormatProcessor(repair_retries=1)

    result = processor.normalize_validate_or_repair(
        invalid,
        source_detail=repaired,
        source_name="测试来源",
        chat_for_repair=lambda prompt: prompts.append(prompt) or (
            "## 官网|行政|周常事务|测试通知\n"
            "- **发布时间**: 未提及\n"
            "- **影响对象**: 未提及\n"
            "- **核心信息**: 已修复\n"
            "- **行动指引**: 未提及\n"
            "- **截止时间**: 未提及\n"
            "- **相关链接**: 未提及"
        ),
    )

    assert "已修复" in result
    assert len(prompts) == 1
