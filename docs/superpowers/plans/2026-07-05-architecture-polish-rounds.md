# Architecture Polish Rounds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Run several focused optimization rounds after the initial rebuild fixes so the project is easier to extend with new notice sources, content types, and LLM providers.

**Architecture:** Keep `src.notice_push` as the only supported runtime path. First make report statistics and state ownership consistent, then reduce `NoticePipeline` and source adapter responsibilities, then isolate LLM transport/retry details from prompt/message construction.

**Tech Stack:** Python 3.12, pytest, sqlite3, BeautifulSoup, PyYAML, OpenAI-compatible SDK, conda environment `spider`.

---

## Scope

Implement in three approval-friendly rounds:

- Round 1: correct report stats and remove old CSV migration from the runtime path.
- Round 2: introduce explicit pipeline options/stats and extract reusable detail parsing.
- Round 3: clean up summarizer boundaries and shared OpenAI-compatible retry logic.

Do not implement:

- New notice sources.
- Video summarization.
- New external dependencies.
- Git commit or GitHub push.
- Any mutation of `resources/notice_records.csv`.

## Round 1: Statistics And State Ownership

### Task 1: Make Markdown Report Use Pipeline Counts

**Files:**

- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/report.py`
- Modify: `src/notice_push/pipeline.py`
- Test: `tests/notice_push/test_report.py`
- Test: `tests/notice_push/test_pipeline.py`

- [x] Add a `ReportStats` dataclass to `src/notice_push/models.py`:

```python
@dataclass(frozen=True)
class ReportStats:
    new_count: int
    retried_count: int
    summarized_count: int
    manual_review_count: int
```

- [x] Add a failing report test in `tests/notice_push/test_report.py` proving retry-only reports do not claim new notices:

```python
def test_render_report_uses_explicit_stats_for_retry_only_report():
    entry = make_entry()
    markdown = render_report(
        report_date=date(2026, 7, 5),
        entries=[entry],
        failures=[],
        stats=ReportStats(new_count=0, retried_count=1, summarized_count=1, manual_review_count=0),
    )

    assert "- 新增通知: 0" in markdown
    assert "- 重试通知: 1" in markdown
    assert "- 成功摘要: 1" in markdown
```

- [x] Update `render_report()` signature:

```python
def render_report(
    report_date: date,
    entries: list[ReportEntry],
    failures: list[FailedNotice],
    stats: ReportStats,
) -> str:
```

- [x] Replace the overview lines in `render_report()`:

```python
f"- 新增通知: {stats.new_count}",
f"- 重试通知: {stats.retried_count}",
f"- 成功摘要: {stats.summarized_count}",
f"- 需要人工复核: {stats.manual_review_count}",
```

- [x] In `NoticePipeline.run()`, create `ReportStats` before rendering:

```python
stats = ReportStats(
    new_count=new_count,
    retried_count=retried_count,
    summarized_count=len(entries),
    manual_review_count=len(failures),
)
markdown = render_report(report_day, entries, failures, stats)
```

- [x] Update existing report tests to pass explicit stats matching their current assertions.

- [x] Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_report.py tests/notice_push/test_pipeline.py -q
```

Expected: all selected tests pass.

### Task 2: Remove Legacy CSV Migration From Runtime Path

**Files:**

- Modify: `src/notice_push/pipeline.py`
- Modify: `src/notice_push/storage.py`
- Modify: `tests/notice_push/test_storage.py`
- Modify: `rebuild.md` only if you want the historical plan to reflect that migration is now retired.

- [x] Add a failing pipeline test in `tests/notice_push/test_pipeline.py` proving runtime does not read `resources/notice_records.csv`. Use a repo root with a malformed CSV and assert a normal run still succeeds:

```python
def test_pipeline_does_not_read_legacy_notice_records_csv(tmp_path):
    resources_dir = tmp_path / "resources"
    resources_dir.mkdir()
    (resources_dir / "notice_records.csv").write_text("\udcff", encoding="utf-8", errors="surrogatepass")
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    pipeline = NoticePipeline(
        config=config,
        storage=NoticeStorage(config.state_path, config.sources),
        http_client=FakeHttp({source.list_url: "list-1", "https://example.com/detail-1.htm": "detail"}),
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: FakeAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        limit=1,
        max_pages_per_source=1,
        report_date=date(2026, 7, 5),
    )

    assert result.new_count == 1
```

- [x] Remove this line from `NoticePipeline.run()`:

```python
self.storage.migrate_legacy_csv(self.config.repo_root / "resources" / "notice_records.csv")
```

- [x] Delete `NoticeStorage.migrate_legacy_csv()` and the `csv` import from `src/notice_push/storage.py`.

- [x] Remove CSV migration assertions from `test_storage_migrates_legacy_csv_and_bootstrap_baseline`; rename it to `test_storage_marks_bootstrap_baseline`.

- [x] Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py tests/notice_push/test_storage.py -q
```

Expected: all selected tests pass.

## Round 2: Pipeline And Detail Parsing Boundaries

### Task 3: Introduce PipelineRunOptions

**Files:**

- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/__main__.py`
- Modify: `src/notice_push/pipeline.py`
- Test: `tests/notice_push/test_cli.py`
- Test: `tests/notice_push/test_pipeline.py`

- [x] Add this dataclass to `src/notice_push/models.py`:

```python
@dataclass(frozen=True)
class PipelineRunOptions:
    source_ids: tuple[str, ...] = ()
    dry_run: bool = False
    limit: Optional[int] = None
    report_date: Optional[date] = None
    max_pages_per_source: Optional[int] = None
    stop_after_seen_pages: Optional[int] = None
    detail_max_workers: int = 1
    summary_max_workers: int = 1
    lookback_days: Optional[int] = None
    retry_failed: bool = False
    failed_retry_limit: int = 0
    failed_retry_after_hours: int = 0
    refresh_seen_details: bool = False
    refresh_seen_max_workers: int = 1
    refresh_seen_limit: int = 0
    bootstrap_seen: bool = False
```

Import `date` and `Optional` if needed.

- [x] Add a helper in `src/notice_push/__main__.py`:

```python
def run_options_from_args(args, profile: NoticeRuntimeProfile) -> PipelineRunOptions:
    return PipelineRunOptions(
        source_ids=tuple(args.sources or ()),
        dry_run=args.dry_run,
        limit=args.limit,
        report_date=date.fromisoformat(args.report_date) if args.report_date else None,
        max_pages_per_source=args.max_pages_per_source if args.max_pages_per_source is not None else profile.max_pages_per_source,
        stop_after_seen_pages=args.stop_after_seen_pages if args.stop_after_seen_pages is not None else profile.stop_after_seen_pages,
        detail_max_workers=args.detail_max_workers if args.detail_max_workers is not None else profile.detail_max_workers,
        summary_max_workers=args.summary_max_workers if args.summary_max_workers is not None else profile.summary_max_workers,
        lookback_days=args.lookback_days if args.lookback_days is not None else profile.lookback_days,
        retry_failed=profile.retry_failed,
        failed_retry_limit=profile.failed_retry_limit,
        failed_retry_after_hours=profile.failed_retry_after_hours,
        refresh_seen_details=profile.refresh_seen_details,
        refresh_seen_max_workers=profile.refresh_seen_max_workers,
        refresh_seen_limit=profile.refresh_seen_limit,
        bootstrap_seen=args.bootstrap_seen,
    )
```

- [x] Add/adjust CLI tests to assert `fake_pipeline.last_options` is a `PipelineRunOptions` with expected values instead of checking a large kwargs dict.

- [x] Change `NoticePipeline.run()` to accept one optional `options: PipelineRunOptions | None = None`. Keep keyword compatibility during the refactor if tests are easier, but route all logic through an options object internally.

- [x] Update `main()` to call:

```python
result = pipeline.run(run_options_from_args(args, profile))
```

- [x] Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_cli.py tests/notice_push/test_pipeline.py -q
```

Expected: all selected tests pass.

### Task 4: Extract Common DetailParser

**Files:**

- Create: `src/notice_push/detail_parser.py`
- Modify: `src/notice_push/sources/base.py`
- Modify: `src/notice_push/sources/shu_official.py`
- Modify: `src/notice_push/sources/management_school.py`
- Modify: `src/notice_push/sources/graduate_school.py`
- Test: `tests/notice_push/test_sources.py`
- Test: `tests/notice_push/test_html_utils.py`

- [x] Create `src/notice_push/detail_parser.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from src.notice_push.html_utils import (
    extract_detail_assets,
    extract_text_blocks,
    infer_content_kind,
    promote_primary_assets,
    select_main_content,
)
from src.notice_push.models import NoticeAsset


@dataclass(frozen=True)
class ParsedDetailBody:
    content: str
    assets: tuple[NoticeAsset, ...]
    content_kind: str
    content_node: Tag | None


class DetailParser:
    def parse_body(
        self,
        soup: BeautifulSoup,
        page_url: str,
        selectors: list[str],
        forced_content_kind: str | None = None,
    ) -> ParsedDetailBody:
        content_node = select_main_content(soup, selectors)
        assets = extract_detail_assets(content_node, soup, page_url)
        content = extract_text_blocks(content_node) if content_node else ""
        content_kind = forced_content_kind or infer_content_kind(content, assets)
        if forced_content_kind == "video":
            assets = ()
        else:
            assets = promote_primary_assets(content_kind, assets)
        return ParsedDetailBody(content=content, assets=assets, content_kind=content_kind, content_node=content_node)
```

- [x] Update `NoticeSourceAdapter.__init__` to accept an optional parser:

```python
def __init__(self, source: NoticeSource, detail_parser: DetailParser | None = None):
    self.source = source
    self.detail_parser = detail_parser or DetailParser()
```

- [x] Replace duplicated detail-body parsing in all three adapters with `self.detail_parser.parse_body(...)`.

- [x] In `GraduateSchoolAdapter`, keep the existing external-video special case by passing `forced_content_kind="video"` when `is_external_video_page(item.url)`.

- [x] Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_sources.py tests/notice_push/test_html_utils.py -q
```

Expected: all selected tests pass.

### Task 5: Remove Runtime Global Parsing Mutation

**Files:**

- Modify: `src/notice_push/html_utils.py`
- Modify: `src/notice_push/detail_parser.py`
- Modify: `src/notice_push/pipeline.py`
- Modify: `src/notice_push/__main__.py`
- Test: `tests/notice_push/test_html_utils.py`
- Test: `tests/notice_push/test_cli.py`

- [x] Add a `ParsingRules` dataclass to `src/notice_push/html_utils.py`:

```python
@dataclass(frozen=True)
class ParsingRules:
    external_video_domains: tuple[str, ...] = DEFAULT_EXTERNAL_VIDEO_DOMAINS
    noise_image_markers: tuple[str, ...] = DEFAULT_NOISE_IMAGE_MARKERS
```

- [x] Change `extract_image_assets()`, `extract_video_assets()`, `extract_assets()`, and `extract_detail_assets()` to accept `rules: ParsingRules = ParsingRules()` and use `rules.noise_image_markers` / `rules.external_video_domains`.

- [x] Change `is_external_video_page(url)` to accept `rules: ParsingRules = ParsingRules()`.

- [x] Remove `configure_parsing()` and its module-level mutation. Tests should no longer need `finally: configure_parsing()`.

- [x] In `DetailParser.__init__`, accept `rules: ParsingRules`.

- [x] In `build_pipeline()`, create a `ParsingRules` from `config.parsing`, pass it to `DetailParser`, and pass the parser into `NoticePipeline` or adapter factory.

- [x] Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_html_utils.py tests/notice_push/test_cli.py tests/notice_push/test_sources.py -q
```

Expected: all selected tests pass.

## Round 3: LLM Boundary Cleanup

### Task 6: Extract Shared Chat Retry Helper

**Files:**

- Create: `src/notice_push/llm_chat.py`
- Modify: `src/notice_push/summarizer.py`
- Test: `tests/notice_push/test_summarizer.py`

- [x] Create `src/notice_push/llm_chat.py`:

```python
from __future__ import annotations

import time
from typing import Optional


def create_chat_completion_with_retry(
    client,
    *,
    model: str,
    messages: list[dict],
    timeout: int,
    max_retries: int,
    initial_retry_delay: float,
    retry_backoff: float,
):
    last_error: Optional[Exception] = None
    for attempt in range(max(1, max_retries)):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False,
                timeout=timeout,
            )
            content = response.choices[0].message.content
            if not content or not content.strip():
                raise ValueError("empty summary response from model")
            return content
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= max(1, max_retries):
                break
            retry_delay = max(0.0, initial_retry_delay) * (max(1.0, retry_backoff) ** attempt)
            if retry_delay:
                time.sleep(retry_delay)
    raise last_error  # type: ignore[misc]
```

- [x] Replace both `_chat()` retry loops in `summarizer.py` with calls to `create_chat_completion_with_retry()`.

- [x] Update summarizer retry tests to monkeypatch `src.notice_push.llm_chat.time.sleep` instead of `src.notice_push.summarizer.time.sleep`.

- [x] Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_summarizer.py -q
```

Expected: all summarizer tests pass.

### Task 7: Move Visible Resource Formatting Out Of Summarizer

**Files:**

- Create: `src/notice_push/resources.py`
- Modify: `src/notice_push/summarizer.py`
- Modify: `src/notice_push/report.py`
- Test: `tests/notice_push/test_summarizer.py`
- Test: `tests/notice_push/test_report.py`

- [x] Create `src/notice_push/resources.py`:

```python
from __future__ import annotations

from src.notice_push.models import NoticeDetail


def visible_notice_resources(detail: NoticeDetail) -> tuple[tuple[str, str], ...]:
    resources: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for attachment in detail.attachments:
        if attachment.url and attachment.url not in seen_urls:
            resources.append((attachment.name or "通知附件", attachment.url))
            seen_urls.add(attachment.url)
    for asset in detail.assets:
        if asset.url and asset.url not in seen_urls:
            resources.append((asset.name or "通知资源", asset.url))
            seen_urls.add(asset.url)
    return tuple(resources)
```

- [x] Import `visible_notice_resources` from `src.notice_push.resources` in `summarizer.py` and `report.py`.

- [x] Remove `visible_notice_resources()` from `summarizer.py`.

- [x] Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_summarizer.py tests/notice_push/test_report.py -q
```

Expected: all selected tests pass.

## Final Verification

- [x] Run full tests:

```powershell
conda run --no-capture-output -n spider pytest -q
```

Expected: all tests pass.

- [x] Run compile check:

```powershell
conda run --no-capture-output -n spider python -m compileall -q src
```

Expected: exit code 0.

- [x] Run status check:

```powershell
git status --short
```

Expected: planned code/doc changes are visible. `resources/notice_records.csv` must remain unstaged and must not be modified by these tasks.

## Approval Gates

- Complete Round 1 first, run verification, then pause for review if the user wants a checkpoint.
- Complete Round 2 only after Round 1 is stable.
- Complete Round 3 last; it should not change external behavior.

No local commit and no GitHub push unless the user explicitly asks.

## Additional Review Polish

- [x] Replace detail-worker shared-list mutation with `DetailFetchResult` so concurrent detail failures are merged in source list order.
- [x] Add a regression test for concurrent detail failure ordering.
- [x] Remove unused eager LLM provider/client helpers from `src/notice_push/llm.py`; the runtime now uses only lazy optional provider resolution.

