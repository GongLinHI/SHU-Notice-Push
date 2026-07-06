from __future__ import annotations

import os
from dataclasses import dataclass

from notice_push.domain import LLMProviderConfig


@dataclass(frozen=True)
class ResolvedLLMProvider:
    name: str
    base_url: str
    api_key: str
    model: str


def resolve_optional_provider(
    name: str,
    config: LLMProviderConfig,
    env: dict[str, str] | None = None,
) -> ResolvedLLMProvider:
    active_env = env or os.environ
    return ResolvedLLMProvider(
        name=name,
        base_url=config.base_url,
        api_key=active_env.get(config.api_key_env, ""),
        model=active_env.get(config.model_env, config.default_model),
    )
