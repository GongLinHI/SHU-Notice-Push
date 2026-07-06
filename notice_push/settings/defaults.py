from __future__ import annotations

from typing import Any

from notice_push.domain import AuditPolicy, MediaPolicy, ParsingConfig


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
DEFAULT_PARSING = ParsingConfig()
DEFAULT_MEDIA_POLICY = MediaPolicy()
DEFAULT_AUDIT_POLICY = AuditPolicy()
