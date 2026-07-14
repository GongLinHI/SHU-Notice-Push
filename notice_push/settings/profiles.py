from __future__ import annotations

from typing import Any, Mapping

from notice_push.domain import NoticeRuntimeProfile
from notice_push.settings.validation import (
    required_bool,
    required_float,
    required_int,
    required_mapping,
    required_optional_int,
)


REQUIRED_PROFILE_NAMES = ("daily", "backfill")
OPTIONAL_INT_PROFILE_KEYS = ("max_pages_per_source", "stop_after_seen_pages", "lookback_days")
INT_PROFILE_KEYS = (
    "detail_max_workers",
    "summary_max_workers",
    "http_timeout",
    "http_max_retries",
    "http_max_retry_delay_seconds",
    "failed_retry_limit",
    "failed_retry_after_hours",
    "refresh_seen_max_workers",
    "refresh_seen_limit",
    "llm_timeout",
    "llm_max_retries",
)
FLOAT_PROFILE_KEYS = (
    "http_initial_retry_delay",
    "http_retry_backoff",
    "llm_initial_retry_delay",
    "llm_retry_backoff",
)
BOOL_PROFILE_KEYS = ("retry_failed", "refresh_seen_details")
POSITIVE_INT_PROFILE_KEYS = {
    "detail_max_workers",
    "summary_max_workers",
    "http_timeout",
    "http_max_retry_delay_seconds",
    "refresh_seen_max_workers",
    "llm_timeout",
    "llm_max_retries",
}
FLOAT_PROFILE_MINIMUMS = {
    "http_initial_retry_delay": 0.0,
    "http_retry_backoff": 1.0,
    "llm_initial_retry_delay": 0.0,
    "llm_retry_backoff": 1.0,
}


def runtime_profiles(yaml_config: Mapping[str, Any]) -> dict[str, NoticeRuntimeProfile]:
    configured_profiles = required_mapping(yaml_config, "profiles")
    for name in REQUIRED_PROFILE_NAMES:
        required_mapping(yaml_config, f"profiles.{name}")
    return {name: _runtime_profile(name, yaml_config) for name in configured_profiles}


def _runtime_profile(name: str, yaml_config: Mapping[str, Any]) -> NoticeRuntimeProfile:
    field_path = ("profiles", name)
    required_mapping(yaml_config, field_path)
    values: dict[str, object] = {}
    for key in OPTIONAL_INT_PROFILE_KEYS:
        values[key] = required_optional_int(yaml_config, (*field_path, key), minimum=1)
    for key in INT_PROFILE_KEYS:
        minimum = 1 if key in POSITIVE_INT_PROFILE_KEYS else 0
        values[key] = required_int(yaml_config, (*field_path, key), minimum=minimum)
    for key in FLOAT_PROFILE_KEYS:
        values[key] = required_float(yaml_config, (*field_path, key), minimum=FLOAT_PROFILE_MINIMUMS[key])
    for key in BOOL_PROFILE_KEYS:
        values[key] = required_bool(yaml_config, (*field_path, key))
    return NoticeRuntimeProfile(name=name, **values)
