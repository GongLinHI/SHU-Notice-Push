from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from notice_push.domain import MediaPolicy, NoticeRuntimeProfile
from notice_push.llm.kimi import KimiMultimodalSummarizer
from notice_push.llm.providers import ResolvedLLMProvider
from notice_push.llm.text import NoticeSummarizer


@dataclass(frozen=True)
class SummarizerDependencies:
    prompt_dir: Path
    prompt_name: str
    profile: NoticeRuntimeProfile
    http_client: object
    media_policy: MediaPolicy
    summary_format_repair_retries: int


SummarizerBuilder = Callable[[ResolvedLLMProvider, SummarizerDependencies], object]
_BUILDERS: dict[str, SummarizerBuilder] = {}


def register_summarizer_builder(kind: str, builder: SummarizerBuilder) -> None:
    normalized_kind = kind.strip()
    if not normalized_kind:
        raise ValueError("summarizer builder kind must not be empty")
    _BUILDERS[normalized_kind] = builder


def summarizer_builder_for(kind: str) -> SummarizerBuilder | None:
    return _BUILDERS.get(kind)


def build_summarizer(
    provider: ResolvedLLMProvider,
    dependencies: SummarizerDependencies,
) -> object:
    builder = summarizer_builder_for(provider.kind)
    if builder is None:
        raise ValueError(
            f"unsupported LLM provider kind for '{provider.name}': {provider.kind}"
        )
    return builder(provider, dependencies)


def _build_openai_text(
    provider: ResolvedLLMProvider,
    dependencies: SummarizerDependencies,
) -> NoticeSummarizer:
    profile = dependencies.profile
    return NoticeSummarizer(
        prompt_dir=dependencies.prompt_dir,
        prompt_name=dependencies.prompt_name,
        model=provider.model,
        api_key=provider.api_key,
        base_url=provider.base_url,
        provider_name=provider.name,
        timeout=profile.llm_timeout,
        max_retries=profile.llm_max_retries,
        initial_retry_delay=profile.llm_initial_retry_delay,
        retry_backoff=profile.llm_retry_backoff,
        summary_format_repair_retries=dependencies.summary_format_repair_retries,
    )


def _build_kimi_multimodal(
    provider: ResolvedLLMProvider,
    dependencies: SummarizerDependencies,
) -> KimiMultimodalSummarizer:
    profile = dependencies.profile
    return KimiMultimodalSummarizer(
        prompt_dir=dependencies.prompt_dir,
        prompt_name=dependencies.prompt_name,
        model=provider.model,
        api_key=provider.api_key,
        base_url=provider.base_url,
        provider_name=provider.name,
        http_client=dependencies.http_client,
        timeout=profile.llm_timeout,
        max_retries=profile.llm_max_retries,
        initial_retry_delay=profile.llm_initial_retry_delay,
        retry_backoff=profile.llm_retry_backoff,
        media_policy=dependencies.media_policy,
        summary_format_repair_retries=dependencies.summary_format_repair_retries,
    )


register_summarizer_builder("openai_text", _build_openai_text)
register_summarizer_builder("kimi_multimodal", _build_kimi_multimodal)
