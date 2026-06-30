from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional

from dotenv import load_dotenv
import yaml

from src.notice_push.models import AppConfig, NoticeRuntimeProfile, NoticeSource


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


def _as_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _as_optional_int(env: Mapping[str, str], name: str, default: Optional[int]) -> Optional[int]:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    value = int(raw)
    return None if value <= 0 else value


def _as_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _as_bool(env: Mapping[str, str], name: str, default: bool = True) -> bool:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _source_enabled(env: Mapping[str, str], yaml_config: Mapping[str, Any], source_key: str) -> bool:
    default = bool(_yaml_value(yaml_config, "sources", source_key, "enabled", default=True))
    env_name = f"SOURCE_{source_key.upper()}_ENABLED"
    return _as_bool(env, env_name, default)


def _built_in_source_defaults() -> dict[str, dict[str, str]]:
    return {
        "shu_official": {
            "name": "上海大学官网",
            "base_url": "https://www.shu.edu.cn/",
            "list_url": "https://www.shu.edu.cn/tzgg.htm",
            "adapter": "shu_official",
        },
        "management_school": {
            "name": "上海大学管理学院",
            "base_url": "https://ms.shu.edu.cn/",
            "list_url": "https://ms.shu.edu.cn/syzl/zytz.htm",
            "adapter": "management_school",
        },
        "graduate_school": {
            "name": "上海大学研究生院",
            "base_url": "https://gs.shu.edu.cn/",
            "list_url": "https://gs.shu.edu.cn/xwlb/sy.htm",
            "adapter": "graduate_school",
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


def _default_sources(env: Mapping[str, str], yaml_config: Mapping[str, Any]) -> tuple[NoticeSource, ...]:
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
                enabled=_source_enabled(env, yaml_config, source_id),
            )
        )
    return tuple(sources)


def _runtime_profiles(env: Mapping[str, str], yaml_config: Mapping[str, Any]) -> dict[str, NoticeRuntimeProfile]:
    return {
        "daily": NoticeRuntimeProfile(
            name="daily",
            max_pages_per_source=_as_optional_int(
                env,
                "DAILY_MAX_PAGES_PER_SOURCE",
                _yaml_value(yaml_config, "profiles", "daily", "max_pages_per_source", default=5),
            ),
            stop_after_seen_pages=_as_optional_int(
                env,
                "DAILY_STOP_AFTER_SEEN_PAGES",
                _yaml_value(yaml_config, "profiles", "daily", "stop_after_seen_pages", default=2),
            ),
            detail_max_workers=_as_int(
                env,
                "DAILY_DETAIL_MAX_WORKERS",
                int(_yaml_value(yaml_config, "profiles", "daily", "detail_max_workers", default=2)),
            ),
            summary_max_workers=_as_int(
                env,
                "DAILY_SUMMARY_MAX_WORKERS",
                int(_yaml_value(yaml_config, "profiles", "daily", "summary_max_workers", default=3)),
            ),
            http_timeout=_as_int(
                env,
                "DAILY_HTTP_TIMEOUT",
                int(_yaml_value(yaml_config, "profiles", "daily", "http_timeout", default=12)),
            ),
            http_max_retries=_as_int(
                env,
                "DAILY_HTTP_MAX_RETRIES",
                int(_yaml_value(yaml_config, "profiles", "daily", "http_max_retries", default=2)),
            ),
            http_initial_retry_delay=_as_float(
                env,
                "DAILY_HTTP_INITIAL_RETRY_DELAY",
                float(_yaml_value(yaml_config, "profiles", "daily", "http_initial_retry_delay", default=0.8)),
            ),
        ),
        "backfill": NoticeRuntimeProfile(
            name="backfill",
            max_pages_per_source=_as_optional_int(
                env,
                "BACKFILL_MAX_PAGES_PER_SOURCE",
                _yaml_value(yaml_config, "profiles", "backfill", "max_pages_per_source", default=None),
            ),
            stop_after_seen_pages=_as_optional_int(
                env,
                "BACKFILL_STOP_AFTER_SEEN_PAGES",
                _yaml_value(yaml_config, "profiles", "backfill", "stop_after_seen_pages", default=None),
            ),
            detail_max_workers=_as_int(
                env,
                "BACKFILL_DETAIL_MAX_WORKERS",
                int(_yaml_value(yaml_config, "profiles", "backfill", "detail_max_workers", default=4)),
            ),
            summary_max_workers=_as_int(
                env,
                "BACKFILL_SUMMARY_MAX_WORKERS",
                int(_yaml_value(yaml_config, "profiles", "backfill", "summary_max_workers", default=3)),
            ),
            http_timeout=_as_int(
                env,
                "BACKFILL_HTTP_TIMEOUT",
                int(_yaml_value(yaml_config, "profiles", "backfill", "http_timeout", default=20)),
            ),
            http_max_retries=_as_int(
                env,
                "BACKFILL_HTTP_MAX_RETRIES",
                int(_yaml_value(yaml_config, "profiles", "backfill", "http_max_retries", default=3)),
            ),
            http_initial_retry_delay=_as_float(
                env,
                "BACKFILL_HTTP_INITIAL_RETRY_DELAY",
                float(_yaml_value(yaml_config, "profiles", "backfill", "http_initial_retry_delay", default=1.0)),
            ),
        ),
    }


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
        prompt_name=env.get("PROMPT_NAME", str(_yaml_value(yaml_config, "prompt_name", default="notice_summary_v1"))),
        deepseek_model=env.get("DEEPSEEK_MODEL", str(_yaml_value(yaml_config, "deepseek_model", default="deepseek-chat"))),
        summary_max_workers=_as_int(env, "SUMMARY_MAX_WORKERS", int(_yaml_value(yaml_config, "summary_max_workers", default=5))),
        max_pages_per_source=_as_int(env, "MAX_PAGES_PER_SOURCE", int(_yaml_value(yaml_config, "max_pages_per_source", default=3))),
        stop_after_seen_pages=_as_int(env, "STOP_AFTER_SEEN_PAGES", int(_yaml_value(yaml_config, "stop_after_seen_pages", default=2))),
        detail_min_chars=_as_int(env, "DETAIL_MIN_CHARS", int(_yaml_value(yaml_config, "detail_min_chars", default=30))),
        runtime_profiles=_runtime_profiles(env, yaml_config),
        sources=_default_sources(env, yaml_config),
    )
