from __future__ import annotations

import os
from dataclasses import dataclass

from openai import OpenAI

from src.notice_push.models import LLMProviderConfig


@dataclass(frozen=True)
class ResolvedLLMProvider:
    name: str
    base_url: str
    api_key: str
    model: str


def resolve_provider(
    name: str,
    config: LLMProviderConfig,
    env: dict[str, str] | None = None,
) -> ResolvedLLMProvider:
    active_env = env or os.environ
    api_key = active_env.get(config.api_key_env, "")
    if not api_key:
        raise ValueError(f"{config.api_key_env} must be provided for provider '{name}'")
    model = active_env.get(config.model_env, config.default_model)
    return ResolvedLLMProvider(
        name=name,
        base_url=config.base_url,
        api_key=api_key,
        model=model,
    )


def create_openai_client(provider: ResolvedLLMProvider) -> OpenAI:
    return OpenAI(api_key=provider.api_key, base_url=provider.base_url)
