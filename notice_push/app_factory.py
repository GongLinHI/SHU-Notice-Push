from __future__ import annotations

from notice_push.domain.config import AppConfig
from notice_push.parsing.detail import DetailParser
from notice_push.parsing.content import ParsingRules
from notice_push.http import HttpClient
from notice_push.http_cache import CachedHttpClient
from notice_push.llm import resolve_optional_provider
from notice_push.llm.registry import SummarizerDependencies, build_summarizer
from notice_push.llm.router import SummarizerRouter
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
    dependencies = SummarizerDependencies(
        prompt_dir=config.repo_root / "resources" / "prompts",
        prompt_name=config.prompt_name,
        profile=profile,
        http_client=http_client,
        media_policy=config.media_policy,
        summary_format_repair_retries=config.summary_format_repair_retries,
    )
    provider_summarizers = {
        provider_id: build_summarizer(
            resolve_optional_provider(provider_id, provider_config),
            dependencies,
        )
        for provider_id, provider_config in config.llm_providers.items()
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
