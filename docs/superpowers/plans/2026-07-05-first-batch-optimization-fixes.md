# First Batch Optimization Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the first batch of production-readiness issues from `docs/superpowers/reviews/2026-07-05-project-optimization-review.md`.

**Architecture:** Keep the current `src.notice_push` layering intact. Make LLM credentials lazy at real API call time, expose media assets through one user-visible resource path, persist media metadata in SQLite, stabilize pytest temp handling, and prevent media download temp-file leaks.

**Tech Stack:** Python 3.12, pytest, sqlite3, dataclasses, OpenAI-compatible SDK, conda environment `spider`.

---

## Scope

This plan implements only the first batch:

- DeepSeek provider lazy startup.
- User-visible PDF/image asset links in prompts and reports.
- SQLite persistence for `content_kind`, `assets`, and `attachments`.
- Stable pytest basetemp under `.tmp`.
- Safe media temp-file creation.

This plan does not implement:

- SQLite write serialization / WAL.
- `new_count` and `retried_count` split.
- mixed text/video classification changes.
- old `src/spider` cleanup.
- model config compatibility cleanup.

Do not modify or stage `resources/notice_records.csv`.

## File Structure

- Modify `src/notice_push/__main__.py`: use optional provider resolution for DeepSeek as well as Kimi.
- Modify `src/notice_push/summarizer.py`: add a shared visible-resource helper and use it in prompt rendering.
- Modify `src/notice_push/report.py`: render visible resources from both `attachments` and `assets`.
- Modify `src/notice_push/storage.py`: add media metadata columns, JSON serialization, and content hash updates.
- Modify `src/notice_push/media.py`: avoid creating temp files before successful downloads.
- Modify `pytest.ini`: move basetemp to `.tmp/pytest`.
- Update tests in `tests/notice_push/test_cli.py`, `tests/notice_push/test_summarizer.py`, `tests/notice_push/test_report.py`, `tests/notice_push/test_storage.py`, and add `tests/notice_push/test_media.py` if clearer than extending summarizer tests.

## Task 1: Make DeepSeek Provider Optional At Startup

**Files:**
- Modify: `src/notice_push/__main__.py`
- Test: `tests/notice_push/test_cli.py`

- [ ] **Step 1: Add failing CLI construction test**

Add this test to `tests/notice_push/test_cli.py` after the existing Kimi optional provider test:

```python
def test_build_pipeline_allows_missing_deepseek_key_until_text_summary_is_needed(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-unit")
    monkeypatch.setenv("KIMI_MODEL", "kimi-unit")
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )

    pipeline = build_pipeline(config, config.runtime_profile("daily"))

    assert isinstance(pipeline.summarizer, SummarizerRouter)
    text_summarizer = pipeline.summarizer.provider_summarizers["deepseek"]
    assert isinstance(text_summarizer, NoticeSummarizer)
    assert text_summarizer.model == "deepseek-unit"
    assert text_summarizer.api_key == ""
    assert text_summarizer.base_url == "https://api.deepseek.com"
```

- [ ] **Step 2: Verify the new test fails**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'; conda run -n spider pytest tests/notice_push/test_cli.py::test_build_pipeline_allows_missing_deepseek_key_until_text_summary_is_needed -q
```

Expected: fail with `ValueError: DEEPSEEK_API_KEY must be provided for provider 'deepseek'`.

- [ ] **Step 3: Implement minimal startup fix**

In `src/notice_push/__main__.py`, change:

```python
deepseek_provider = resolve_provider("deepseek", config.llm_providers["deepseek"])
```

to:

```python
deepseek_provider = resolve_optional_provider("deepseek", config.llm_providers["deepseek"])
```

Remove the unused `resolve_provider` import if it is no longer used.

- [ ] **Step 4: Verify CLI tests pass**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'; conda run -n spider pytest tests/notice_push/test_cli.py -q
```

Expected: all CLI tests pass.

## Task 2: Expose Assets As User-Visible Resources

**Files:**
- Modify: `src/notice_push/summarizer.py`
- Modify: `src/notice_push/report.py`
- Test: `tests/notice_push/test_summarizer.py`
- Test: `tests/notice_push/test_report.py`

- [ ] **Step 1: Add failing summarizer prompt test**

Add this test to `tests/notice_push/test_summarizer.py`:

```python
def test_render_notice_user_prompt_includes_assets_when_attachments_are_empty():
    detail = NoticeDetail(
        source_id="management_school",
        url="https://ms.shu.edu.cn/info/1245/91745.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91745.htm",
        title="巡察公告",
        content="",
        assets=(
            NoticeAsset(
                kind="pdf",
                role="primary",
                name="巡察公告.pdf",
                url="https://ms.shu.edu.cn/__local/inspection.pdf",
                mime_type="application/pdf",
            ),
        ),
        content_kind="pdf",
    )

    prompt = render_notice_user_prompt(detail, source_name="上海大学管理学院")

    assert "- 巡察公告.pdf: https://ms.shu.edu.cn/__local/inspection.pdf" in prompt
```

- [ ] **Step 2: Add failing report test**

Add this test to `tests/notice_push/test_report.py`:

```python
def test_render_report_includes_assets_when_attachments_are_empty():
    detail = NoticeDetail(
        source_id="management_school",
        url="https://ms.shu.edu.cn/info/1245/91475.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91475.htm",
        title="管理学院2026年寒假值班安排",
        content="",
        assets=(
            NoticeAsset(
                kind="image",
                role="primary",
                name="值班安排.png",
                url="https://ms.shu.edu.cn/__local/duty.png",
                mime_type="image/png",
            ),
        ),
        content_kind="image",
    )
    summary = NoticeSummary(
        notice_id=1,
        markdown="## 上海大学管理学院|行政|周常事务|管理学院2026年寒假值班安排",
        model="kimi-k2.7-code",
        prompt_version="notice_summary_v1",
        generated_at=datetime(2026, 7, 5),
    )

    markdown = render_report(
        date(2026, 7, 5),
        [ReportEntry("management_school", "上海大学管理学院", detail, summary)],
        [],
    )

    assert "- **附件**: [值班安排.png](https://ms.shu.edu.cn/__local/duty.png)" in markdown
```

Ensure the test file imports `NoticeAsset`, `NoticeDetail`, `NoticeSummary`, `ReportEntry`, `render_report`, `date`, and `datetime` as needed.

- [ ] **Step 3: Verify new tests fail**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'; conda run -n spider pytest tests/notice_push/test_summarizer.py::test_render_notice_user_prompt_includes_assets_when_attachments_are_empty tests/notice_push/test_report.py::test_render_report_includes_assets_when_attachments_are_empty -q
```

Expected: both tests fail because assets are not rendered as visible resources.

- [ ] **Step 4: Implement shared visible resource helper**

In `src/notice_push/summarizer.py`, add a small helper near `render_notice_user_prompt`:

```python
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

Update `render_notice_user_prompt`:

```python
resources = visible_notice_resources(detail)
attachments = "\n".join(f"- {name}: {url}" for name, url in resources) or "未提及"
```

- [ ] **Step 5: Use the same helper in reports**

In `src/notice_push/report.py`, import the helper:

```python
from src.notice_push.summarizer import visible_notice_resources
```

Replace the attachment rendering block with:

```python
resources = visible_notice_resources(entry.detail)
if resources:
    resource_links = "；".join(f"[{name}]({url})" for name, url in resources)
    lines.append(f"- **附件**: {resource_links}")
```

- [ ] **Step 6: Verify prompt/report tests pass**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'; conda run -n spider pytest tests/notice_push/test_summarizer.py tests/notice_push/test_report.py -q
```

Expected: all summarizer and report tests pass.

## Task 3: Persist Media Metadata In SQLite

**Files:**
- Modify: `src/notice_push/storage.py`
- Test: `tests/notice_push/test_storage.py`

- [ ] **Step 1: Add failing schema migration test**

Add these assertions to the existing schema migration coverage in `tests/notice_push/test_storage.py`, or add this standalone test:

```python
def test_storage_initializes_media_metadata_columns(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    db_path = tmp_path / "state.sqlite3"
    storage = NoticeStorage(db_path, config.sources)

    storage.initialize()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("pragma table_info(notices)").fetchall()}

    assert {"content_kind", "assets_json", "attachments_json"} <= columns
```

- [ ] **Step 2: Add failing detail persistence test**

Add this test:

```python
def test_storage_saves_media_metadata_for_detail(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = NoticeListItem(
        source_id="management_school",
        url="https://ms.shu.edu.cn/info/1245/91745.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91745.htm",
        title="巡察公告",
    )
    notice_id = storage.upsert_seen_item(item)

    storage.save_detail(
        notice_id,
        NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            content="",
            attachments=(Attachment(name="巡察公告.pdf", url="https://ms.shu.edu.cn/__local/inspection.pdf"),),
            assets=(
                NoticeAsset(
                    kind="pdf",
                    role="primary",
                    name="巡察公告.pdf",
                    url="https://ms.shu.edu.cn/__local/inspection.pdf",
                    mime_type="application/pdf",
                ),
            ),
            content_kind="pdf",
        ),
    )

    row = storage.get_notice(notice_id)

    assert row["content_kind"] == "pdf"
    assert '"kind": "pdf"' in row["assets_json"]
    assert '"巡察公告.pdf"' in row["attachments_json"]
```

Ensure imports include `sqlite3`, `Attachment`, `NoticeAsset`, and `NoticeDetail`.

- [ ] **Step 3: Add failing content hash test for asset changes**

Add this test:

```python
def test_storage_content_hash_changes_when_asset_url_changes_even_with_empty_content(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = NoticeListItem(
        source_id="management_school",
        url="https://ms.shu.edu.cn/info/1245/91745.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91745.htm",
        title="巡察公告",
    )
    notice_id = storage.upsert_seen_item(item)

    first_detail = NoticeDetail(
        source_id=item.source_id,
        url=item.url,
        canonical_url=item.canonical_url,
        title=item.title,
        content="",
        assets=(NoticeAsset("pdf", "primary", "巡察公告.pdf", "https://ms.shu.edu.cn/__local/inspection-v1.pdf", "application/pdf"),),
        content_kind="pdf",
    )
    second_detail = NoticeDetail(
        source_id=item.source_id,
        url=item.url,
        canonical_url=item.canonical_url,
        title=item.title,
        content="",
        assets=(NoticeAsset("pdf", "primary", "巡察公告.pdf", "https://ms.shu.edu.cn/__local/inspection-v2.pdf", "application/pdf"),),
        content_kind="pdf",
    )

    storage.save_detail(notice_id, first_detail)
    first_hash = storage.get_notice(notice_id)["content_hash"]
    storage.save_detail(notice_id, second_detail)
    second_hash = storage.get_notice(notice_id)["content_hash"]

    assert first_hash != second_hash
```

- [ ] **Step 4: Verify storage tests fail**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'; conda run -n spider pytest tests/notice_push/test_storage.py -q
```

Expected: fail because the columns and metadata persistence do not exist.

- [ ] **Step 5: Implement JSON serialization and hash helpers**

In `src/notice_push/storage.py`, add imports:

```python
import json
```

Add helpers near `_dt`:

```python
def _attachments_json(detail: NoticeDetail) -> str:
    return json.dumps(
        [{"name": item.name, "url": item.url} for item in detail.attachments],
        ensure_ascii=False,
        sort_keys=True,
    )


def _assets_json(detail: NoticeDetail) -> str:
    return json.dumps(
        [
            {
                "kind": item.kind,
                "role": item.role,
                "name": item.name,
                "url": item.url,
                "mime_type": item.mime_type,
            }
            for item in detail.assets
        ],
        ensure_ascii=False,
        sort_keys=True,
    )


def _content_hash(detail: NoticeDetail) -> str:
    digest = hashlib.sha256()
    digest.update((detail.content or "").encode("utf-8"))
    digest.update((detail.content_kind or "text").encode("utf-8"))
    digest.update(_assets_json(detail).encode("utf-8"))
    digest.update(_attachments_json(detail).encode("utf-8"))
    return digest.hexdigest()
```

- [ ] **Step 6: Add columns and save metadata**

Update the `create table notices` SQL to include:

```sql
content_kind text not null default 'text',
assets_json text not null default '[]',
attachments_json text not null default '[]',
```

Add the same columns to `_ensure_notice_columns()`:

```python
"content_kind": "text not null default 'text'",
"assets_json": "text not null default '[]'",
"attachments_json": "text not null default '[]'",
```

Update `save_detail()` to use:

```python
content_hash = _content_hash(detail)
assets_json = _assets_json(detail)
attachments_json = _attachments_json(detail)
```

and set:

```sql
content_kind = ?,
assets_json = ?,
attachments_json = ?,
```

with corresponding parameters:

```python
detail.content_kind or "text",
assets_json,
attachments_json,
```

Update `update_seen_detail_if_changed()` the same way.

- [ ] **Step 7: Verify storage tests pass**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'; conda run -n spider pytest tests/notice_push/test_storage.py -q
```

Expected: all storage tests pass.

## Task 4: Move pytest basetemp Under `.tmp`

**Files:**
- Modify: `pytest.ini`

- [ ] **Step 1: Update pytest basetemp**

Change `pytest.ini` from:

```ini
[pytest]
pythonpath = .
addopts = --basetemp=.pytest_tmp
```

to:

```ini
[pytest]
pythonpath = .
addopts = --basetemp=.tmp/pytest
```

- [ ] **Step 2: Verify default pytest command**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'; conda run -n spider pytest -q
```

Expected: full test suite passes without passing a manual `--basetemp`.

## Task 5: Avoid Temp File Leaks On Media Download Failure

**Files:**
- Modify: `src/notice_push/media.py`
- Test: `tests/notice_push/test_media.py`

- [ ] **Step 1: Add media tests**

Create `tests/notice_push/test_media.py`:

```python
from pathlib import Path

import pytest

from src.notice_push.media import download_asset_to_temp
from src.notice_push.models import NoticeAsset


class _BytesHttpClient:
    def __init__(self, content: bytes):
        self.content = content

    def get_bytes(self, url: str) -> bytes:
        return self.content


class _FailingHttpClient:
    def get_bytes(self, url: str) -> bytes:
        raise RuntimeError("download failed")


def test_download_asset_to_temp_writes_downloaded_bytes():
    asset = NoticeAsset(
        kind="image",
        role="primary",
        name="duty.png",
        url="https://ms.shu.edu.cn/__local/duty.png",
        mime_type="image/png",
    )

    path = download_asset_to_temp(_BytesHttpClient(b"image-bytes"), asset)

    try:
        assert path.suffix == ".png"
        assert path.read_bytes() == b"image-bytes"
    finally:
        Path(path).unlink(missing_ok=True)


def test_download_asset_to_temp_does_not_create_file_when_download_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    asset = NoticeAsset(
        kind="pdf",
        role="primary",
        name="notice.pdf",
        url="https://ms.shu.edu.cn/__local/notice.pdf",
        mime_type="application/pdf",
    )

    with pytest.raises(RuntimeError, match="download failed"):
        download_asset_to_temp(_FailingHttpClient(), asset)

    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Verify the failing test**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'; conda run -n spider pytest tests/notice_push/test_media.py -q
```

Expected: failure in the download-failure test because the current implementation creates a temp file before `get_bytes()`.

- [ ] **Step 3: Implement safer temp file creation**

Change `src/notice_push/media.py`:

```python
def download_asset_to_temp(http_client: HttpClient, asset: NoticeAsset) -> Path:
    suffix = _suffix_for_asset(asset)
    content = http_client.get_bytes(asset.url)
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    path = Path(handle.name)
    try:
        handle.write(content)
    finally:
        handle.close()
    return path
```

- [ ] **Step 4: Verify media tests pass**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'; conda run -n spider pytest tests/notice_push/test_media.py -q
```

Expected: all media tests pass.

## Final Verification

- [ ] **Run focused tests**

```powershell
$env:PYTHONIOENCODING='utf-8'; conda run -n spider pytest tests/notice_push/test_cli.py tests/notice_push/test_summarizer.py tests/notice_push/test_report.py tests/notice_push/test_storage.py tests/notice_push/test_media.py -q
```

Expected: all selected tests pass.

- [ ] **Run full tests**

```powershell
$env:PYTHONIOENCODING='utf-8'; conda run -n spider pytest -q
```

Expected: full test suite passes.

- [ ] **Run compile check**

```powershell
conda run -n spider python -m compileall -q src
```

Expected: exit code 0.

- [ ] **Check git status**

```powershell
git status --short
```

Expected: implementation files and the plan file are modified/added. `resources/notice_records.csv` may remain locally modified from previous work but must not be staged unless the user explicitly requests it.

## Commit Guidance

After implementation and verification, use one commit for this batch:

```powershell
git add docs/superpowers/plans/2026-07-05-first-batch-optimization-fixes.md pytest.ini src/notice_push/__main__.py src/notice_push/summarizer.py src/notice_push/report.py src/notice_push/storage.py src/notice_push/media.py tests/notice_push/test_cli.py tests/notice_push/test_summarizer.py tests/notice_push/test_report.py tests/notice_push/test_storage.py tests/notice_push/test_media.py
git commit -m "fix: improve first batch notice pipeline resilience"
```

Do not stage `resources/notice_records.csv`.

