import pytest

from notice_push.domain import NoticeSource
from notice_push.sources.selection import select_sources


def _source(source_id: str, *, enabled: bool) -> NoticeSource:
    return NoticeSource(
        id=source_id,
        name=source_id,
        base_url=f"https://{source_id}.example/",
        list_url=f"https://{source_id}.example/notices",
        adapter=f"example.{source_id}.Adapter",
        enabled=enabled,
    )


def test_select_sources_uses_enabled_sources_by_default_and_allows_explicit_disabled_source():
    sources = (_source("enabled", enabled=True), _source("disabled", enabled=False))

    assert [source.id for source in select_sources(sources)] == ["enabled"]
    assert [source.id for source in select_sources(sources, ("disabled",))] == ["disabled"]


def test_select_sources_rejects_unknown_ids_with_complete_available_list():
    sources = (_source("enabled", enabled=True), _source("disabled", enabled=False))

    with pytest.raises(ValueError, match=r"Unknown source id\(s\): missing. Available sources: enabled, disabled"):
        select_sources(sources, ("missing",))
