from __future__ import annotations

from notice_push.domain.config import AppConfig
from notice_push.parsing.detail import DetailParser
from notice_push.parsing.html import ParsingRules
from notice_push.http import HttpClient
from notice_push.llm import resolve_optional_provider
from notice_push.llm.kimi import KimiMultimodalSummarizer
from notice_push.llm.router import SummarizerRouter
from notice_push.llm.text import NoticeSummarizer
from notice_push.domain import NoticeRuntimeProfile
from notice_push.pipeline import NoticePipeline, create_adapter
from notice_push.observability.source_audit import SourceAuditor
from notice_push.storage import NoticeStorage


def build_detail_parser(config: AppConfig) -> DetailParser:
    return DetailParser(
        ParsingRules(
            external_video_domains=config.parsing.external_video_domains,
            noise_image_markers=config.parsing.noise_image_markers,
        )
    )


def build_http_client(profile: NoticeRuntimeProfile) -> HttpClient:
    return HttpClient(
        timeout=profile.http_timeout,
        max_retries=profile.http_max_retries,
        initial_retry_delay=profile.http_initial_retry_delay,
    )


def build_pipeline(config: AppConfig, profile: NoticeRuntimeProfile) -> NoticePipeline:
    detail_parser = build_detail_parser(config)
    storage = NoticeStorage(config.state_path, config.sources)
    http_client = build_http_client(profile)
    deepseek_provider = resolve_optional_provider("deepseek", config.llm_providers["deepseek"])
    kimi_provider = resolve_optional_provider("kimi", config.llm_providers["kimi"])
    text_summarizer = NoticeSummarizer(
        prompt_dir=config.repo_root / "resources" / "prompts",
        prompt_name=config.prompt_name,
        model=deepseek_provider.model,
        api_key=deepseek_provider.api_key,
        base_url=deepseek_provider.base_url,
        timeout=profile.llm_timeout,
        max_retries=profile.llm_max_retries,
        initial_retry_delay=profile.llm_initial_retry_delay,
        retry_backoff=profile.llm_retry_backoff,
        summary_format_repair_retries=config.summary_format_repair_retries,
    )
    kimi_summarizer = KimiMultimodalSummarizer(
        prompt_dir=config.repo_root / "resources" / "prompts",
        prompt_name=config.prompt_name,
        model=kimi_provider.model,
        api_key=kimi_provider.api_key,
        base_url=kimi_provider.base_url,
        http_client=http_client,
        timeout=profile.llm_timeout,
        max_retries=profile.llm_max_retries,
        initial_retry_delay=profile.llm_initial_retry_delay,
        retry_backoff=profile.llm_retry_backoff,
        media_policy=config.media_policy,
        summary_format_repair_retries=config.summary_format_repair_retries,
    )
    summarizer = SummarizerRouter(
        text_summarizer=text_summarizer,
        kimi_summarizer=kimi_summarizer,
        routing=config.llm_routing,
    )
    return NoticePipeline(
        config=config,
        storage=storage,
        http_client=http_client,
        summarizer=summarizer,
        adapter_factory=lambda source: create_adapter(source, detail_parser=detail_parser),
    )


def run_source_audit(config: AppConfig, profile: NoticeRuntimeProfile, source_ids: tuple[str, ...]):
    detail_parser = build_detail_parser(config)
    http_client = build_http_client(profile)
    auditor = SourceAuditor(
        http_client=http_client,
        adapter_factory=lambda source: create_adapter(source, detail_parser=detail_parser),
        min_list_items=config.audit_policy.min_list_items,
        sample_detail_count=config.audit_policy.sample_detail_count,
        required_content_kinds=config.audit_policy.required_content_kinds,
    )
    return auditor.audit_sources(_select_sources(config, source_ids or None))


def _select_sources(config: AppConfig, source_ids: tuple[str, ...] | None):
    if source_ids:
        requested = set(source_ids)
        return [source for source in config.sources if source.id in requested]
    return [source for source in config.sources if source.enabled]
