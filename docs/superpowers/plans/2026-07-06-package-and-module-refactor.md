# Package And Module Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目从 `src.notice_push` 包路径重构为顶层 `notice_push` 包，并拆分当前过长 Python 文件，让包结构、文件职责和后续扩展通知源/LLM/报告能力的边界更清晰。

**Architecture:** `src` 不再作为 Python 包名出现，源码顶层包统一为 `notice_push`，入口统一为 `python -m notice_push`。先做低风险包路径迁移并保持测试绿，再按领域拆分 `__main__.py`、`pipeline.py`、`storage.py`、`summarizer.py`、`config.py`、`html_utils.py`、`models.py`。拆分过程中保留少量 re-export facade，让每批迁移可独立验证，最后再清理旧路径和文档引用。

**Tech Stack:** Python 3.12, pytest, sqlite3, requests, BeautifulSoup, PyYAML, GitHub Actions, conda environment `spider`.

---

## Current Findings

当前结构问题不是 `src/notice_push` 目录本身，而是项目把 `src` 当成了 Python 包名：

```text
python -m src.notice_push
from src.notice_push.pipeline import NoticePipeline
adapter: src.notice_push.sources.shu_official.ShuOfficialAdapter
```

目标结构应改为：

```text
notice_push/
  __main__.py
  cli.py
  app_factory.py
  settings/
  domain/
  crawler/
  storage/
  llm/
  reporting/
  observability/
  sources/
tests/
```

目标运行方式：

```powershell
conda run --no-capture-output -n spider python -m notice_push --doctor
conda run --no-capture-output -n spider python -m notice_push --profile daily
```

当前超过或接近需要拆分阈值的文件：

```text
src/notice_push/pipeline.py       535 lines
src/notice_push/storage.py        497 lines
src/notice_push/summarizer.py     335 lines
src/notice_push/config.py         321 lines
src/notice_push/html_utils.py     296 lines
src/notice_push/models.py         236 lines
src/notice_push/__main__.py       206 lines
```

## Refactor Rules

- Do not commit or push unless the user explicitly asks.
- Do not edit or stage `resources/notice_records.csv`.
- Keep `resources/notice_state.sqlite3` only if an executed migration actually changes it; otherwise leave it untouched.
- Use `apply_patch` for manual edits.
- Run focused tests after each batch and full verification at the end.
- Prefer temporary compatibility facades during migration, then remove old package paths in the final cleanup batch.
- Do not keep long-term compatibility for `src.notice_push`; this project no longer needs the old entrypoint.

## Target File Structure

Create:

```text
notice_push/
  __init__.py
  __main__.py
  cli.py
  app_factory.py
  settings/
    __init__.py
    defaults.py
    loader.py
    profiles.py
  domain/
    __init__.py
    audit.py
    config.py
    notices.py
    results.py
    runtime.py
  crawler/
    __init__.py
    detail_fetcher.py
    list_scanner.py
    refresh_seen.py
    failures.py
  storage/
    __init__.py
    database.py
    health.py
    migrations.py
    notices.py
    serialization.py
  llm/
    __init__.py
    chat.py
    providers.py
    prompts.py
    repair.py
    router.py
    text.py
    kimi.py
  reporting/
    __init__.py
    markdown.py
    resources.py
  observability/
    __init__.py
    doctor.py
    run_summary.py
    source_audit.py
  parsing/
    __init__.py
    detail.py
    html.py
    media.py
  sources/
    __init__.py
    base.py
    graduate_school.py
    management_school.py
    shu_official.py
```

Remove after migration:

```text
src/
```

Keep tests under `tests/notice_push/` because that is the test namespace, not an import namespace.

---

## Batch 1: Move Package Root From `src.notice_push` To `notice_push`

### Task 1.1: Move Package Directory

**Files:**
- Move: `src/notice_push/` -> `notice_push/`
- Delete: `src/__init__.py`
- Delete if empty: `src/`

- [ ] **Step 1: Move files**

Use `git mv` so history is preserved:

```powershell
git mv src/notice_push notice_push
git rm src/__init__.py
```

If `src/` becomes empty except `__pycache__`, remove generated cache directories with PowerShell:

```powershell
Get-ChildItem -LiteralPath src -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
if ((Get-ChildItem -LiteralPath src -Force | Measure-Object).Count -eq 0) { Remove-Item -LiteralPath src -Force }
```

Expected: `notice_push/__main__.py` exists and `src/notice_push` no longer exists.

### Task 1.2: Rewrite Imports And Adapter Paths

**Files:**
- Modify: `notice_push/**/*.py`
- Modify: `tests/**/*.py`
- Modify: `resources/config/runtime.yml`
- Modify: `.github/workflows/daily_report.yml`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/add-source-guide.md`

- [ ] **Step 1: Replace package imports**

Replace all Python import paths:

```text
src.notice_push -> notice_push
```

Use a mechanical replace in `.py`, `.yml`, `.yaml`, `.md` files only. Do not edit SQLite, CSV, HTML outputs, or generated caches.

- [ ] **Step 2: Update runtime adapter paths**

`resources/config/runtime.yml` should become:

```yaml
sources:
  shu_official:
    adapter: notice_push.sources.shu_official.ShuOfficialAdapter
  management_school:
    adapter: notice_push.sources.management_school.ManagementSchoolAdapter
  graduate_school:
    adapter: notice_push.sources.graduate_school.GraduateSchoolAdapter
```

- [ ] **Step 3: Update workflow commands**

`.github/workflows/daily_report.yml`:

```yaml
output=$(python -m notice_push --profile daily --date "${{ steps.date.outputs.date }}" 2>&1)
```

`.github/workflows/ci.yml`:

```yaml
- run: python -m notice_push --doctor
```

- [ ] **Step 4: Update README commands**

Replace every command:

```text
python -m src.notice_push
```

with:

```text
python -m notice_push
```

- [ ] **Step 5: Verify old import path is gone**

Run:

```powershell
rg -n "src\.notice_push|python -m src\.notice_push|src/notice_push|src\\notice_push" . --glob '!resources/notice_state.sqlite3' --glob '!resources/notice_records.csv'
```

Expected: only historical plan/review documents may still mention old paths. Runtime files, tests, README, workflows, and `runtime.yml` must not mention old paths.

### Task 1.3: Verify Package Migration

**Files:**
- Test: `tests/notice_push/test_cli.py`
- Test: `tests/notice_push/test_config_models.py`
- Test: `tests/notice_push/test_sources.py`

- [ ] **Step 1: Run focused tests**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_cli.py tests/notice_push/test_config_models.py tests/notice_push/test_sources.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run entrypoint smoke**

Run:

```powershell
conda run --no-capture-output -n spider python -m notice_push --doctor
```

Expected: exit code 0 in normal checkout. Missing API keys may print `doctor_warning=...`, not `doctor_error=...`.

---

## Batch 2: Split CLI And Application Factory

### Task 2.1: Make `__main__.py` A Thin Entrypoint

**Files:**
- Create: `notice_push/cli.py`
- Create: `notice_push/app_factory.py`
- Modify: `notice_push/__main__.py`
- Test: `tests/notice_push/test_cli.py`

- [ ] **Step 1: Move parser and command flow to `cli.py`**

Move these functions from `notice_push/__main__.py` to `notice_push/cli.py`:

```python
build_parser
run_options_from_args
select_sources
audit_counts
print_audit_counts
main
```

`notice_push/cli.py` imports runtime construction from `notice_push.app_factory`.

- [ ] **Step 2: Move object wiring to `app_factory.py`**

Move these functions from `notice_push/__main__.py` to `notice_push/app_factory.py`:

```python
build_detail_parser
build_http_client
build_pipeline
run_source_audit
```

`notice_push/app_factory.py` should import:

```python
from notice_push.settings.loader import load_config
from notice_push.parsing.detail import DetailParser
from notice_push.parsing.html import ParsingRules
from notice_push.http import HttpClient
from notice_push.llm import resolve_optional_provider
from notice_push.pipeline import NoticePipeline, create_adapter
from notice_push.source_audit import SourceAuditor
from notice_push.storage import NoticeStorage
from notice_push.summarizer import KimiMultimodalSummarizer, NoticeSummarizer, SummarizerRouter
```

- [ ] **Step 3: Reduce `__main__.py`**

`notice_push/__main__.py` should contain only:

```python
from __future__ import annotations

from notice_push.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Update tests**

In `tests/notice_push/test_cli.py`, update monkeypatch targets:

```text
notice_push.__main__.build_pipeline -> notice_push.cli.build_pipeline
notice_push.__main__.run_source_audit -> notice_push.cli.run_source_audit
notice_push.__main__.load_config -> notice_push.cli.load_config
```

Also import:

```python
from notice_push.app_factory import build_pipeline
from notice_push.cli import main
```

- [ ] **Step 5: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_cli.py -q
conda run --no-capture-output -n spider python -m notice_push --doctor
```

Expected: tests pass; doctor exits 0.

---

## Batch 3: Split Configuration Loading

### Task 3.1: Move Runtime Config Into `settings/`

**Files:**
- Create: `notice_push/settings/__init__.py`
- Create: `notice_push/settings/defaults.py`
- Create: `notice_push/settings/profiles.py`
- Create: `notice_push/settings/loader.py`
- Modify: `notice_push/config.py`
- Test: `tests/notice_push/test_config_models.py`

- [ ] **Step 1: Move constants to `settings/defaults.py`**

Move these constants out of `notice_push/config.py`:

```python
PROFILE_DEFAULTS
OPTIONAL_INT_PROFILE_KEYS
INT_PROFILE_KEYS
FLOAT_PROFILE_KEYS
BOOL_PROFILE_KEYS
DEFAULT_LLM_PROVIDERS
DEFAULT_LLM_ROUTING
DEFAULT_PARSING
DEFAULT_MEDIA_POLICY
DEFAULT_AUDIT_POLICY
```

- [ ] **Step 2: Move profile parsing to `settings/profiles.py`**

Move these functions:

```python
_runtime_profiles
_runtime_profile
_profile_value
_int_value
_optional_int_value
_float_value
_bool_value
```

Expose:

```python
def runtime_profiles(yaml_config: Mapping[str, Any]) -> dict[str, NoticeRuntimeProfile]:
    ...
```

- [ ] **Step 3: Move YAML loading and AppConfig assembly to `settings/loader.py`**

Move:

```python
_repo_root
_load_yaml_config
_yaml_value
_source_enabled
_built_in_source_defaults
_source_value
_default_sources
_llm_providers
_llm_routing
_parsing_config
_media_policy
_audit_policy
_string_tuple
load_config
```

- [ ] **Step 4: Keep `notice_push/config.py` as facade**

For this batch, keep:

```python
from notice_push.settings.loader import load_config
from notice_push.domain.config import AppConfig

__all__ = ["AppConfig", "load_config"]
```

This prevents one large import rewrite in the same batch.

- [ ] **Step 5: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_config_models.py tests/notice_push/test_cli.py -q
```

Expected: all tests pass.

---

## Batch 4: Split Domain Models

### Task 4.1: Split `models.py` By Domain

**Files:**
- Create: `notice_push/domain/__init__.py`
- Create: `notice_push/domain/notices.py`
- Create: `notice_push/domain/audit.py`
- Create: `notice_push/domain/results.py`
- Create: `notice_push/domain/runtime.py`
- Create: `notice_push/domain/config.py`
- Modify: `notice_push/models.py`
- Test: `tests/notice_push/test_config_models.py`
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Move notice entities to `domain/notices.py`**

Move:

```python
NoticeSource
Attachment
NoticeAsset
NoticeListItem
NoticeDetail
NoticeSummary
FailedNotice
SourceError
```

- [ ] **Step 2: Move audit entities to `domain/audit.py`**

Move:

```python
SourceAuditIssue
SourceAuditSample
SourceAuditResult
AuditPolicy
```

- [ ] **Step 3: Move result entities to `domain/results.py`**

Move:

```python
RefreshSeenError
PipelineSourceStats
StorageHealth
PipelineResult
PipelineCounters
ReportStats
```

- [ ] **Step 4: Move runtime entities to `domain/runtime.py`**

Move:

```python
PipelineRunOptions
NoticeRuntimeProfile
LLMProviderConfig
ParsingConfig
MediaPolicy
```

- [ ] **Step 5: Move `AppConfig` to `domain/config.py`**

Move:

```python
AppConfig
```

`AppConfig` imports `NoticeSource`, `LLMProviderConfig`, `ParsingConfig`, `MediaPolicy`, `AuditPolicy`, and `NoticeRuntimeProfile` from domain modules.

- [ ] **Step 6: Keep `models.py` as temporary re-export facade**

`notice_push/models.py` should only contain:

```python
from notice_push.domain.audit import AuditPolicy, SourceAuditIssue, SourceAuditResult, SourceAuditSample
from notice_push.domain.config import AppConfig
from notice_push.domain.notices import (
    Attachment,
    FailedNotice,
    NoticeAsset,
    NoticeDetail,
    NoticeListItem,
    NoticeSource,
    NoticeSummary,
    SourceError,
)
from notice_push.domain.results import (
    PipelineCounters,
    PipelineResult,
    PipelineSourceStats,
    RefreshSeenError,
    ReportStats,
    StorageHealth,
)
from notice_push.domain.runtime import (
    LLMProviderConfig,
    MediaPolicy,
    NoticeRuntimeProfile,
    ParsingConfig,
    PipelineRunOptions,
)
```

- [ ] **Step 7: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_config_models.py tests/notice_push/test_pipeline.py -q
```

Expected: all tests pass.

---

## Batch 5: Split Pipeline Into Crawler Components

### Task 5.1: Extract Detail Fetching And Failure Classification

**Files:**
- Create: `notice_push/crawler/__init__.py`
- Create: `notice_push/crawler/failures.py`
- Create: `notice_push/crawler/detail_fetcher.py`
- Modify: `notice_push/pipeline.py`
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Move failure policy and classifier**

Move from `pipeline.py` to `crawler/failures.py`:

```python
@dataclass(frozen=True)
class FailureRetryPolicy:
    limit: int = 0
    after_hours: int = 0


class UnsupportedContentError(ValueError):
    pass


def classify_failure(exc: Exception, *, stage: str = "") -> str:
    ...
```

Update callers to use:

```python
from notice_push.crawler.failures import FailureRetryPolicy, UnsupportedContentError, classify_failure
```

- [ ] **Step 2: Move prepared/detail result models**

Move from `pipeline.py` to `crawler/detail_fetcher.py`:

```python
@dataclass(frozen=True)
class PreparedNotice:
    source: NoticeSource
    notice_id: int
    detail: NoticeDetail


@dataclass(frozen=True)
class DetailFetchResult:
    prepared: Optional[PreparedNotice] = None
    failure: Optional[FailedNotice] = None
```

- [ ] **Step 3: Move `is_summarizable_detail`**

Move:

```python
SUPPORTED_ASSET_KINDS = {"pdf", "image"}
SUPPORTED_ASSET_ROLES = {"primary", "attachment"}

def is_summarizable_detail(detail: NoticeDetail, min_chars: int) -> bool:
    ...
```

Keep a temporary re-export in `pipeline.py`:

```python
from notice_push.crawler.detail_fetcher import is_summarizable_detail
```

This preserves existing tests that import it from `pipeline.py`.

- [ ] **Step 4: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py -q
```

Expected: all tests pass.

### Task 5.2: Extract List Scanning And Refresh-Seen Logic

**Files:**
- Create: `notice_push/crawler/list_scanner.py`
- Create: `notice_push/crawler/refresh_seen.py`
- Modify: `notice_push/pipeline.py`
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Move pagination helpers**

Move from `pipeline.py` to `crawler/list_scanner.py`:

```python
UNBOUNDED_PAGE_SCAN = float("inf")

def cutoff_datetime(report_day: date, lookback_days: Optional[int]) -> Optional[datetime]:
    ...

def items_within_lookback(items: list[NoticeListItem], cutoff: Optional[datetime]) -> list[NoticeListItem]:
    ...

def item_key(item: NoticeListItem) -> tuple[str, str]:
    ...

def page_is_before_cutoff(items: list[NoticeListItem], cutoff: Optional[datetime]) -> bool:
    ...
```

Update `pipeline.py` imports and call sites:

```text
_cutoff_datetime -> cutoff_datetime
_items_within_lookback -> items_within_lookback
_item_key -> item_key
_page_is_before_cutoff -> page_is_before_cutoff
```

- [ ] **Step 2: Move refresh seen updater**

Move `_update_seen_details_if_changed()` from `NoticePipeline` to `crawler/refresh_seen.py` as:

```python
def update_seen_details_if_changed(
    *,
    source: NoticeSource,
    adapter,
    items: list[NoticeListItem],
    seen_rows: dict[str, object],
    http_client,
    storage,
    detail_min_chars: int,
    max_workers: Optional[int] = None,
) -> list[RefreshSeenError]:
    ...
```

Update `pipeline.py` to call this function.

- [ ] **Step 3: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py -q
```

Expected: all tests pass.

### Task 5.3: Extract Pipeline Stats

**Files:**
- Create: `notice_push/crawler/stats.py`
- Modify: `notice_push/pipeline.py`
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Move result stats helpers**

Move from `pipeline.py` to `crawler/stats.py`:

```python
def source_stats(...)
def models_used(entries: list[ReportEntry]) -> tuple[str, ...]
def media_counts(entries: list[ReportEntry]) -> dict[str, int]
def utc_now() -> str
```

Update call sites:

```text
_source_stats -> source_stats
_models_used -> models_used
_media_counts -> media_counts
_utc_now -> utc_now
```

- [ ] **Step 2: Verify target size**

Run:

```powershell
(Get-Content -LiteralPath notice_push/pipeline.py | Measure-Object -Line).Lines
```

Expected: `pipeline.py` is below 350 lines.

- [ ] **Step 3: Verify tests**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py -q
```

Expected: all tests pass.

---

## Batch 6: Split Storage

### Task 6.1: Move Schema, Serialization, And Health Helpers

**Files:**
- Create: `notice_push/storage/__init__.py`
- Create: `notice_push/storage/schema.py`
- Create: `notice_push/storage/serialization.py`
- Create: `notice_push/storage/health.py`
- Move: `notice_push/storage.py` -> `notice_push/storage/database.py`
- Move: `notice_push/storage_migrations.py` -> `notice_push/storage/migrations.py`
- Modify: `notice_push/storage/__init__.py`
- Test: `tests/notice_push/test_storage.py`

- [ ] **Step 1: Convert `storage.py` file into `storage/` package safely**

Because a file named `notice_push/storage.py` cannot coexist with a directory named `notice_push/storage/`, move the file to a temporary name first:

```powershell
git mv notice_push/storage.py notice_push/storage_database.py
New-Item -ItemType Directory -Force -Path notice_push/storage | Out-Null
git mv notice_push/storage_database.py notice_push/storage/database.py
```

Create `notice_push/storage/__init__.py`:

```python
from notice_push.storage.database import NoticeStorage

__all__ = ["NoticeStorage"]
```

Existing imports like `from notice_push.storage import NoticeStorage` continue to work.

- [ ] **Step 2: Move migrations**

Move:

```powershell
git mv notice_push/storage_migrations.py notice_push/storage/migrations.py
```

Update imports:

```text
notice_push.storage_migrations -> notice_push.storage.migrations
```

- [ ] **Step 3: Move serialization helpers**

Move from `storage/database.py` to `storage/serialization.py`:

```python
def assets_json(detail: NoticeDetail) -> str:
    ...

def attachments_json(detail: NoticeDetail) -> str:
    ...

def content_hash(detail: NoticeDetail) -> str:
    ...
```

Update call sites:

```text
_assets_json -> assets_json
_attachments_json -> attachments_json
_content_hash -> content_hash
```

- [ ] **Step 4: Move table helpers and health**

Move from `storage/database.py` to `storage/health.py`:

```python
def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    ...

def table_count(conn: sqlite3.Connection, table_name: str) -> int:
    ...

def storage_health(conn: sqlite3.Connection) -> tuple[int, int, tuple[str, ...]]:
    ...
```

`NoticeStorage.health_check()` should call `storage_health(conn)`.

- [ ] **Step 5: Move schema setup**

Move table creation SQL and `_ensure_notice_columns()` to `storage/schema.py`:

```python
def initialize_schema(conn: sqlite3.Connection, now: str) -> None:
    ...

def ensure_notice_columns(conn: sqlite3.Connection) -> None:
    ...
```

`NoticeStorage.initialize()` should call `initialize_schema(conn, now)`.

- [ ] **Step 6: Keep `NoticeStorage` public import stable**

For this batch, `notice_push/storage/__init__.py` re-exports `NoticeStorage`. Do not rename the class.

- [ ] **Step 7: Verify target size**

Run:

```powershell
(Get-Content -LiteralPath notice_push/storage/database.py | Measure-Object -Line).Lines
```

Expected: `storage/database.py` is below 320 lines.

- [ ] **Step 8: Verify tests**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_storage.py tests/notice_push/test_pipeline.py -q
```

Expected: all tests pass.

---

## Batch 7: Split LLM Summarizers

### Task 7.1: Extract Prompt, Repair, Text, Kimi, And Router Modules

**Files:**
- Create: `notice_push/llm/__init__.py`
- Move: `notice_push/llm.py` -> `notice_push/llm/providers.py`
- Move: `notice_push/llm_chat.py` -> `notice_push/llm/chat.py`
- Create: `notice_push/llm/prompts.py`
- Create: `notice_push/llm/repair.py`
- Create: `notice_push/llm/text.py`
- Create: `notice_push/llm/kimi.py`
- Create: `notice_push/llm/router.py`
- Modify: `notice_push/summarizer.py`
- Modify: `notice_push/app_factory.py`
- Test: `tests/notice_push/test_summarizer.py`
- Test: `tests/notice_push/test_cli.py`

- [ ] **Step 1: Convert `llm.py` file into `llm/` package safely**

Because a file named `notice_push/llm.py` cannot coexist with a directory named `notice_push/llm/`, move the file to a temporary name first:

```powershell
git mv notice_push/llm.py notice_push/llm_providers.py
New-Item -ItemType Directory -Force -Path notice_push/llm | Out-Null
git mv notice_push/llm_providers.py notice_push/llm/providers.py
git mv notice_push/llm_chat.py notice_push/llm/chat.py
```

Create `notice_push/llm/__init__.py`:

```python
from notice_push.llm.providers import ProviderRuntime, resolve_optional_provider, resolve_provider

__all__ = ["ProviderRuntime", "resolve_optional_provider", "resolve_provider"]
```

Update imports:

```text
notice_push.llm import resolve_optional_provider -> notice_push.llm.providers import resolve_optional_provider
notice_push.llm_chat import create_chat_completion_with_retry -> notice_push.llm.chat import create_chat_completion_with_retry
```

- [ ] **Step 2: Move prompt functions**

Move from `summarizer.py` to `llm/prompts.py`:

```python
load_prompt
render_notice_user_prompt
```

- [ ] **Step 3: Move repair function**

Move from `summarizer.py` to `llm/repair.py`:

```python
render_summary_repair_prompt
```

Use a public name without leading underscore.

- [ ] **Step 4: Move text summarizer**

Move `NoticeSummarizer` to `llm/text.py`.

- [ ] **Step 5: Move Kimi summarizer**

Move `KimiMultimodalSummarizer` to `llm/kimi.py`.

- [ ] **Step 6: Move router**

Move `SummarizerRouter` to `llm/router.py`.

- [ ] **Step 7: Keep `summarizer.py` as temporary facade**

`notice_push/summarizer.py` should only re-export:

```python
from notice_push.llm.kimi import KimiMultimodalSummarizer
from notice_push.llm.prompts import load_prompt, render_notice_user_prompt
from notice_push.llm.router import SummarizerRouter
from notice_push.llm.text import NoticeSummarizer
```

- [ ] **Step 8: Verify target size**

Run:

```powershell
(Get-Content -LiteralPath notice_push/summarizer.py | Measure-Object -Line).Lines
```

Expected: `summarizer.py` is below 40 lines.

- [ ] **Step 9: Verify tests**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_summarizer.py tests/notice_push/test_cli.py -q
```

Expected: all tests pass.

---

## Batch 8: Split Parsing And Reporting Helpers

### Task 8.1: Move HTML/Detail/Media Parsing

**Files:**
- Create: `notice_push/parsing/__init__.py`
- Move: `notice_push/html_utils.py` -> `notice_push/parsing/html.py`
- Move: `notice_push/detail_parser.py` -> `notice_push/parsing/detail.py`
- Move: `notice_push/media.py` -> `notice_push/parsing/media.py`
- Modify: `notice_push/html_utils.py`
- Modify: `notice_push/detail_parser.py`
- Modify: `notice_push/media.py`
- Test: `tests/notice_push/test_html_utils.py`
- Test: `tests/notice_push/test_media.py`
- Test: `tests/notice_push/test_sources.py`

- [ ] **Step 1: Move modules**

Run:

```powershell
git mv notice_push/html_utils.py notice_push/parsing/html.py
git mv notice_push/detail_parser.py notice_push/parsing/detail.py
git mv notice_push/media.py notice_push/parsing/media.py
```

- [ ] **Step 2: Create temporary facades**

Create `notice_push/html_utils.py`:

```python
from notice_push.parsing.html import *  # noqa: F403
```

Create `notice_push/detail_parser.py`:

```python
from notice_push.parsing.detail import *  # noqa: F403
```

Create `notice_push/media.py`:

```python
from notice_push.parsing.media import *  # noqa: F403
```

- [ ] **Step 3: Update first-party imports**

Update production code to import from `notice_push.parsing.*`. Tests can keep old imports until final cleanup, or be updated in the same batch if small.

- [ ] **Step 4: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_html_utils.py tests/notice_push/test_media.py tests/notice_push/test_sources.py -q
```

Expected: all tests pass.

### Task 8.2: Move Reporting Modules

**Files:**
- Create: `notice_push/reporting/__init__.py`
- Move: `notice_push/report.py` -> `notice_push/reporting/markdown.py`
- Move: `notice_push/resources.py` -> `notice_push/reporting/resources.py`
- Modify: `notice_push/report.py`
- Modify: `notice_push/resources.py`
- Test: `tests/notice_push/test_report.py`
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Move modules**

Run:

```powershell
git mv notice_push/report.py notice_push/reporting/markdown.py
git mv notice_push/resources.py notice_push/reporting/resources.py
```

- [ ] **Step 2: Create temporary facades**

Create `notice_push/report.py`:

```python
from notice_push.reporting.markdown import *  # noqa: F403
```

Create `notice_push/resources.py`:

```python
from notice_push.reporting.resources import *  # noqa: F403
```

- [ ] **Step 3: Update first-party imports**

Update production code:

```text
notice_push.report -> notice_push.reporting.markdown
notice_push.resources -> notice_push.reporting.resources
```

- [ ] **Step 4: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_report.py tests/notice_push/test_pipeline.py -q
```

Expected: all tests pass.

---

## Batch 9: Move Observability Modules

### Task 9.1: Move Doctor, Run Summary, And Source Audit

**Files:**
- Create: `notice_push/observability/__init__.py`
- Move: `notice_push/doctor.py` -> `notice_push/observability/doctor.py`
- Move: `notice_push/run_summary.py` -> `notice_push/observability/run_summary.py`
- Move: `notice_push/source_audit.py` -> `notice_push/observability/source_audit.py`
- Modify: `notice_push/doctor.py`
- Modify: `notice_push/run_summary.py`
- Modify: `notice_push/source_audit.py`
- Modify: `notice_push/cli.py`
- Modify: `notice_push/pipeline.py`
- Test: `tests/notice_push/test_cli.py`
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Move modules**

Run:

```powershell
git mv notice_push/doctor.py notice_push/observability/doctor.py
git mv notice_push/run_summary.py notice_push/observability/run_summary.py
git mv notice_push/source_audit.py notice_push/observability/source_audit.py
```

- [ ] **Step 2: Create temporary facades**

Create:

```python
# notice_push/doctor.py
from notice_push.observability.doctor import *  # noqa: F403

# notice_push/run_summary.py
from notice_push.observability.run_summary import *  # noqa: F403

# notice_push/source_audit.py
from notice_push.observability.source_audit import *  # noqa: F403
```

- [ ] **Step 3: Update first-party imports**

Update production imports to `notice_push.observability.*`.

- [ ] **Step 4: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_cli.py tests/notice_push/test_pipeline.py -q
```

Expected: all tests pass.

---

## Batch 10: Final Cleanup Of Facades And Documentation

### Task 10.1: Remove Temporary Facades Where Imports Are Fully Migrated

**Files:**
- Delete if unused: `notice_push/models.py`
- Delete if unused: `notice_push/config.py`
- Delete if unused: `notice_push/summarizer.py`
- Delete if unused: `notice_push/html_utils.py`
- Delete if unused: `notice_push/detail_parser.py`
- Delete if unused: `notice_push/media.py`
- Delete if unused: `notice_push/report.py`
- Delete if unused: `notice_push/resources.py`
- Delete if unused: `notice_push/doctor.py`
- Delete if unused: `notice_push/run_summary.py`
- Delete if unused: `notice_push/source_audit.py`
- Test: full suite

- [ ] **Step 1: Find facade imports**

Run:

```powershell
rg -n "notice_push\.(models|config|summarizer|html_utils|detail_parser|media|report|resources|doctor|run_summary|source_audit)" notice_push tests scripts
```

Expected: only intentional public imports remain. If tests import old facades, update tests to the new module path.

- [ ] **Step 2: Delete unused facades**

Only delete a facade when `rg` proves it has no imports.

- [ ] **Step 3: Verify old `src` path is absent from runtime files**

Run:

```powershell
rg -n "src\.notice_push|python -m src\.notice_push|src/notice_push|src\\notice_push" README.md .github resources tests notice_push scripts
```

Expected: no matches.

### Task 10.2: Update Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/add-source-guide.md`
- Modify if useful: `PYTHON_FILES_SUMMARY.md`
- Modify if useful: `PROJECT_DOCUMENTATION.md`

- [ ] **Step 1: Update README structure**

README project structure should show:

```text
notice_push/
  cli.py              CLI 参数解析和命令分发
  app_factory.py      HTTP、Storage、LLM、Pipeline 装配
  settings/           YAML 配置加载和 profile 默认值
  domain/             Notice、Result、Runtime dataclass
  crawler/            目录扫描、详情抓取、失败分类、已见通知刷新
  storage/            SQLite schema、序列化、健康检查
  llm/                DeepSeek/Kimi 摘要、路由、提示词修复
  parsing/            HTML 正文、附件、PDF/image/video 解析
  reporting/          Markdown 日报和资源链接
  observability/      doctor、source audit、run summary
  sources/            三个通知源 Adapter
```

- [ ] **Step 2: Update add-source guide**

Adapter example should import:

```python
from notice_push.domain.notices import NoticeDetail, NoticeListItem
from notice_push.parsing.html import clean_text
from notice_push.sources.base import NoticeSourceAdapter
```

Runtime adapter path example:

```yaml
adapter: notice_push.sources.new_source.NewSourceAdapter
```

### Task 10.3: Final Verification

**Files:**
- Test: all

- [ ] **Step 1: Run full tests**

Run:

```powershell
conda run --no-capture-output -n spider pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run compile check**

Run:

```powershell
conda run --no-capture-output -n spider python -m compileall -q notice_push
```

Expected: exit code 0.

- [ ] **Step 3: Validate workflow YAML**

Run:

```powershell
conda run --no-capture-output -n spider python -c "import yaml; [yaml.safe_load(open(path, encoding='utf-8')) for path in ['.github/workflows/ci.yml', '.github/workflows/daily_report.yml']]"
```

Expected: exit code 0.

- [ ] **Step 4: Run doctor**

Run:

```powershell
conda run --no-capture-output -n spider python -m notice_push --doctor
```

Expected: exit code 0 in normal checkout.

- [ ] **Step 5: Run package path smoke**

Run:

```powershell
conda run --no-capture-output -n spider python -c "import notice_push; from notice_push.cli import main; from notice_push.pipeline import NoticePipeline; print('ok')"
```

Expected output:

```text
ok
```

- [ ] **Step 6: Ensure old package path fails**

Run:

```powershell
conda run --no-capture-output -n spider python -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('src.notice_push') is None else 1)"
```

Expected: exit code 0.

- [ ] **Step 7: Check git status**

Run:

```powershell
git status --short
```

Expected: refactor files are visible. `resources/notice_records.csv` must not be staged or intentionally modified by this refactor.

---

## Success Criteria

- Runtime command is `python -m notice_push`; `python -m src.notice_push` is no longer used or supported.
- `resources/config/runtime.yml` adapter paths use `notice_push.sources...`.
- No production code imports from `src.notice_push`.
- No production `.py` file remains over 350 lines unless there is a clear reason documented in the file.
- `pipeline.py`, `storage.py`, and `summarizer.py` are split into smaller modules with focused responsibilities.
- Full test suite, compile check, workflow YAML parse, and doctor all pass in conda env `spider`.

## Suggested Execution Order

1. Execute Batch 1 first and stop if package migration breaks CLI or adapter imports.
2. Execute Batches 2-4 next because they reduce import and dataclass coupling.
3. Execute Batches 5-9 in any order only after Batch 4 is green, but prefer pipeline -> storage -> LLM -> parsing/reporting -> observability.
4. Execute Batch 10 last to remove temporary facades and update docs.

## Risk Notes

- This refactor touches nearly every import path. Keep changes mechanical inside each batch.
- Do not combine package root migration and deep file splitting in one commit if commits are later requested.
- GitHub Actions must be updated in the same batch as package root migration; otherwise CI will call the old entrypoint.
- Runtime adapter import strings are data, not Python imports, so `rg` checks must include YAML.
- `notice_push/storage.py` and `notice_push/storage/` cannot coexist; Batch 6 uses the explicit temporary name `notice_push/storage_database.py` before creating the package directory.
- `notice_push/llm.py` and `notice_push/llm/` cannot coexist; Batch 7 uses the explicit temporary name `notice_push/llm_providers.py` before creating the package directory.
