from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional

from dotenv import load_dotenv
import yaml

from src.notice_push.models import AppConfig, NoticeRuntimeProfile, NoticeSource


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

    return AppConfig(
        repo_root=root,
        state_path=Path(resolved_state_path),
        output_dir=Path(resolved_output_dir),
        prompt_name=str(_yaml_value(yaml_config, "prompt_name", default="notice_summary_v1")),
        deepseek_model=env.get(
            "DEEPSEEK_MODEL",
            str(_yaml_value(yaml_config, "deepseek_model", default="deepseek-v4-flash")),
        ),
        detail_min_chars=int(_yaml_value(yaml_config, "detail_min_chars", default=30)),
        runtime_profiles=_runtime_profiles(yaml_config),
        sources=_default_sources(yaml_config),
    )
