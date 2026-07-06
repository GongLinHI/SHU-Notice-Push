# Production Readiness And Quality Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有重构完成后的 `src.notice_push` 主链路上，补齐生产运行质量、每次执行的源站 DOM 巡检、多模态边界控制、可观测性和维护文档。

**Architecture:** 短期继续把 `resources/notice_state.sqlite3` 提交到 Git，但增加 schema version、运行前备份、状态体检和独立 CI 防护。每次 pipeline 执行默认做轻量 DOM 巡检，巡检失败进入运行异常告警；摘要和媒体处理增加结构化校验与大小限制，避免单个异常通知拖垮日报任务。

**Tech Stack:** Python 3.12, pytest, sqlite3, requests, BeautifulSoup, PyYAML, GitHub Actions, conda environment `spider`.

---

## Decisions Locked

- SQLite 状态库短期继续提交到 Git，不迁到 artifact/cache/外部数据库。
- DOM 巡检频率为每次执行：GitHub Actions 日报、本地 `python -m src.notice_push` 默认都会运行。
- DOM 巡检使用当前 HTTP + BeautifulSoup + adapter 体系，不引入 Playwright 到 GitHub Actions 主链路；Playwright 只作为人工排查工具。
- 不新增重量级依赖；图片/PDF 先做大小、MIME、后缀和文本长度限制，不做图片压缩。
- 不修改或提交 `resources/notice_records.csv`。

## File Structure

- Create `.github/workflows/ci.yml`: 独立 CI，运行测试和 compileall。
- Modify `.github/workflows/daily_report.yml`: 接入每次执行 DOM 巡检输出、状态库备份 artifact、运行摘要 artifact。
- Create `src/notice_push/source_audit.py`: 源站目录页和样例详情页 DOM 巡检。
- Create `src/notice_push/run_summary.py`: 输出 JSON 运行摘要和巡检摘要。
- Create `src/notice_push/storage_migrations.py`: SQLite schema version 与迁移记录。
- Modify `src/notice_push/storage.py`: 初始化时执行迁移、提供 health check。
- Modify `src/notice_push/models.py`: 增加 audit、run summary、media policy 相关 dataclass。
- Modify `src/notice_push/__main__.py`: 增加 `--audit-only`、`--doctor`、`--skip-source-audit`，并打印新计数。
- Modify `src/notice_push/pipeline.py`: 每次执行前运行 source audit，把 audit issue 合并到 `PipelineResult`。
- Modify `src/notice_push/http.py` and `src/notice_push/media.py`: 支持下载大小限制与媒体类型校验。
- Create `src/notice_push/summary_validator.py`: 校验 LLM Markdown 摘要模板字段。
- Modify `src/notice_push/summarizer.py`: 保存摘要前调用 validator。
- Create `src/notice_push/doctor.py`: 本地和 Actions 可复用的配置/状态体检。
- Create `docs/add-source-guide.md`: 新增通知源操作指南和测试模板。

## Task 1: Add CI And Keep SQLite-In-Git Safe

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `.github/workflows/daily_report.yml`
- Create: `src/notice_push/storage_migrations.py`
- Modify: `src/notice_push/storage.py`
- Test: `tests/notice_push/test_storage.py`

- [ ] **Step 1: Write storage migration tests**

Add tests covering:

```python
def test_storage_records_schema_migration_version(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)

    storage.initialize()

    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        versions = [row[0] for row in conn.execute("select version from schema_migrations")]

    assert "2026_07_06_baseline" in versions


def test_storage_health_reports_existing_database(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()

    health = storage.health_check()

    assert health.exists is True
    assert health.source_count == 3
    assert health.schema_versions == ("2026_07_06_baseline",)
```

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_storage.py -q
```

Expected: new tests fail because migration table and `health_check()` do not exist.

- [ ] **Step 2: Implement schema migration baseline**

Create `src/notice_push/storage_migrations.py` with:

```python
BASELINE_SCHEMA_VERSION = "2026_07_06_baseline"


def ensure_schema_migrations(conn) -> None:
    conn.execute(
        """
        create table if not exists schema_migrations (
            version text primary key,
            applied_at text not null
        )
        """
    )


def record_baseline_migration(conn, applied_at: str) -> None:
    conn.execute(
        """
        insert or ignore into schema_migrations(version, applied_at)
        values (?, ?)
        """,
        (BASELINE_SCHEMA_VERSION, applied_at),
    )
```

Update `NoticeStorage.initialize()` to call `ensure_schema_migrations(conn)` before table creation and `record_baseline_migration(conn, now)` after `_ensure_notice_columns(conn)`.

- [ ] **Step 3: Add storage health model and method**

Add to `src/notice_push/models.py`:

```python
@dataclass(frozen=True)
class StorageHealth:
    exists: bool
    source_count: int
    notice_count: int
    schema_versions: tuple[str, ...]
```

Add `NoticeStorage.health_check()` returning `StorageHealth`. If the DB file does not exist, return `exists=False`, `source_count=0`, `notice_count=0`, `schema_versions=()`.

- [ ] **Step 4: Add independent CI workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - run: pip install -r requirements.txt
      - run: pytest -q
      - run: python -m compileall -q src
```

- [ ] **Step 5: Backup SQLite before daily run**

In `.github/workflows/daily_report.yml`, add a step before `Run notice pipeline`:

```yaml
      - name: Backup SQLite state
        id: backup_state
        run: |
          if [ -f resources/notice_state.sqlite3 ]; then
            cp resources/notice_state.sqlite3 "$RUNNER_TEMP/notice_state_before_run.sqlite3"
            echo "backup_exists=true" >> "$GITHUB_OUTPUT"
          else
            echo "backup_exists=false" >> "$GITHUB_OUTPUT"
          fi
```

Add an upload-artifact step after the pipeline run:

```yaml
      - name: Upload SQLite backup
        if: steps.backup_state.outputs.backup_exists == 'true'
        uses: actions/upload-artifact@v4
        with:
          name: notice-state-before-run-${{ steps.date.outputs.date }}
          path: ${{ runner.temp }}/notice_state_before_run.sqlite3
          retention-days: 14
```

- [ ] **Step 6: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_storage.py -q
conda run --no-capture-output -n spider pytest -q
conda run --no-capture-output -n spider python -m compileall -q src
```

Expected: all tests pass.

## Task 2: Run DOM Source Audit On Every Execution

**Files:**
- Create: `src/notice_push/source_audit.py`
- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/__main__.py`
- Modify: `src/notice_push/pipeline.py`
- Modify: `.github/workflows/daily_report.yml`
- Test: `tests/notice_push/test_pipeline.py`
- Test: `tests/notice_push/test_cli.py`

- [ ] **Step 1: Add audit models**

Add to `src/notice_push/models.py`:

```python
@dataclass(frozen=True)
class SourceAuditIssue:
    source_id: str
    source_name: str
    url: str
    severity: str
    reason: str


@dataclass(frozen=True)
class SourceAuditResult:
    source_id: str
    source_name: str
    list_url: str
    list_item_count: int
    sampled_detail_url: str = ""
    detail_content_kind: str = ""
    issues: tuple[SourceAuditIssue, ...] = field(default_factory=tuple)
```

Add to `PipelineRunOptions`:

```python
audit_sources: bool = True
```

Add to `PipelineResult`:

```python
audit_results: tuple[SourceAuditResult, ...] = field(default_factory=tuple)
```

- [ ] **Step 2: Add failing audit tests**

In `tests/notice_push/test_pipeline.py`, add:

```python
def test_pipeline_reports_audit_error_when_list_page_parses_no_items(tmp_path):
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
        http_client=FakeHttp({source.list_url: "<html>changed</html>"}),
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: FakeAdapter(selected_source),
    )

    result = run_pipeline(
        pipeline,
        source_ids=["shu_official"],
        dry_run=True,
        max_pages_per_source=1,
        audit_sources=True,
    )

    assert len(result.audit_results) == 1
    assert result.audit_results[0].list_item_count == 0
    assert result.audit_results[0].issues[0].severity == "error"
```

In `tests/notice_push/test_cli.py`, add a CLI assertion that `audit_error_count=` is printed.

- [ ] **Step 3: Implement source audit runner**

Create `src/notice_push/source_audit.py`:

```python
class SourceAuditor:
    def __init__(self, http_client, adapter_factory, min_list_items: int = 1):
        self.http_client = http_client
        self.adapter_factory = adapter_factory
        self.min_list_items = min_list_items

    def audit_source(self, source: NoticeSource) -> SourceAuditResult:
        adapter = self.adapter_factory(source)
        issues: list[SourceAuditIssue] = []
        try:
            list_html = self.http_client.get_text(source.list_url)
            items = adapter.parse_list_page(list_html, source.list_url)
        except Exception as exc:
            issue = SourceAuditIssue(source.id, source.name, source.list_url, "error", str(exc))
            return SourceAuditResult(source.id, source.name, source.list_url, 0, issues=(issue,))

        if len(items) < self.min_list_items:
            issues.append(
                SourceAuditIssue(
                    source.id,
                    source.name,
                    source.list_url,
                    "error",
                    f"list page parsed {len(items)} items; expected at least {self.min_list_items}",
                )
            )

        sampled_detail_url = ""
        detail_content_kind = ""
        if items:
            sampled_detail_url = items[0].url
            try:
                detail_html = self.http_client.get_text(items[0].url)
                detail = adapter.parse_detail(detail_html, items[0])
                detail_content_kind = detail.content_kind
            except Exception as exc:
                issues.append(SourceAuditIssue(source.id, source.name, items[0].url, "warning", str(exc)))

        return SourceAuditResult(
            source_id=source.id,
            source_name=source.name,
            list_url=source.list_url,
            list_item_count=len(items),
            sampled_detail_url=sampled_detail_url,
            detail_content_kind=detail_content_kind,
            issues=tuple(issues),
        )
```

- [ ] **Step 4: Wire audit into every pipeline execution**

In `NoticePipeline.run()`, after `selected_sources` is computed and before normal crawling:

```python
audit_results = ()
if options.audit_sources:
    auditor = SourceAuditor(self.http_client, self.adapter_factory)
    audit_results = tuple(auditor.audit_source(source) for source in selected_sources)
```

Return `audit_results=audit_results`. Do not stop the pipeline for warnings. Convert only `severity == "error"` issues into `SourceError` entries so GitHub Actions already sends the operational alert.

- [ ] **Step 5: Add CLI flags and outputs**

In `src/notice_push/__main__.py`:

- Add `--skip-source-audit` to disable audit in emergency.
- Add `--audit-only` to run only audit and exit 0 when no audit errors, 1 when audit errors exist.
- Print:

```python
audit_error_count = sum(1 for result in result.audit_results for issue in result.issues if issue.severity == "error")
audit_warning_count = sum(1 for result in result.audit_results for issue in result.issues if issue.severity == "warning")
print(f"audit_error_count={audit_error_count}")
print(f"audit_warning_count={audit_warning_count}")
```

- [ ] **Step 6: Update GitHub Actions alert parsing**

In `.github/workflows/daily_report.yml`, parse `audit_error_count` and `audit_warning_count`. Include both in the operational alert email. Alert condition becomes:

```yaml
if: steps.run_python_script.outputs.source_error_count != '0' || steps.run_python_script.outputs.audit_error_count != '0' || steps.run_python_script.outputs.exit_code == '2'
```

- [ ] **Step 7: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py tests/notice_push/test_cli.py -q
conda run --no-capture-output -n spider pytest -q
```

Expected: all tests pass.

## Task 3: Add Media Guardrails For PDF And Image Notices

**Files:**
- Modify: `resources/config/runtime.yml`
- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/config.py`
- Modify: `src/notice_push/http.py`
- Modify: `src/notice_push/media.py`
- Modify: `src/notice_push/summarizer.py`
- Test: `tests/notice_push/test_config_models.py`
- Test: `tests/notice_push/test_media.py`
- Test: `tests/notice_push/test_summarizer.py`

- [ ] **Step 1: Add media policy config**

Add to `runtime.yml`:

```yaml
media:
  pdf_max_bytes: 20971520
  image_max_bytes: 8388608
  pdf_extracted_text_max_chars: 50000
```

Add to `models.py`:

```python
@dataclass(frozen=True)
class MediaPolicy:
    pdf_max_bytes: int = 20971520
    image_max_bytes: int = 8388608
    pdf_extracted_text_max_chars: int = 50000
```

Add `media_policy: MediaPolicy` to `AppConfig`.

- [ ] **Step 2: Add config tests**

In `tests/notice_push/test_config_models.py`, verify default and YAML override values:

```python
assert config.media_policy.pdf_max_bytes == 20971520
assert config.media_policy.image_max_bytes == 8388608
assert config.media_policy.pdf_extracted_text_max_chars == 50000
```

- [ ] **Step 3: Add limited byte download**

Add `HttpClient.get_bytes_limited(url: str, max_bytes: int) -> bytes` that uses `stream=True`, accumulates chunks, and raises `ValueError("download exceeds max_bytes")` once the limit is exceeded.

- [ ] **Step 4: Enforce media size and type**

Change `download_asset_to_temp(http_client, asset, max_bytes)` to call `get_bytes_limited`. Add checks:

- PDF assets must have `.pdf` suffix or `application/pdf` MIME.
- Image assets must have image suffix or `image/` MIME.
- Empty downloads raise `ValueError("downloaded media is empty")`.

- [ ] **Step 5: Limit Kimi PDF extracted text**

In `_summarize_pdf()`, after `file_content` is read:

```python
if len(file_content) > self.media_policy.pdf_extracted_text_max_chars:
    file_content = file_content[: self.media_policy.pdf_extracted_text_max_chars]
```

Pass `media_policy` from `build_pipeline()` into `KimiMultimodalSummarizer`.

- [ ] **Step 6: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_config_models.py tests/notice_push/test_media.py tests/notice_push/test_summarizer.py -q
conda run --no-capture-output -n spider pytest -q
```

Expected: all tests pass.

## Task 4: Validate Summary Markdown And Emit Run Summary JSON

**Files:**
- Create: `src/notice_push/summary_validator.py`
- Create: `src/notice_push/run_summary.py`
- Modify: `src/notice_push/summarizer.py`
- Modify: `src/notice_push/pipeline.py`
- Modify: `.github/workflows/daily_report.yml`
- Test: `tests/notice_push/test_summarizer.py`
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Add summary validator**

Create `src/notice_push/summary_validator.py`:

```python
REQUIRED_SUMMARY_FIELDS = ("发布时间", "影响对象", "核心信息", "行动指引", "截止时间", "相关链接")


def validate_summary_markdown(markdown: str) -> None:
    if not markdown.strip().startswith("## "):
        raise ValueError("summary must start with a level-2 heading")
    for field in REQUIRED_SUMMARY_FIELDS:
        if f"**{field}**" not in markdown:
            raise ValueError(f"summary missing required field: {field}")
```

Call it before creating `NoticeSummary` in both text and Kimi summarizers.

- [ ] **Step 2: Add run summary JSON writer**

Create `src/notice_push/run_summary.py` with `write_run_summary(output_dir, report_date, pipeline_result) -> Path`. Output path:

```text
resources/results/json/YYYY-MM-DD.json
```

JSON fields:

- `report_date`
- `new_count`
- `retried_count`
- `summarized_count`
- `manual_review_count`
- `failed_count`
- `source_error_count`
- `audit_error_count`
- `audit_warning_count`
- `report_path`

- [ ] **Step 3: Wire JSON output into pipeline**

When `options.dry_run is False`, write JSON summary even if no Markdown report exists. Add `run_summary_path: Optional[Path] = None` to `PipelineResult` and print it in CLI as `run_summary_path=...`.

- [ ] **Step 4: Upload JSON as artifact**

In `.github/workflows/daily_report.yml`, upload `resources/results/json/${{ steps.date.outputs.date }}.json` as artifact with retention 30 days. Do not commit JSON summaries unless the user later requests historical JSON in Git.

- [ ] **Step 5: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_summarizer.py tests/notice_push/test_pipeline.py -q
conda run --no-capture-output -n spider pytest -q
```

Expected: all tests pass.

## Task 5: Add Doctor Command For Local And Action Diagnostics

**Files:**
- Create: `src/notice_push/doctor.py`
- Modify: `src/notice_push/__main__.py`
- Modify: `README.md`
- Test: `tests/notice_push/test_cli.py`

- [ ] **Step 1: Add doctor checks**

Create `src/notice_push/doctor.py` with `run_doctor(config) -> tuple[str, ...]`. Checks:

- `resources/prompts/{prompt_name}.md` exists.
- `config.state_path.parent` exists or can be created.
- At least one source is enabled.
- Every enabled source has `name`, `base_url`, `list_url`, and `adapter`.
- `DEEPSEEK_API_KEY` absence returns a warning, not a hard failure.
- `KIMI_API_KEY` absence returns a warning, not a hard failure.
- SQLite health check succeeds if state DB exists.

- [ ] **Step 2: Add CLI flag**

Add `--doctor` to `src/notice_push/__main__.py`. When present:

- Load config.
- Run doctor.
- Print one line per finding prefixed with `doctor_warning=`.
- Return 0 when only warnings exist.
- Return 2 only for structural config errors.

- [ ] **Step 3: Document usage**

Add to README:

```powershell
conda run --no-capture-output -n spider python -m src.notice_push --doctor
```

- [ ] **Step 4: Verify**

Run:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_cli.py -q
conda run --no-capture-output -n spider python -m src.notice_push --doctor
```

Expected: tests pass; doctor command prints warnings or exits 0 in a normal checkout.

## Task 6: Add Source-Extension Guide And Fixtures Policy

**Files:**
- Create: `docs/add-source-guide.md`
- Modify: `README.md`
- Test: no code test required

- [ ] **Step 1: Write source guide**

Create `docs/add-source-guide.md` with:

- How to add a `sources.<source_id>` entry in `runtime.yml`.
- How to implement `NoticeSourceAdapter`.
- Required tests: list page, detail page, next page, PDF/image/video fixture when relevant.
- Fixture naming convention: `tests/fixtures/source_pages/<source_id>_<case>.html`.
- Required local commands:

```powershell
conda run --no-capture-output -n spider pytest tests/notice_push/test_sources.py -q
conda run --no-capture-output -n spider pytest -q
```

- [ ] **Step 2: Link from README**

In README “添加新通知源” section, link to `docs/add-source-guide.md`.

- [ ] **Step 3: Verify docs are present**

Run:

```powershell
Test-Path docs/add-source-guide.md
```

Expected: `True`.

## Final Verification

- [ ] Run full tests:

```powershell
conda run --no-capture-output -n spider pytest -q
```

Expected: all tests pass.

- [ ] Run compile check:

```powershell
conda run --no-capture-output -n spider python -m compileall -q src
```

Expected: exit code 0.

- [ ] Run status check:

```powershell
git status --short
```

Expected: implementation and docs changes are visible. `resources/notice_records.csv` remains unstaged and unrelated.

## Execution Notes

- Do not commit or push unless the user explicitly asks.
- If implementing in batches, complete tasks in order: CI/state safety, DOM audit, media guardrails, summary JSON, doctor, docs.
- If a live source changes during implementation, add or update a fixture from the observed HTML and keep the parser change source-specific.
