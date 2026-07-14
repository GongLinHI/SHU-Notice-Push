from __future__ import annotations

from notice_push.domain.config import AppConfig
from notice_push.parsing.detail import DetailParser
from notice_push.parsing.html import ParsingRules
from notice_push.http import HttpClient
from notice_push.http_cache import CachedHttpClient
from notice_push.llm import resolve_optional_provider
from notice_push.llm.kimi import KimiMultimodalSummarizer
from notice_push.llm.router import SummarizerRouter
from notice_push.llm.text import NoticeSummarizer
from notice_push.domain import NoticeRuntimeProfile
from notice_push.pipeline import NoticePipeline, create_adapter
from notice_push.observability.source_audit import SourceAuditor
from notice_push.sources.selection import select_sources
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
        retry_backoff=profile.http_retry_backoff,
        max_retry_delay_seconds=profile.http_max_retry_delay_seconds,
    )


def build_pipeline(config: AppConfig, profile: NoticeRuntimeProfile) -> NoticePipeline:
    detail_parser = build_detail_parser(config)
    storage = NoticeStorage(config.state_path, config.sources)
    http_client = CachedHttpClient(build_http_client(profile))
    provider_summarizers = {
        provider_id: _build_provider_summarizer(provider_id, config, profile, http_client)
        for provider_id in config.llm_providers
    }
    summarizer = SummarizerRouter(
        provider_summarizers=provider_summarizers,
        routing=config.llm_routing,
    )
    return NoticePipeline(
        config=config,
        storage=storage,
        http_client=http_client,
        summarizer=summarizer,
        adapter_factory=lambda source: create_adapter(source, detail_parser=detail_parser),
    )


def _build_provider_summarizer(provider_id: str, config: AppConfig, profile: NoticeRuntimeProfile, http_client: HttpClient):
    provider = resolve_optional_provider(provider_id, config.llm_providers[provider_id])
    prompt_dir = config.repo_root / "resources" / "prompts"
    if provider.kind == "openai_text":
        return NoticeSummarizer(
            prompt_dir=prompt_dir,
            prompt_name=config.prompt_name,
            model=provider.model,
            api_key=provider.api_key,
            base_url=provider.base_url,
            timeout=profile.llm_timeout,
            max_retries=profile.llm_max_retries,
            initial_retry_delay=profile.llm_initial_retry_delay,
            retry_backoff=profile.llm_retry_backoff,
            summary_format_repair_retries=config.summary_format_repair_retries,
        )
    if provider.kind == "kimi_multimodal":
        return KimiMultimodalSummarizer(
            prompt_dir=prompt_dir,
            prompt_name=config.prompt_name,
            model=provider.model,
            api_key=provider.api_key,
            base_url=provider.base_url,
            http_client=http_client,
            timeout=profile.llm_timeout,
            max_retries=profile.llm_max_retries,
            initial_retry_delay=profile.llm_initial_retry_delay,
            retry_backoff=profile.llm_retry_backoff,
            media_policy=config.media_policy,
            summary_format_repair_retries=config.summary_format_repair_retries,
        )
    raise ValueError(f"unsupported LLM provider kind for '{provider_id}': {provider.kind}")


def run_source_audit(config: AppConfig, profile: NoticeRuntimeProfile, source_ids: tuple[str, ...]):
    detail_parser = build_detail_parser(config)
    http_client = CachedHttpClient(build_http_client(profile))
    auditor = SourceAuditor(
        http_client=http_client,
        adapter_factory=lambda source: create_adapter(source, detail_parser=detail_parser),
        min_list_items=config.audit_policy.min_list_items,
        sample_detail_count=config.audit_policy.sample_detail_count,
        required_content_kinds=config.audit_policy.required_content_kinds,
    )
    return auditor.audit_sources(select_sources(config.sources, source_ids))
