from __future__ import annotations

from typing import Any, Mapping, Optional

from notice_push.domain import NoticeRuntimeProfile
from notice_push.settings.defaults import (
    BOOL_PROFILE_KEYS,
    FLOAT_PROFILE_KEYS,
    INT_PROFILE_KEYS,
    OPTIONAL_INT_PROFILE_KEYS,
    PROFILE_DEFAULTS,
)


def runtime_profiles(yaml_config: Mapping[str, Any]) -> dict[str, NoticeRuntimeProfile]:
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
