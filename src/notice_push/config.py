from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional

from dotenv import load_dotenv
import yaml

from src.notice_push.models import AppConfig, LLMProviderConfig, NoticeRuntimeProfile, NoticeSource


PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "daily": {
        "max_pages_per_source": 5,
        "stop_after_seen_pages": 2,
        "detail_max_workers": 2,
        "summary_max_workers": 3,
        "http_timeout": 12,
        "http_max_retries": 2,
        "http_initial_retry_delay": 0.8,
        "lookback_days": 365,
        "retry_failed": True,
        "failed_retry_limit": 3,
        "failed_retry_after_hours": 12,
        "refresh_seen_details": False,
        "refresh_seen_max_workers": 1,
        "refresh_seen_limit": 0,
        "llm_timeout": 60,
        "llm_max_retries": 3,
        "llm_initial_retry_delay": 1.0,
        "llm_retry_backoff": 2.0,
    },
    "backfill": {
        "max_pages_per_source": None,
        "stop_after_seen_pages": None,
        "detail_max_workers": 4,
        "summary_max_workers": 3,
        "http_timeout": 20,
        "http_max_retries": 3,
        "http_initial_retry_delay": 1.0,
        "lookback_days": 365,
        "retry_failed": True,
        "failed_retry_limit": 3,
        "failed_retry_after_hours": 6,
        "refresh_seen_details": True,
        "refresh_seen_max_workers": 2,
        "refresh_seen_limit": 200,
        "llm_timeout": 90,
        "llm_max_retries": 3,
        "llm_initial_retry_delay": 1.0,
        "llm_retry_backoff": 2.0,
    },
}

OPTIONAL_INT_PROFILE_KEYS = {"max_pages_per_source", "stop_after_seen_pages", "lookback_days"}
INT_PROFILE_KEYS = {
    "detail_max_workers",
    "summary_max_workers",
    "http_timeout",
    "http_max_retries",
    "failed_retry_limit",
    "failed_retry_after_hours",
    "refresh_seen_max_workers",
    "refresh_seen_limit",
    "llm_timeout",
    "llm_max_retries",
}
FLOAT_PROFILE_KEYS = {"http_initial_retry_delay", "llm_initial_retry_delay", "llm_retry_backoff"}
BOOL_PROFILE_KEYS = {"retry_failed", "refresh_seen_details"}
DEFAULT_LLM_PROVIDERS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "model_env": "DEEPSEEK_MODEL",
        "default_model": "deepseek-v4-flash",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "api_key_env": "KIMI_API_KEY",
        "model_env": "KIMI_MODEL",
        "default_model": "kimi-k2.7-code",
    },
}
DEFAULT_LLM_ROUTING = {"text": "deepseek", "pdf": "kimi", "image": "kimi"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_yaml_config(root: Path) -> dict[str, Any]:
    config_path = root / "resources" / "config" / "runtime.yml"
    if not config_path.exists():
        return {}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Runtime config must be a mapping: {config_path}")
    return data


def _yaml_value(data: Mapping[str, Any], *path: str, default=None):
    current: Any = data
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return default
        current = current[key]
    return current


def _int_value(raw, default: int) -> int:
    if raw is None or raw == "":
        return default
    return int(raw)


def _optional_int_value(raw, default: Optional[int]) -> Optional[int]:
    if raw is None or raw == "":
        if default is None or default == "":
            return None
        value = int(default)
        return None if value <= 0 else value
    value = int(raw)
    return None if value <= 0 else value


def _float_value(raw, default: float) -> float:
    if raw is None or raw == "":
        return default
    return float(raw)


def _bool_value(raw, default: bool = True) -> bool:
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _source_enabled(yaml_config: Mapping[str, Any], source_key: str) -> bool:
    return _bool_value(_yaml_value(yaml_config, "sources", source_key, "enabled", default=True), True)


def _built_in_source_defaults() -> dict[str, dict[str, str]]:
    return {
        "shu_official": {
            "name": "上海大学官网",
            "base_url": "https://www.shu.edu.cn/",
            "list_url": "https://www.shu.edu.cn/tzgg.htm",
            "adapter": "src.notice_push.sources.shu_official.ShuOfficialAdapter",
        },
        "management_school": {
            "name": "上海大学管理学院",
            "base_url": "https://ms.shu.edu.cn/",
            "list_url": "https://ms.shu.edu.cn/syzl/zytz.htm",
            "adapter": "src.notice_push.sources.management_school.ManagementSchoolAdapter",
        },
        "graduate_school": {
            "name": "上海大学研究生院",
            "base_url": "https://gs.shu.edu.cn/",
            "list_url": "https://gs.shu.edu.cn/xwlb/sy.htm",
            "adapter": "src.notice_push.sources.graduate_school.GraduateSchoolAdapter",
        },
    }


def _source_value(
    source_id: str,
    source_config: Mapping[str, Any],
    defaults: Mapping[str, Mapping[str, str]],
    key: str,
) -> str:
    value = source_config.get(key)
    if value is not None:
        return str(value)
    try:
        return defaults[source_id][key]
    except KeyError as exc:
        raise ValueError(f"Source '{source_id}' must define '{key}' in runtime.yml") from exc


def _default_sources(yaml_config: Mapping[str, Any]) -> tuple[NoticeSource, ...]:
    defaults = _built_in_source_defaults()
    yaml_sources = _yaml_value(yaml_config, "sources", default={})
    if yaml_sources is None:
        yaml_sources = {}
    if not isinstance(yaml_sources, Mapping):
        raise ValueError("Runtime config 'sources' must be a mapping")

    source_ids = list(defaults)
    source_ids.extend(source_id for source_id in yaml_sources if source_id not in defaults)

    sources: list[NoticeSource] = []
    for source_id in source_ids:
        source_config = yaml_sources.get(source_id) or {}
        if not isinstance(source_config, Mapping):
            raise ValueError(f"Source '{source_id}' config must be a mapping")
        sources.append(
            NoticeSource(
                id=source_id,
                name=_source_value(source_id, source_config, defaults, "name"),
                base_url=_source_value(source_id, source_config, defaults, "base_url"),
                list_url=_source_value(source_id, source_config, defaults, "list_url"),
                adapter=_source_value(source_id, source_config, defaults, "adapter"),
                enabled=_source_enabled(yaml_config, source_id),
            )
        )
    return tuple(sources)


def _runtime_profiles(yaml_config: Mapping[str, Any]) -> dict[str, NoticeRuntimeProfile]:
    return {name: _runtime_profile(name, defaults, yaml_config) for name, defaults in PROFILE_DEFAULTS.items()}


def _runtime_profile(
    name: str,
    defaults: Mapping[str, Any],
    yaml_config: Mapping[str, Any],
) -> NoticeRuntimeProfile:
    values = {key: _profile_value(yaml_config, name, key, default) for key, default in defaults.items()}
    return NoticeRuntimeProfile(name=name, **values)


def _profile_value(yaml_config: Mapping[str, Any], profile_name: str, key: str, default):
    raw = _yaml_value(yaml_config, "profiles", profile_name, key, default=default)
    if key in OPTIONAL_INT_PROFILE_KEYS:
        return _optional_int_value(raw, default)
    if key in INT_PROFILE_KEYS:
        return _int_value(raw, int(default))
    if key in FLOAT_PROFILE_KEYS:
        return _float_value(raw, float(default))
    if key in BOOL_PROFILE_KEYS:
        return _bool_value(raw, bool(default))
    return raw


def _llm_providers(yaml_config: Mapping[str, Any], env: Mapping[str, str]) -> dict[str, LLMProviderConfig]:
    yaml_providers = _yaml_value(yaml_config, "llm", "providers", default={}) or {}
    if not isinstance(yaml_providers, Mapping):
        raise ValueError("Runtime config 'llm.providers' must be a mapping")

    provider_ids = list(DEFAULT_LLM_PROVIDERS)
    provider_ids.extend(provider_id for provider_id in yaml_providers if provider_id not in DEFAULT_LLM_PROVIDERS)

    providers: dict[str, LLMProviderConfig] = {}
    for provider_id in provider_ids:
        provider_config = yaml_providers.get(provider_id) or {}
        if not isinstance(provider_config, Mapping):
            raise ValueError(f"LLM provider '{provider_id}' config must be a mapping")
        defaults = DEFAULT_LLM_PROVIDERS.get(provider_id, {})
        model_env = str(provider_config.get("model_env", defaults.get("model_env", f"{provider_id.upper()}_MODEL")))
        default_model = str(provider_config.get("default_model", defaults.get("default_model", "")))
        if provider_id == "deepseek" and "deepseek_model" in yaml_config and "default_model" not in provider_config:
            default_model = str(yaml_config["deepseek_model"])
        providers[provider_id] = LLMProviderConfig(
            name=provider_id,
            base_url=str(provider_config.get("base_url", defaults.get("base_url", ""))),
            api_key_env=str(provider_config.get("api_key_env", defaults.get("api_key_env", f"{provider_id.upper()}_API_KEY"))),
            model_env=model_env,
            default_model=env.get(model_env, default_model),
        )
    return providers


def _llm_routing(yaml_config: Mapping[str, Any]) -> dict[str, str]:
    routing = dict(DEFAULT_LLM_ROUTING)
    yaml_routing = _yaml_value(yaml_config, "llm", "routing", default={}) or {}
    if not isinstance(yaml_routing, Mapping):
        raise ValueError("Runtime config 'llm.routing' must be a mapping")
    routing.update({str(key): str(value) for key, value in yaml_routing.items()})
    return routing


def load_config(
    env: Optional[Mapping[str, str]] = None,
    repo_root: Optional[Path] = None,
    state_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> AppConfig:
    root = (repo_root or _repo_root()).resolve()
    yaml_config = _load_yaml_config(root)

    if env is None:
        load_dotenv()
        env = os.environ

    resolved_state_path = state_path or root / "resources" / "notice_state.sqlite3"
    resolved_output_dir = output_dir or root / "resources" / "results"
    llm_providers = _llm_providers(yaml_config, env)

    return AppConfig(
        repo_root=root,
        state_path=Path(resolved_state_path),
        output_dir=Path(resolved_output_dir),
        prompt_name=str(_yaml_value(yaml_config, "prompt_name", default="notice_summary_v1")),
        deepseek_model=llm_providers["deepseek"].default_model,
        llm_providers=llm_providers,
        llm_routing=_llm_routing(yaml_config),
        detail_min_chars=int(_yaml_value(yaml_config, "detail_min_chars", default=30)),
        runtime_profiles=_runtime_profiles(yaml_config),
        sources=_default_sources(yaml_config),
    )
