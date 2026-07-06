# Production Quality Observability Parsing Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 分批完成 9 项生产运行质量、可观测性和解析鲁棒性改进，让 GitHub Actions 日报运行更不容易互相覆盖、告警口径更可信、源站结构变化更早暴露。

**Architecture:** 先保护状态库和 workflow 并发，再把 audit/source errors/failures 的计数语义拆清楚，然后扩展 run summary 与 doctor，最后增强 source audit、媒体检测、摘要格式修复和 Adapter fallback。所有行为先用单元测试或 fixture smoke 覆盖，再改实现。

**Tech Stack:** Python 3.12, pytest, sqlite3, requests, BeautifulSoup, PyYAML, GitHub Actions, actionlint, conda environment `spider`, Playwright MCP for manual live source inspection.

---

## Browser Recon Notes

2026-07-06 用 Playwright 抽样三个通知源得到的结构事实：

- 上海大学官网 `https://www.shu.edu.cn/tzgg.htm`
  - 当前目录主体 selector：`.ej_main ul li a[href]`
  - 每页约 5 条通知，下一页文本为 `下页`，URL 示例 `https://www.shu.edu.cn/tzgg/123.htm`
  - 详情页主体多为 `.v_news_content`，部分页面也匹配 `#vsb_content .v_news_content`
- 上海大学管理学院 `https://ms.shu.edu.cn/syzl/zytz.htm`
  - 当前目录主体 selector：`table.ArtList a[href]`
  - 每页约 20 条通知，下一页链接 class 为 `Next`
  - 详情页主体多为 `.v_news_content`，页面有大量导航和装饰图片，media 识别必须限制在正文主体
- 上海大学研究生院 `https://gs.shu.edu.cn/xwlb/sy.htm`
  - 当前目录主体 selector：`tr[id^='line_u17_'] a[href]`
  - 每页约 20 条通知，下一页 URL 示例 `https://gs.shu.edu.cn/xwlb/sy/6.htm`
  - 详情页主体多为 `#vsb_content .v_news_content`，存在跨站招生链接和附件 PDF 链接

Important implication: source audit must sample items returned by the Adapter, not generic first visible anchors. Generic anchor scans easily hit navigation links such as `English`, `首页`, `建议意见`.

## Batch Overview

### Batch 1: Production Safety Baseline

Covers review items 1 and 2.

Goal: prevent overlapping runs and ensure SQLite WAL data is durable before Git commit or artifact backup.

Files:
- Modify: `.github/workflows/daily_report.yml`
- Modify: `src/notice_push/storage.py`
- Modify: `src/notice_push/pipeline.py`
- Test: `tests/notice_push/test_storage.py`
- Test: `tests/notice_push/test_pipeline.py`

### Batch 2: Alert Semantics And Counter Correctness

Covers review item 3.

Goal: separate `source_error_count` from `audit_error_count`, avoid double counting, and keep operational alert wording precise.

Files:
- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/pipeline.py`
- Modify: `src/notice_push/__main__.py`
- Modify: `src/notice_push/run_summary.py`
- Modify: `.github/workflows/daily_report.yml`
- Test: `tests/notice_push/test_pipeline.py`
- Test: `tests/notice_push/test_cli.py`

### Batch 3: Observability Upgrade

Covers review items 6 and 7.

Goal: expose refresh-seen failures, source-level stats, failure type distribution, durations, model names, media counts, and git SHA in run summary and alert artifacts.

Files:
- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/pipeline.py`
- Modify: `src/notice_push/run_summary.py`
- Modify: `src/notice_push/__main__.py`
- Modify: `.github/workflows/daily_report.yml`
- Test: `tests/notice_push/test_pipeline.py`
- Test: `tests/notice_push/test_cli.py`

### Batch 4: Source Audit And Parsing Robustness

Covers review items 5, 8, and 9.

Goal: make source audit sample multiple Adapter items, add media magic-byte/response-header validation, and add summary format repair before marking a notice failed.

Files:
- Modify: `src/notice_push/source_audit.py`
- Modify: `src/notice_push/http.py`
- Modify: `src/notice_push/media.py`
- Modify: `src/notice_push/summarizer.py`
- Modify: `src/notice_push/summary_validator.py`
- Modify: `resources/config/runtime.yml`
- Test: `tests/notice_push/test_pipeline.py`
- Test: `tests/notice_push/test_http.py`
- Test: `tests/notice_push/test_media.py`
- Test: `tests/notice_push/test_summarizer.py`

### Batch 5: CI, Doctor, And Final Guardrails

Covers review item 4 and cross-cutting verification.

Goal: make CI catch workflow mistakes and common deployment issues before daily action runs.

Files:
- Modify: `.github/workflows/ci.yml`
- Modify: `src/notice_push/doctor.py`
- Modify: `README.md`
- Test: `tests/notice_push/test_cli.py`

---

## Batch 1: Production Safety Baseline

### Task 1.1: Add Workflow Concurrency

**Files:**
- Modify: `.github/workflows/daily_report.yml`

- [ ] **Step 1: Add workflow concurrency**

Insert after the `on:` block:

```yaml
concurrency:
  group: notice-daily-report
  cancel-in-progress: false
```

Expected behavior: a manual dispatch waits behind a scheduled run instead of racing the same SQLite file and bot commit.

- [ ] **Step 2: Verify YAML syntax locally**

Run:

```powershell
conda run --no-capture-output -n spider python -c "import yaml; yaml.safe_load(open('.github/workflows/daily_report.yml', encoding='utf-8'))"
```

Expected: exit code 0.

### Task 1.2: Checkpoint SQLite WAL Before Result Return

**Files:**
- Modify: `src/notice_push/storage.py`
- Modify: `src/notice_push/pipeline.py`
- Test: `tests/notice_push/test_storage.py`
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Write failing storage test**

Add to `tests/notice_push/test_storage.py`:

```python
def test_storage_checkpoint_truncates_wal_file(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    db_path = tmp_path / "state.sqlite3"
    storage = NoticeStorage(db_path, config.sources)
    storage.initialize()
    storage.upsert_seen_item(make_item("shu_official", "https://example.com/wal.htm"))

    storage.checkpoint()

    wal_path = tmp_path / "state.sqlite3-wal"
    assert not wal_path.exists() or wal_path.stat().st_size == 0
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_storage.py::test_storage_checkpoint_truncates_wal_file -q
```

Expected: fail with `AttributeError: 'NoticeStorage' object has no attribute 'checkpoint'`.

- [ ] **Step 3: Implement `NoticeStorage.checkpoint()`**

Add method:

```python
def checkpoint(self) -> None:
    if not self.db_path.exists():
        return
    with self._write_lock, self._connect() as conn:
        conn.execute("pragma wal_checkpoint(TRUNCATE)")
```

- [ ] **Step 4: Call checkpoint at end of non-dry run**

In `NoticePipeline.run()`, after `write_run_summary()` and before returning:

```python
if not options.dry_run:
    self.storage.checkpoint()
```

Keep this after summary JSON writing so the JSON and DB represent the same completed run.

- [ ] **Step 5: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_storage.py tests/notice_push/test_pipeline.py -q
```

Expected: all pass.

---

## Batch 2: Alert Semantics And Counter Correctness

### Task 2.1: Keep Audit Errors Out Of `source_errors`

**Files:**
- Modify: `src/notice_push/pipeline.py`
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Update failing test expectation**

In `test_pipeline_reports_audit_error_when_list_page_parses_no_items`, assert:

```python
assert len(result.audit_results) == 1
assert result.audit_results[0].issues[0].severity == "error"
assert result.source_errors == ()
```

Add a second test proving real directory fetch errors still populate `source_errors`:

```python
def test_pipeline_keeps_real_source_errors_separate_from_audit_errors(tmp_path):
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
        http_client=FakeHttp({}),
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: FakeAdapter(selected_source),
    )

    result = run_pipeline(
        pipeline,
        source_ids=["shu_official"],
        dry_run=False,
        max_pages_per_source=1,
        audit_sources=False,
    )

    assert result.audit_results == ()
    assert len(result.source_errors) == 1
    assert result.source_errors[0].source_id == source.id
```

This second test proves operational source errors still come from the normal directory crawl path, not from synthetic audit issues.

- [ ] **Step 2: Run test and confirm failure**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py::test_pipeline_reports_audit_error_when_list_page_parses_no_items -q
```

Expected: fail because `_audit_errors_as_source_errors()` still appends audit issues into `source_errors`.

- [ ] **Step 3: Remove audit-to-source conversion**

In `NoticePipeline.run()`, replace:

```python
source_errors.extend(_audit_errors_as_source_errors(audit_results))
```

with no operation. Delete `_audit_errors_as_source_errors()`.

- [ ] **Step 4: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py -q
```

Expected: all pass.

### Task 2.2: Centralize Pipeline Counters

**Files:**
- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/__main__.py`
- Modify: `src/notice_push/run_summary.py`
- Test: `tests/notice_push/test_cli.py`

- [ ] **Step 1: Add counter model**

Add to `models.py`:

```python
@dataclass(frozen=True)
class PipelineCounters:
    new_count: int
    retried_count: int
    summarized_count: int
    failed_count: int
    manual_review_count: int
    source_error_count: int
    audit_error_count: int
    audit_warning_count: int
    refresh_seen_error_count: int = 0
```

- [ ] **Step 2: Add helper function**

Create in `run_summary.py`:

```python
def pipeline_counters(result: PipelineResult) -> PipelineCounters:
    audit_error_count = sum(
        1
        for audit in result.audit_results
        for issue in audit.issues
        if issue.severity == "error"
    )
    audit_warning_count = sum(
        1
        for audit in result.audit_results
        for issue in audit.issues
        if issue.severity == "warning"
    )
    return PipelineCounters(
        new_count=result.new_count,
        retried_count=result.retried_count,
        summarized_count=result.summarized_count,
        failed_count=len(result.failed),
        manual_review_count=result.manual_review_count,
        source_error_count=len(result.source_errors),
        audit_error_count=audit_error_count,
        audit_warning_count=audit_warning_count,
        refresh_seen_error_count=len(getattr(result, "refresh_seen_errors", ())),
    )
```

Batch 3 later adds the real `refresh_seen_errors` field; the helper is already forward-compatible.

- [ ] **Step 3: Use counters in CLI and JSON**

Replace duplicate counting in `__main__.py` and `run_summary.py` with `pipeline_counters(result)`.

- [ ] **Step 4: Update workflow wording**

In `.github/workflows/daily_report.yml`, keep alert condition:

```yaml
if: steps.run_python_script.outputs.source_error_count != '0' || steps.run_python_script.outputs.audit_error_count != '0' || steps.run_python_script.outputs.exit_code == '2'
```

But email copy should label:

- `source_error_count`: 正式抓取目录页异常
- `audit_error_count`: 运行前 DOM 巡检异常

- [ ] **Step 5: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_cli.py tests/notice_push/test_pipeline.py -q
```

Expected: all pass.

---

## Batch 3: Observability Upgrade

### Task 3.1: Surface Refresh-Seen Failures

**Files:**
- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/pipeline.py`
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Add model**

Add to `models.py`:

```python
@dataclass(frozen=True)
class RefreshSeenError:
    source_id: str
    source_name: str
    title: str
    url: str
    reason: str
```

Add to `PipelineResult`:

```python
refresh_seen_errors: tuple[RefreshSeenError, ...] = field(default_factory=tuple)
```

- [ ] **Step 2: Write failing test**

Add a test where `refresh_seen_details=True` and adapter raises during refresh:

```python
def test_pipeline_reports_refresh_seen_detail_errors(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    storage = NoticeStorage(config.state_path, config.sources)
    storage.initialize()
    item = NoticeListItem(
        source_id=source.id,
        url="https://example.com/detail-1.htm",
        canonical_url="https://example.com/detail-1.htm",
        title="测试通知 1",
        published_at=datetime(2026, 6, 16),
        list_excerpt="列表摘要",
    )
    storage.upsert_seen_item(item)

    class RefreshFailingAdapter(FakeAdapter):
        def parse_detail(self, html, item):
            raise RuntimeError("refresh detail failed")

    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=FakeHttp({source.list_url: "list-1", "https://example.com/detail-1.htm": "detail"}),
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: RefreshFailingAdapter(selected_source),
    )

    result = run_pipeline(
        pipeline,
        source_ids=["shu_official"],
        dry_run=False,
        max_pages_per_source=1,
        refresh_seen_details=True,
        report_date=date(2026, 7, 6),
    )

    assert result.refresh_seen_errors[0].url == item.url
    assert "refresh detail failed" in result.refresh_seen_errors[0].reason
```

- [ ] **Step 3: Change `_update_seen_details_if_changed()` return type**

Return `list[RefreshSeenError]` instead of `None`. Replace silent `except Exception: return` with appending structured error.

- [ ] **Step 4: Include errors in result**

In `NoticePipeline.run()`, collect refresh errors and pass them into `PipelineResult`.

- [ ] **Step 5: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py -q
```

Expected: all pass.

### Task 3.2: Expand Run Summary JSON

**Files:**
- Modify: `src/notice_push/run_summary.py`
- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/pipeline.py`
- Modify: `src/notice_push/__main__.py`
- Test: `tests/notice_push/test_pipeline.py`
- Test: `tests/notice_push/test_cli.py`

- [ ] **Step 1: Add run timing fields**

Add to `PipelineResult`:

```python
started_at: str = ""
finished_at: str = ""
duration_seconds: float = 0.0
```

In `NoticePipeline.run()`, set start via `time.perf_counter()` and UTC ISO timestamps.

- [ ] **Step 2: Add source stats to JSON**

Extend `_run_summary_payload()` to include:

```python
"sources": [
    {
        "source_id": source_id,
        "source_name": source_name,
        "summarized_count": ...,
        "failed_count": ...,
        "source_error_count": ...,
        "audit_error_count": ...,
        "audit_warning_count": ...,
        "refresh_seen_error_count": ...,
    }
]
```

- [ ] **Step 3: Add failure type distribution**

Include:

```python
"failure_types": {
    "detail_empty": 2,
    "llm_rate_limit": 1
}
```

Add `failure_type: str = ""` to `FailedNotice` and populate it at every failure creation site. JSON should count `failure.failure_type` when present, otherwise fall back to the existing `_classify_failure(reason)` logic.

- [ ] **Step 4: Add model and media stats**

Include:

```python
"models": ["deepseek-v4-flash", "kimi-k2.7-code"],
"media_counts": {
    "pdf": 1,
    "image": 1,
    "video": 0
}
```

- [ ] **Step 5: Add git SHA from workflow**

In `__main__.py`, read `GITHUB_SHA` and pass into `PipelineResult` as `git_sha`. Locally default to empty string.

- [ ] **Step 6: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py tests/notice_push/test_cli.py -q
```

Expected: all pass.

---

## Batch 4: Source Audit And Parsing Robustness

### Task 4.1: Multi-Sample Adapter-Based Source Audit

**Files:**
- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/source_audit.py`
- Modify: `resources/config/runtime.yml`
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Add audit config**

Add to `resources/config/runtime.yml`:

```yaml
audit:
  min_list_items: 1
  sample_detail_count: 3
  required_content_kinds:
    - text
    - pdf
    - image
```

Add config dataclass:

```python
@dataclass(frozen=True)
class AuditPolicy:
    min_list_items: int = 1
    sample_detail_count: int = 3
    required_content_kinds: tuple[str, ...] = ("text", "pdf", "image")
```

- [ ] **Step 2: Expand audit result model**

Add:

```python
@dataclass(frozen=True)
class SourceAuditSample:
    title: str
    url: str
    content_kind: str
    content_length: int
    asset_count: int
```

Add `samples: tuple[SourceAuditSample, ...]` to `SourceAuditResult`.

- [ ] **Step 3: Write failing test for multiple samples**

Use `MultiItemAdapter` and assert three detail URLs were sampled when `sample_detail_count=3`.

- [ ] **Step 4: Implement sampling**

Change `SourceAuditor` to sample:

```python
for item in items[: self.sample_detail_count]:
    detail_html = self.http_client.get_text(item.url)
    detail = adapter.parse_detail(detail_html, item)
```

Every failed detail sample should be `warning`, not `error`, unless all sampled details fail.

- [ ] **Step 5: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py -q
```

Expected: all pass.

### Task 4.2: Validate Media With Response Headers And Magic Bytes

**Files:**
- Modify: `src/notice_push/http.py`
- Modify: `src/notice_push/media.py`
- Test: `tests/notice_push/test_http.py`
- Test: `tests/notice_push/test_media.py`

- [ ] **Step 1: Add response object while preserving current byte API**

Create:

```python
@dataclass(frozen=True)
class DownloadedBytes:
    content: bytes
    content_type: str = ""
```

Add `HttpClient.get_download_limited(url, max_bytes) -> DownloadedBytes`. Keep existing `get_bytes_limited(url, max_bytes) -> bytes` as a thin wrapper:

```python
def get_bytes_limited(self, url: str, max_bytes: int) -> bytes:
    return self.get_download_limited(url, max_bytes).content
```

- [ ] **Step 2: Write tests**

Add tests:

```python
def test_pdf_download_accepts_query_url_when_magic_bytes_match():
    asset = NoticeAsset("pdf", "primary", "download", "https://example.com/download?id=1", "")
    client = _DownloadHttpClient(b"%PDF-1.7 body", "application/octet-stream")
    path = download_asset_to_temp(client, asset, max_bytes=1024)
    assert path.suffix == ".pdf"
```

```python
def test_image_download_rejects_wrong_magic_bytes_even_when_url_looks_like_png():
    asset = NoticeAsset("image", "primary", "notice.png", "https://example.com/notice.png", "image/png")
    with pytest.raises(ValueError, match="image content signature"):
        download_asset_to_temp(_DownloadHttpClient(b"not image", "image/png"), asset, max_bytes=1024)
```

- [ ] **Step 3: Implement PDF magic checks**

Accept PDF when any is true:

- asset MIME is `application/pdf`
- response content type is `application/pdf`
- URL/name suffix is `.pdf`
- content starts with `b"%PDF"`

For suffixless PDFs, choose `.pdf`.

- [ ] **Step 4: Implement image magic checks**

Recognize PNG, JPEG, GIF, WEBP signatures. If response/content claims image but signature is unknown, reject with `image content signature is not recognized`.

- [ ] **Step 5: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_http.py tests/notice_push/test_media.py -q
```

Expected: all pass.

### Task 4.3: Summary Format Repair Before Failure

**Files:**
- Modify: `src/notice_push/summary_validator.py`
- Modify: `src/notice_push/summarizer.py`
- Test: `tests/notice_push/test_summarizer.py`

- [ ] **Step 1: Add normalizer tests**

Add:

```python
def test_summary_validator_normalizes_full_width_colon_fields():
    markdown = "\n".join([
        "## 官网|行政|周常事务|测试通知",
        "- **发布时间：** 2026-06-16",
        "- **影响对象：** 全校师生",
        "- **核心信息：** 核心内容",
        "- **行动指引：** 按要求办理",
        "- **截止时间：** 未提及",
        "- **相关链接：** 未提及",
    ])

    normalized = normalize_summary_markdown(markdown)

    assert "- **发布时间**: 2026-06-16" in normalized
    validate_summary_markdown(normalized)
```

- [ ] **Step 2: Implement normalizer**

Add:

```python
def normalize_summary_markdown(markdown: str) -> str:
    for field in REQUIRED_SUMMARY_FIELDS:
        markdown = re.sub(
            rf"\*\*{field}[：:]\*\*\s*",
            f"**{field}**: ",
            markdown,
        )
    return markdown
```

- [ ] **Step 3: Use normalizer before validation**

In both summarizers:

```python
content = normalize_summary_markdown(content)
validate_summary_markdown(content)
```

- [ ] **Step 4: Add one repair retry**

If validation still fails, make one additional LLM call with a system/user message asking to reformat the prior answer only. Keep this behind config:

```yaml
llm:
  summary_format_repair_retries: 1
```

Do not add more than one repair retry in this batch.

- [ ] **Step 5: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_summarizer.py -q
```

Expected: all pass.

---

## Batch 5: CI, Doctor, And Final Guardrails

### Task 5.1: Add Workflow And CLI Smoke To CI

**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: no Python test required

- [ ] **Step 1: Add actionlint**

Add to `.github/workflows/ci.yml`:

```yaml
      - name: Check workflows
        uses: rhysd/actionlint@v1
```

- [ ] **Step 2: Add doctor smoke**

Add:

```yaml
      - run: python -m src.notice_push --doctor
```

This must run with no secrets and still exit 0 if only API key warnings exist.

- [ ] **Step 3: Add offline CLI smoke**

Add a pytest-backed smoke instead of live network:

```yaml
      - run: pytest tests/notice_push/test_cli.py tests/notice_push/test_sources.py -q
```

Keep full `pytest -q` after it.

- [ ] **Step 4: Verify YAML syntax locally**

Run:

```powershell
conda run --no-capture-output -n spider python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml', encoding='utf-8'))"
```

Expected: exit code 0.

### Task 5.2: Strengthen Doctor

**Files:**
- Modify: `src/notice_push/doctor.py`
- Modify: `README.md`
- Test: `tests/notice_push/test_cli.py`

- [ ] **Step 1: Add doctor checks**

Add checks for:

- SQLite `schema_migrations` contains `2026_07_06_baseline`
- workflow exists and parses as YAML
- `runtime.yml` exists and has enabled sources
- prompt output fields match `REQUIRED_SUMMARY_FIELDS`
- media policy max bytes are positive

- [ ] **Step 2: Add tests**

Add tests that monkeypatch a broken prompt and invalid media policy, expecting `doctor_error=`.

- [ ] **Step 3: Update README**

In local development section, clarify:

```text
--doctor 不会访问源站，也不会初始化 LLM 客户端；缺少 API key 只输出 warning。
```

- [ ] **Step 4: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_cli.py -q
conda run --no-capture-output -n spider python -m src.notice_push --doctor
```

Expected: tests pass; doctor exits 0 in normal checkout.

---

## Final Verification

- [ ] Run full unit tests:

```powershell
conda run --no-capture-output -n spider pytest -q
```

Expected: all tests pass.

- [ ] Run compile check:

```powershell
conda run --no-capture-output -n spider python -m compileall -q src
```

Expected: exit code 0.

- [ ] Validate workflow YAML:

```powershell
conda run --no-capture-output -n spider python -c "import yaml; [yaml.safe_load(open(path, encoding='utf-8')) for path in ['.github/workflows/ci.yml', '.github/workflows/daily_report.yml']]"
```

Expected: exit code 0.

- [ ] Run doctor:

```powershell
conda run --no-capture-output -n spider python -m src.notice_push --doctor
```

Expected: exit code 0 in a normal checkout.

- [ ] Run git status:

```powershell
git status --short
```

Expected: implementation files are visible. `resources/notice_records.csv` remains unrelated and must not be staged unless user explicitly requests it.

## Execution Policy

- Do not commit or push unless the user explicitly asks.
- Execute batches in order.
- After each batch, run that batch's focused tests.
- After Batch 5, run final verification.
- Use Playwright MCP only for manual investigation or fixture refresh. Do not add browser automation to GitHub Actions.
