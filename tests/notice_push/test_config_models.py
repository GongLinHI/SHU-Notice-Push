from datetime import datetime
from pathlib import Path

import pytest

from src.notice_push.config import load_config
from src.notice_push.models import NoticeListItem, NoticeRuntimeProfile, NoticeSource


def test_load_config_uses_defaults_and_repo_relative_paths(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)

    assert config.repo_root == tmp_path
    assert config.state_path == tmp_path / "resources" / "notice_state.sqlite3"
    assert config.output_dir == tmp_path / "resources" / "results"
    assert config.prompt_name == "notice_summary_v1"
    assert config.deepseek_model == "deepseek-chat"
    assert config.summary_max_workers == 5
    assert config.max_pages_per_source == 3
    assert config.stop_after_seen_pages == 2
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
    )
    assert [source.id for source in config.sources] == [
        "shu_official",
        "management_school",
        "graduate_school",
    ]


def test_load_config_supports_path_and_runtime_overrides(tmp_path):
    state_path = tmp_path / "isolated" / "state.sqlite3"
    output_dir = tmp_path / "isolated" / "results"

    config = load_config(
        env={
            "PROMPT_NAME": "notice_summary_v2",
            "DEEPSEEK_MODEL": "deepseek-reasoner",
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
    assert config.prompt_name == "notice_summary_v2"
    assert config.deepseek_model == "deepseek-reasoner"
    assert config.summary_max_workers == 2
    assert config.max_pages_per_source == 7
    assert config.stop_after_seen_pages == 4
    assert config.detail_min_chars == 80
    assert config.source_by_id("graduate_school").enabled is False


def test_load_config_supports_profile_specific_overrides(tmp_path):
    config = load_config(
        env={
            "DAILY_MAX_PAGES_PER_SOURCE": "6",
            "DAILY_STOP_AFTER_SEEN_PAGES": "3",
            "DAILY_DETAIL_MAX_WORKERS": "5",
            "DAILY_SUMMARY_MAX_WORKERS": "6",
            "DAILY_HTTP_TIMEOUT": "14",
            "DAILY_HTTP_MAX_RETRIES": "4",
            "DAILY_HTTP_INITIAL_RETRY_DELAY": "1.2",
            "BACKFILL_MAX_PAGES_PER_SOURCE": "25",
            "BACKFILL_STOP_AFTER_SEEN_PAGES": "0",
            "BACKFILL_DETAIL_MAX_WORKERS": "7",
            "BACKFILL_SUMMARY_MAX_WORKERS": "8",
            "BACKFILL_HTTP_TIMEOUT": "30",
            "BACKFILL_HTTP_MAX_RETRIES": "5",
            "BACKFILL_HTTP_INITIAL_RETRY_DELAY": "1.5",
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
    )


def test_load_config_reads_defaults_from_yaml_before_env_overrides(tmp_path):
    config_dir = tmp_path / "resources" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "runtime.yml").write_text(
        "\n".join(
            [
                "prompt_name: notice_summary_v3",
                "deepseek_model: deepseek-v4-flash",
                "summary_max_workers: 4",
                "max_pages_per_source: 9",
                "stop_after_seen_pages: 5",
                "detail_min_chars: 60",
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

    assert config.prompt_name == "notice_summary_v5"
    assert config.deepseek_model == "deepseek-v4-flash"
    assert config.summary_max_workers == 4
    assert config.max_pages_per_source == 9
    assert config.stop_after_seen_pages == 5
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
    assert config.runtime_profiles["daily"].http_timeout == 18
    assert config.runtime_profiles["daily"].http_max_retries == 4
    assert config.runtime_profiles["daily"].http_initial_retry_delay == 1.1


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
