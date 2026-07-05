from datetime import datetime
from pathlib import Path

import pytest

from src.notice_push.config import load_config
from src.notice_push.models import NoticeListItem, NoticeRuntimeProfile, NoticeSource, ParsingConfig


def test_load_config_uses_defaults_and_repo_relative_paths(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)

    assert config.repo_root == tmp_path
    assert config.state_path == tmp_path / "resources" / "notice_state.sqlite3"
    assert config.output_dir == tmp_path / "resources" / "results"
    assert config.prompt_name == "notice_summary_v1"
    assert not hasattr(config, "deepseek_model")
    assert config.llm_providers["deepseek"].base_url == "https://api.deepseek.com"
    assert config.llm_providers["deepseek"].api_key_env == "DEEPSEEK_API_KEY"
    assert config.llm_providers["deepseek"].model_env == "DEEPSEEK_MODEL"
    assert config.llm_providers["deepseek"].default_model == "deepseek-v4-flash"
    assert config.llm_providers["kimi"].base_url == "https://api.moonshot.cn/v1"
    assert config.llm_providers["kimi"].api_key_env == "KIMI_API_KEY"
    assert config.llm_providers["kimi"].model_env == "KIMI_MODEL"
    assert config.llm_providers["kimi"].default_model == "kimi-k2.7-code"
    assert config.llm_routing == {"text": "deepseek", "pdf": "kimi", "image": "kimi"}
    assert config.parsing == ParsingConfig(
        external_video_domains=("kankanews.com",),
        noise_image_markers=("logo", "icon", "wx", "weixin", "qr", "blank", "spacer"),
    )
    assert config.detail_min_chars == 30
    assert config.runtime_profiles["daily"] == NoticeRuntimeProfile(
        name="daily",
        max_pages_per_source=5,
        stop_after_seen_pages=2,
        detail_max_workers=2,
        summary_max_workers=3,
        http_timeout=12,
        http_max_retries=2,
        http_initial_retry_delay=0.8,
        lookback_days=365,
        retry_failed=True,
        failed_retry_limit=3,
        failed_retry_after_hours=12,
        refresh_seen_details=False,
        refresh_seen_max_workers=1,
        refresh_seen_limit=0,
        llm_timeout=60,
        llm_max_retries=3,
        llm_initial_retry_delay=1.0,
        llm_retry_backoff=2.0,
    )
    assert config.runtime_profiles["backfill"] == NoticeRuntimeProfile(
        name="backfill",
        max_pages_per_source=None,
        stop_after_seen_pages=None,
        detail_max_workers=4,
        summary_max_workers=3,
        http_timeout=20,
        http_max_retries=3,
        http_initial_retry_delay=1.0,
        lookback_days=365,
        retry_failed=True,
        failed_retry_limit=3,
        failed_retry_after_hours=6,
        refresh_seen_details=True,
        refresh_seen_max_workers=2,
        refresh_seen_limit=200,
        llm_timeout=90,
        llm_max_retries=3,
        llm_initial_retry_delay=1.0,
        llm_retry_backoff=2.0,
    )
    assert [source.id for source in config.sources] == [
        "shu_official",
        "management_school",
        "graduate_school",
    ]


def test_load_config_supports_path_and_model_env_override_only(tmp_path):
    state_path = tmp_path / "isolated" / "state.sqlite3"
    output_dir = tmp_path / "isolated" / "results"

    config = load_config(
        env={
            "PROMPT_NAME": "notice_summary_v2",
            "DEEPSEEK_MODEL": "deepseek-v4-flash",
            "SUMMARY_MAX_WORKERS": "2",
            "MAX_PAGES_PER_SOURCE": "7",
            "STOP_AFTER_SEEN_PAGES": "4",
            "DETAIL_MIN_CHARS": "80",
            "SOURCE_GRADUATE_SCHOOL_ENABLED": "false",
        },
        repo_root=tmp_path,
        state_path=state_path,
        output_dir=output_dir,
    )

    assert config.state_path == state_path
    assert config.output_dir == output_dir
    assert config.prompt_name == "notice_summary_v1"
    assert config.llm_providers["deepseek"].default_model == "deepseek-v4-flash"
    assert config.detail_min_chars == 30
    assert config.source_by_id("graduate_school").enabled is True


def test_load_config_reads_profile_values_from_yaml_not_environment(tmp_path):
    config_dir = tmp_path / "resources" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "runtime.yml").write_text(
        "\n".join(
            [
                "profiles:",
                "  daily:",
                "    max_pages_per_source: 6",
                "    stop_after_seen_pages: 3",
                "    detail_max_workers: 5",
                "    summary_max_workers: 6",
                "    http_timeout: 14",
                "    http_max_retries: 4",
                "    http_initial_retry_delay: 1.2",
                "    lookback_days: 120",
                "    retry_failed: false",
                "    failed_retry_limit: 9",
                "    failed_retry_after_hours: 3",
                "    refresh_seen_details: true",
                "    refresh_seen_max_workers: 2",
                "    refresh_seen_limit: 12",
                "    llm_timeout: 55",
                "    llm_max_retries: 4",
                "    llm_initial_retry_delay: 1.3",
                "    llm_retry_backoff: 2.5",
                "  backfill:",
                "    max_pages_per_source: 25",
                "    stop_after_seen_pages: 0",
                "    detail_max_workers: 7",
                "    summary_max_workers: 8",
                "    http_timeout: 30",
                "    http_max_retries: 5",
                "    http_initial_retry_delay: 1.5",
                "    lookback_days: 730",
                "    retry_failed: true",
                "    failed_retry_limit: 8",
                "    failed_retry_after_hours: 1",
                "    refresh_seen_details: false",
                "    refresh_seen_max_workers: 5",
                "    refresh_seen_limit: 0",
                "    llm_timeout: 80",
                "    llm_max_retries: 5",
                "    llm_initial_retry_delay: 1.7",
                "    llm_retry_backoff: 3.0",
            ]
        ),
        encoding="utf-8",
    )
    config = load_config(
        env={
            "DAILY_MAX_PAGES_PER_SOURCE": "99",
            "BACKFILL_MAX_PAGES_PER_SOURCE": "99",
        },
        repo_root=tmp_path,
    )

    assert config.runtime_profiles["daily"] == NoticeRuntimeProfile(
        name="daily",
        max_pages_per_source=6,
        stop_after_seen_pages=3,
        detail_max_workers=5,
        summary_max_workers=6,
        http_timeout=14,
        http_max_retries=4,
        http_initial_retry_delay=1.2,
        lookback_days=120,
        retry_failed=False,
        failed_retry_limit=9,
        failed_retry_after_hours=3,
        refresh_seen_details=True,
        refresh_seen_max_workers=2,
        refresh_seen_limit=12,
        llm_timeout=55,
        llm_max_retries=4,
        llm_initial_retry_delay=1.3,
        llm_retry_backoff=2.5,
    )
    assert config.runtime_profiles["backfill"] == NoticeRuntimeProfile(
        name="backfill",
        max_pages_per_source=25,
        stop_after_seen_pages=None,
        detail_max_workers=7,
        summary_max_workers=8,
        http_timeout=30,
        http_max_retries=5,
        http_initial_retry_delay=1.5,
        lookback_days=730,
        retry_failed=True,
        failed_retry_limit=8,
        failed_retry_after_hours=1,
        refresh_seen_details=False,
        refresh_seen_max_workers=5,
        refresh_seen_limit=0,
        llm_timeout=80,
        llm_max_retries=5,
        llm_initial_retry_delay=1.7,
        llm_retry_backoff=3.0,
    )


def test_load_config_reads_llm_provider_values_from_yaml(tmp_path):
    config_dir = tmp_path / "resources" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "runtime.yml").write_text(
        "\n".join(
            [
                "llm:",
                "  providers:",
                "    deepseek:",
                "      base_url: https://deepseek.example/v1",
                "      api_key_env: CUSTOM_DEEPSEEK_KEY",
                "      model_env: CUSTOM_DEEPSEEK_MODEL",
                "      default_model: deepseek-test",
                "    kimi:",
                "      base_url: https://kimi.example/v1",
                "      api_key_env: CUSTOM_KIMI_KEY",
                "      model_env: CUSTOM_KIMI_MODEL",
                "      default_model: kimi-test",
                "  routing:",
                "    text: deepseek",
                "    pdf: kimi",
                "    image: kimi",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(
        env={
            "CUSTOM_DEEPSEEK_MODEL": "deepseek-env",
            "CUSTOM_KIMI_MODEL": "kimi-env",
        },
        repo_root=tmp_path,
    )

    assert config.llm_providers["deepseek"].base_url == "https://deepseek.example/v1"
    assert config.llm_providers["deepseek"].model_env == "CUSTOM_DEEPSEEK_MODEL"
    assert config.llm_providers["deepseek"].default_model == "deepseek-env"
    assert config.llm_providers["kimi"].base_url == "https://kimi.example/v1"
    assert config.llm_providers["kimi"].model_env == "CUSTOM_KIMI_MODEL"
    assert config.llm_providers["kimi"].default_model == "kimi-env"
    assert config.llm_routing["text"] == "deepseek"
    assert config.llm_routing["pdf"] == "kimi"
    assert config.llm_routing["image"] == "kimi"


def test_load_config_reads_parsing_values_from_yaml(tmp_path):
    config_dir = tmp_path / "resources" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "runtime.yml").write_text(
        "\n".join(
            [
                "parsing:",
                "  external_video_domains:",
                "    - video.example.edu",
                "  noise_image_markers:",
                "    - tracking",
                "    - spacer",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(env={}, repo_root=tmp_path)

    assert config.parsing == ParsingConfig(
        external_video_domains=("video.example.edu",),
        noise_image_markers=("tracking", "spacer"),
    )


def test_load_config_ignores_legacy_top_level_deepseek_model(tmp_path):
    config_dir = tmp_path / "resources" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "runtime.yml").write_text(
        "deepseek_model: legacy-deepseek-model\n",
        encoding="utf-8",
    )

    config = load_config(env={}, repo_root=tmp_path)

    assert not hasattr(config, "deepseek_model")
    assert config.llm_providers["deepseek"].default_model == "deepseek-v4-flash"


def test_load_config_reads_runtime_values_from_yaml(tmp_path):
    config_dir = tmp_path / "resources" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "runtime.yml").write_text(
        "\n".join(
            [
                "prompt_name: notice_summary_v3",
                "detail_min_chars: 60",
                "llm:",
                "  providers:",
                "    deepseek:",
                "      default_model: deepseek-yaml",
                "sources:",
                "  custom_source:",
                "    name: 自定义通知源",
                "    base_url: https://custom.example.edu/",
                "    list_url: https://custom.example.edu/notices.htm",
                "    adapter: custom_adapter",
                "    enabled: true",
                "  graduate_school:",
                "    enabled: false",
                "profiles:",
                "  daily:",
                "    max_pages_per_source: 8",
                "    stop_after_seen_pages: 3",
                "    detail_max_workers: 3",
                "    summary_max_workers: 4",
                "    http_timeout: 16",
                "    http_max_retries: 4",
                "    http_initial_retry_delay: 1.1",
                "    lookback_days: 180",
                "    retry_failed: true",
                "    failed_retry_limit: 4",
                "    failed_retry_after_hours: 2",
                "    refresh_seen_details: true",
                "    refresh_seen_max_workers: 2",
                "    refresh_seen_limit: 10",
                "    llm_timeout: 75",
                "    llm_max_retries: 4",
                "    llm_initial_retry_delay: 1.4",
                "    llm_retry_backoff: 2.1",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(
        env={
            "PROMPT_NAME": "notice_summary_v5",
            "DAILY_HTTP_TIMEOUT": "18",
        },
        repo_root=tmp_path,
    )

    assert config.prompt_name == "notice_summary_v3"
    assert config.llm_providers["deepseek"].default_model == "deepseek-yaml"
    assert config.detail_min_chars == 60
    assert config.source_by_id("custom_source") == NoticeSource(
        id="custom_source",
        name="自定义通知源",
        base_url="https://custom.example.edu/",
        list_url="https://custom.example.edu/notices.htm",
        adapter="custom_adapter",
        enabled=True,
    )
    assert config.source_by_id("graduate_school").enabled is False
    assert config.runtime_profiles["daily"].max_pages_per_source == 8
    assert config.runtime_profiles["daily"].detail_max_workers == 3
    assert config.runtime_profiles["daily"].summary_max_workers == 4
    assert config.runtime_profiles["daily"].http_timeout == 16
    assert config.runtime_profiles["daily"].http_max_retries == 4
    assert config.runtime_profiles["daily"].http_initial_retry_delay == 1.1
    assert config.runtime_profiles["daily"].lookback_days == 180
    assert config.runtime_profiles["daily"].retry_failed is True
    assert config.runtime_profiles["daily"].failed_retry_limit == 4
    assert config.runtime_profiles["daily"].failed_retry_after_hours == 2
    assert config.runtime_profiles["daily"].refresh_seen_details is True
    assert config.runtime_profiles["daily"].refresh_seen_max_workers == 2
    assert config.runtime_profiles["daily"].refresh_seen_limit == 10
    assert config.runtime_profiles["daily"].llm_timeout == 75
    assert config.runtime_profiles["daily"].llm_max_retries == 4
    assert config.runtime_profiles["daily"].llm_initial_retry_delay == 1.4
    assert config.runtime_profiles["daily"].llm_retry_backoff == 2.1


def test_notice_source_and_list_item_are_immutable():
    source = NoticeSource(
        id="shu_official",
        name="上海大学官网",
        base_url="https://www.shu.edu.cn/",
        list_url="https://www.shu.edu.cn/tzgg.htm",
        adapter="shu_official",
    )
    item = NoticeListItem(
        source_id=source.id,
        url="https://www.shu.edu.cn/info/1051/397035.htm",
        canonical_url="https://www.shu.edu.cn/info/1051/397035.htm",
        title="关于宝山校区部分楼宇停电的通知",
        published_at=datetime(2026, 6, 16),
        list_excerpt="目录页摘要只用于调试",
    )

    with pytest.raises(AttributeError):
        source.name = "changed"
    with pytest.raises(AttributeError):
        item.title = "changed"


def test_source_by_id_rejects_unknown_source(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)

    with pytest.raises(KeyError):
        config.source_by_id("missing")


def test_runtime_profile_by_name_rejects_unknown_profile(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)

    with pytest.raises(KeyError):
        config.runtime_profile("missing")
