from __future__ import annotations

from collections.abc import Iterable

from notice_push.domain import NoticeSource


def select_sources(
    sources: Iterable[NoticeSource],
    requested_ids: Iterable[str] | None = None,
) -> list[NoticeSource]:
    available_sources = tuple(sources)
    requested = set(requested_ids or ())
    if not requested:
        return [source for source in available_sources if source.enabled]

    selected = [source for source in available_sources if source.id in requested]
    found = {source.id for source in selected}
    missing = sorted(requested - found)
    if missing:
        available = ", ".join(source.id for source in available_sources)
        raise ValueError(f"Unknown source id(s): {', '.join(missing)}. Available sources: {available}")
    return selected
