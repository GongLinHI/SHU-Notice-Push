from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional

from dotenv import load_dotenv
import yaml

from notice_push.domain import (
    AppConfig,
    AuditPolicy,
    LLMProviderConfig,
    MediaPolicy,
    NoticeSource,
    ParsingConfig,
)
from notice_push.settings.profiles import runtime_profiles
from notice_push.settings.validation import (
    required_bool,
    required_int,
    required_mapping,
    required_non_empty_mapping,
    required_string,
    required_string_tuple,
)


SUPPORTED_LLM_PROVIDER_KINDS = frozenset({"openai_text", "kimi_multimodal"})
REQUIRED_LLM_ROUTES = ("text", "pdf", "image")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_yaml_config(root: Path) -> dict[str, Any]:
    config_path = root / "resources" / "config" / "runtime.yml"
    if not config_path.is_file():
        raise ValueError(f"Runtime config file is missing: {config_path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Runtime config must be a mapping: {config_path}")
    return data


def _sources(yaml_config: Mapping[str, Any]) -> tuple[NoticeSource, ...]:
    configured_sources = required_non_empty_mapping(yaml_config, "sources")
    sources: list[NoticeSource] = []
    for source_id, raw_config in configured_sources.items():
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("sources keys must be non-empty strings")
        path = f"sources.{source_id}"
        field_path = ("sources", source_id)
        if not isinstance(raw_config, Mapping):
            raise ValueError(f"{path} must be a mapping")
        sources.append(
            NoticeSource(
                id=source_id,
                name=required_string(yaml_config, (*field_path, "name")),
                base_url=required_string(yaml_config, (*field_path, "base_url")),
                list_url=required_string(yaml_config, (*field_path, "list_url")),
                adapter=required_string(yaml_config, (*field_path, "adapter")),
                enabled=required_bool(yaml_config, (*field_path, "enabled")),
            )
        )
    return tuple(sources)


def _llm_providers(yaml_config: Mapping[str, Any], env: Mapping[str, str]) -> dict[str, LLMProviderConfig]:
    configured_providers = required_non_empty_mapping(yaml_config, "llm.providers")
    providers: dict[str, LLMProviderConfig] = {}
    for provider_id, raw_config in configured_providers.items():
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("llm.providers keys must be non-empty strings")
        path = f"llm.providers.{provider_id}"
        field_path = ("llm", "providers", provider_id)
        if not isinstance(raw_config, Mapping):
            raise ValueError(f"{path} must be a mapping")
        kind = required_string(yaml_config, (*field_path, "kind"))
        if kind not in SUPPORTED_LLM_PROVIDER_KINDS:
            raise ValueError(
                f"{path}.kind has unsupported value '{kind}'. "
                f"Supported kinds: {', '.join(sorted(SUPPORTED_LLM_PROVIDER_KINDS))}"
            )
        model_env = required_string(yaml_config, (*field_path, "model_env"))
        default_model = required_string(yaml_config, (*field_path, "default_model"))
        providers[provider_id] = LLMProviderConfig(
            name=provider_id,
            base_url=required_string(yaml_config, (*field_path, "base_url")),
            api_key_env=required_string(yaml_config, (*field_path, "api_key_env")),
            model_env=model_env,
            default_model=env.get(model_env) or default_model,
            kind=kind,
        )
    return providers


def _llm_routing(yaml_config: Mapping[str, Any], providers: Mapping[str, LLMProviderConfig]) -> dict[str, str]:
    configured_routing = required_mapping(yaml_config, "llm.routing")
    for route in REQUIRED_LLM_ROUTES:
        required_string(yaml_config, f"llm.routing.{route}")
    routing: dict[str, str] = {}
    for content_kind, provider_id in configured_routing.items():
        if not isinstance(content_kind, str) or not content_kind.strip():
            raise ValueError("llm.routing keys must be non-empty strings")
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError(f"llm.routing.{content_kind} must be a non-empty string")
        routing[content_kind] = provider_id.strip()
    missing = sorted({provider_id for provider_id in routing.values() if provider_id not in providers})
    if missing:
        raise ValueError(
            "llm.routing references unknown LLM provider(s): "
            + ", ".join(missing)
            + ". Available providers: "
            + ", ".join(sorted(providers))
        )
    return routing


def _parsing_config(yaml_config: Mapping[str, Any]) -> ParsingConfig:
    required_mapping(yaml_config, "parsing")
    return ParsingConfig(
        external_video_domains=required_string_tuple(yaml_config, "parsing.external_video_domains"),
        noise_image_markers=required_string_tuple(yaml_config, "parsing.noise_image_markers"),
    )


def _media_policy(yaml_config: Mapping[str, Any]) -> MediaPolicy:
    required_mapping(yaml_config, "media")
    return MediaPolicy(
        pdf_max_bytes=required_int(yaml_config, "media.pdf_max_bytes", minimum=1),
        image_max_bytes=required_int(yaml_config, "media.image_max_bytes", minimum=1),
        pdf_extracted_text_max_chars=required_int(yaml_config, "media.pdf_extracted_text_max_chars", minimum=1),
    )


def _audit_policy(yaml_config: Mapping[str, Any]) -> AuditPolicy:
    required_mapping(yaml_config, "audit")
    return AuditPolicy(
        min_list_items=required_int(yaml_config, "audit.min_list_items", minimum=1),
        sample_detail_count=required_int(yaml_config, "audit.sample_detail_count", minimum=1),
        required_content_kinds=required_string_tuple(yaml_config, "audit.required_content_kinds"),
    )


def load_config(
    env: Optional[Mapping[str, str]] = None,
    repo_root: Optional[Path] = None,
    state_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> AppConfig:
    root = (repo_root or _repo_root()).resolve()
    yaml_config = _load_yaml_config(root)

    if env is None:
        load_dotenv(root / ".env")
        env = os.environ

    llm_providers = _llm_providers(yaml_config, env)
    return AppConfig(
        repo_root=root,
        state_path=Path(state_path or root / "resources" / "notice_state.sqlite3"),
        output_dir=Path(output_dir or root / "resources" / "results"),
        prompt_name=required_string(yaml_config, "prompt_name"),
        llm_providers=llm_providers,
        llm_routing=_llm_routing(yaml_config, llm_providers),
        summary_format_repair_retries=required_int(
            yaml_config,
            "llm.summary_format_repair_retries",
            minimum=0,
        ),
        parsing=_parsing_config(yaml_config),
        media_policy=_media_policy(yaml_config),
        audit_policy=_audit_policy(yaml_config),
        detail_min_chars=required_int(yaml_config, "detail_min_chars", minimum=1),
        runtime_profiles=runtime_profiles(yaml_config),
        sources=_sources(yaml_config),
    )
