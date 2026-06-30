# Rebuild Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining review gaps so the rebuilt notice pipeline satisfies `rebuild.md` in architecture, failure semantics, state behavior, and repository hygiene.

**Architecture:** Keep the current `notice_push` package shape. Remove hard-coded adapter creation from `pipeline.py` by moving adapter resolution into a dynamic import registry utility. Split source-level crawl failures from notice-level failures so daily notice reports represent new notices/manual-review items rather than pure source outages. Add a lightweight seen-notice change check that updates stored detail/content hash without resending summaries. Route operational failures through a separate GitHub Actions alert email, not the daily notice email.

**Tech Stack:** Python 3.12, `pytest`, `sqlite3`, `requests`, `beautifulsoup4`, `PyYAML`, GitHub Actions, conda env `spider`.

---

## Scope Decisions

- Keep `daily` profile as currently approved: `max_pages_per_source=5`, `detail_max_workers=2`, `summary_max_workers=3`, `http_initial_retry_delay=0.8`.
- Keep key runtime values in `resources/config/runtime.yml`. Do not reintroduce many GitHub Action env overrides unless needed for secrets.
- Treat pure source directory failures as source errors, not new notice failures. They should not produce the daily notice email.
- Print `source_error_count` in CLI/Action logs only. Do not render source directory failures into the daily Markdown/HTML report.
- Send a separate operational alert email when `source_error_count > 0` or when the Python pipeline fails before it can print normal counters.
- Treat notice-level detail/summary failures as reportable manual-review items because they correspond to newly discovered notices.
- Keep notice-level detail/summary failures in the daily report. They are not counted as source directory failures and should not trigger the operational alert email by themselves.
- Do not run real API smoke tests by default. If needed later, use `.tmp/live-smoke/...` paths only.

## Target File Map

- Modify `src/notice_push/models.py`: add `SourceError`; extend `PipelineResult` with `source_errors`.
- Modify `src/notice_push/pipeline.py`: use dynamic adapter loader; separate source directory failures from notice failures; add seen-notice change checking.
- Modify `src/notice_push/storage.py`: add methods to return seen rows and update changed detail/content hash without resending.
- Modify `src/notice_push/__main__.py`: print `source_error_count`; keep `0` for generated daily report/dry-run and `1` for no daily report.
- Modify `.github/workflows/daily_report.yml`: parse `source_error_count`; keep no-new skip behavior; send a separate operational alert email for source outages or fatal run errors.
- Modify `resources/config/runtime.yml`: switch adapter values to import paths.
- Modify `.gitignore`: ignore `.idea/` and `.trae/`.
- Test `tests/notice_push/test_config_models.py`: assert source adapter import paths load from YAML.
- Test `tests/notice_push/test_pipeline.py`: dynamic adapter loading, source-error separation, seen-notice change update.
- Test `tests/notice_push/test_storage.py`: update changed detail/content hash for already-seen notices.
- Test `tests/notice_push/test_cli.py`: pure source outage exit behavior and printed count.

---

### Task 1: Dynamic Adapter Loading

**Files:**
- Modify: `src/notice_push/pipeline.py`
- Modify: `resources/config/runtime.yml`
- Test: `tests/notice_push/test_pipeline.py`
- Test: `tests/notice_push/test_config_models.py`

- [ ] **Step 1: Add failing test for import-path adapter loading**

Add to `tests/notice_push/test_pipeline.py`:

```python
def test_create_adapter_loads_adapter_from_import_path(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    source = config.source_by_id("shu_official")
    import_path_source = type(source)(
        id=source.id,
        name=source.name,
        base_url=source.base_url,
        list_url=source.list_url,
        adapter="src.notice_push.sources.shu_official.ShuOfficialAdapter",
        enabled=source.enabled,
    )

    from src.notice_push.pipeline import create_adapter
    from src.notice_push.sources.shu_official import ShuOfficialAdapter

    adapter = create_adapter(import_path_source)

    assert isinstance(adapter, ShuOfficialAdapter)
```

- [ ] **Step 2: Run adapter test and verify failure**

Run:

```bash
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py::test_create_adapter_loads_adapter_from_import_path -q
```

Expected: FAIL because `create_adapter()` only handles short hard-coded names.

- [ ] **Step 3: Implement dynamic loader with short-name compatibility**

In `src/notice_push/pipeline.py`, replace the adapter imports and `create_adapter()` with:

```python
from importlib import import_module


ADAPTER_ALIASES = {
    "shu_official": "src.notice_push.sources.shu_official.ShuOfficialAdapter",
    "management_school": "src.notice_push.sources.management_school.ManagementSchoolAdapter",
    "graduate_school": "src.notice_push.sources.graduate_school.GraduateSchoolAdapter",
}


def create_adapter(source: NoticeSource):
    adapter_path = ADAPTER_ALIASES.get(source.adapter, source.adapter)
    module_name, _, class_name = adapter_path.rpartition(".")
    if not module_name or not class_name:
        raise ValueError(
            f"Adapter for source '{source.id}' must be an import path like "
            "'package.module.AdapterClass', got: {source.adapter}"
        )
    module = import_module(module_name)
    adapter_class = getattr(module, class_name)
    return adapter_class(source)
```

Remove direct imports of `GraduateSchoolAdapter`, `ManagementSchoolAdapter`, and `ShuOfficialAdapter` from the top of `pipeline.py`.

- [ ] **Step 4: Update runtime adapter config to import paths**

In `resources/config/runtime.yml`, change:

```yaml
adapter: shu_official
adapter: management_school
adapter: graduate_school
```

to:

```yaml
adapter: src.notice_push.sources.shu_official.ShuOfficialAdapter
adapter: src.notice_push.sources.management_school.ManagementSchoolAdapter
adapter: src.notice_push.sources.graduate_school.GraduateSchoolAdapter
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py tests/notice_push/test_config_models.py tests/notice_push/test_sources.py -q
```

Expected: PASS.

---

### Task 2: Separate Source Errors From Notice Failures

**Files:**
- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/pipeline.py`
- Modify: `src/notice_push/__main__.py`
- Modify: `.github/workflows/daily_report.yml`
- Test: `tests/notice_push/test_pipeline.py`
- Test: `tests/notice_push/test_cli.py`

- [ ] **Step 1: Add `SourceError` model and failing pipeline test**

Add to `src/notice_push/models.py` only after the failing test is written.

First add this test to `tests/notice_push/test_pipeline.py`:

```python
def test_pipeline_records_source_directory_failure_without_creating_report(tmp_path):
    config = load_config(
        env={},
        repo_root=tmp_path,
        state_path=tmp_path / "state.sqlite3",
        output_dir=tmp_path / "results",
    )
    source = config.source_by_id("shu_official")
    http = FakeHttp({})
    storage = NoticeStorage(config.state_path, config.sources)
    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=http,
        summarizer=FakeSummarizer(),
        adapter_factory=lambda selected_source: FakeAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        limit=1,
        max_pages_per_source=1,
        report_date=date(2026, 6, 30),
    )

    assert result.new_count == 0
    assert result.failed == ()
    assert len(result.source_errors) == 1
    assert result.source_errors[0].source_id == source.id
    assert result.report_path is None
```

- [ ] **Step 2: Run failing pipeline test**

Run:

```bash
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py::test_pipeline_records_source_directory_failure_without_creating_report -q
```

Expected: FAIL because `PipelineResult` has no `source_errors` and source errors currently become `FailedNotice`.

- [ ] **Step 3: Add model support**

In `src/notice_push/models.py`, add:

```python
@dataclass(frozen=True)
class SourceError:
    source_id: str
    source_name: str
    url: str
    reason: str
```

Update `PipelineResult`:

```python
@dataclass(frozen=True)
class PipelineResult:
    report_path: Optional[Path]
    new_count: int
    summarized_count: int
    failed: tuple[FailedNotice, ...] = field(default_factory=tuple)
    source_errors: tuple[SourceError, ...] = field(default_factory=tuple)
```

- [ ] **Step 4: Update pipeline source-error path**

In `src/notice_push/pipeline.py`:

```python
from src.notice_push.models import FailedNotice, NoticeDetail, NoticeListItem, NoticeSource, PipelineResult, SourceError
```

Inside `run()` add:

```python
source_errors: list[SourceError] = []
```

Replace directory page exception handling with:

```python
except Exception as exc:
    source_errors.append(
        SourceError(
            source_id=source.id,
            source_name=source.name,
            url=page_url,
            reason=str(exc),
        )
    )
    break
```

Keep report generation focused on notice-level entries and notice-level failures only:

```python
if not dry_run and (entries or failures):
    markdown = render_report(report_day, entries, failures)
    report_path = write_report(self.config.output_dir, report_day, markdown)
```

Return:

```python
return PipelineResult(
    report_path=report_path,
    new_count=new_count,
    summarized_count=len(entries),
    failed=tuple(failures),
    source_errors=tuple(source_errors),
)
```

- [ ] **Step 5: Keep daily report rendering source-error free**

Do not change `src/notice_push/report.py` to accept `SourceError`. The daily report must remain limited to this existing signature:

```python
def render_report(
    report_date: date,
    entries: list[ReportEntry],
    failures: list[FailedNotice],
) -> str:
```

This keeps the product boundary clear:

- Daily notice email: new notices and new-notice manual review items only.
- Operational alert email: source directory outages and fatal pipeline failures only.

- [ ] **Step 6: Update CLI output and exit semantics**

In `src/notice_push/__main__.py`, print:

```python
print(f"source_error_count={len(result.source_errors)}")
```

Exit behavior remains:

```python
if args.dry_run:
    return 0
return 0 if result.report_path else 1
```

This means pure source errors do not send email; they skip like no-new, but `source_error_count` is visible in logs.

- [ ] **Step 7: Update workflow output parsing and persist run log**

In `.github/workflows/daily_report.yml`, after `failed_count=...`, add:

```bash
source_error_count=$(echo "$output" | awk -F= '/^source_error_count=/{print $2}' | tail -n1)
```

Add outputs and write the raw pipeline log to a temporary file:

```bash
echo "source_error_count=${source_error_count:-0}" >> "$GITHUB_OUTPUT"
echo "log_path=$RUNNER_TEMP/notice_pipeline.log" >> "$GITHUB_OUTPUT"
printf '%s\n' "$output" > "$RUNNER_TEMP/notice_pipeline.log"
```

Update no-new log line to mention source errors:

```bash
echo "No reportable new notices found today; source_error_count=${{ steps.run_python_script.outputs.source_error_count }}."
```

- [ ] **Step 8: Add separate operational alert email branch**

Move the existing `Fail if notice pipeline errored` step so it runs after the alert email step. Then add these steps after `Check if there are new notices` and before `Check if today's markdown file exists`:

```yaml
      - name: Prepare operational alert email
        id: prepare_alert
        if: steps.run_python_script.outputs.source_error_count != '0' || steps.run_python_script.outputs.exit_code == '2'
        run: |
          alert_file="$RUNNER_TEMP/notice_alert.html"
          {
            echo '<!doctype html><html><body style="font-family:Arial,sans-serif;line-height:1.6;color:#1f2937;">'
            echo '<h2>上海大学通知推送运行异常</h2>'
            echo '<p>本邮件只表示爬虫运行或源站访问异常，不代表今日存在新通知。</p>'
            echo '<ul>'
            echo '<li>报告日期: ${{ steps.date.outputs.date }}</li>'
            echo '<li>pipeline_exit_code: ${{ steps.run_python_script.outputs.exit_code }}</li>'
            echo '<li>source_error_count: ${{ steps.run_python_script.outputs.source_error_count }}</li>'
            echo '<li>failed_count: ${{ steps.run_python_script.outputs.failed_count }}</li>'
            echo '<li>workflow: <a href="${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}">查看 GitHub Actions 日志</a></li>'
            echo '</ul>'
            echo '<h3>Pipeline 输出</h3>'
            echo '<pre style="white-space:pre-wrap;background:#f6f8fa;border:1px solid #d0d7de;border-radius:6px;padding:12px;">'
            sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g' "${{ steps.run_python_script.outputs.log_path }}"
            echo '</pre>'
            echo '</body></html>'
          } > "$alert_file"
          echo "alert_path=$alert_file" >> "$GITHUB_OUTPUT"

      - name: Send operational alert email
        if: steps.run_python_script.outputs.source_error_count != '0' || steps.run_python_script.outputs.exit_code == '2'
        uses: dawidd6/action-send-mail@v3
        with:
          server_address: ${{ secrets.MAIL_SERVER_ADDRESS }}
          server_port: ${{ secrets.MAIL_SERVER_PORT }}
          secure: true
          username: ${{ secrets.MAIL_USERNAME }}
          password: ${{ secrets.MAIL_PASSWORD }}
          subject: '上海大学通知推送运行异常 - ${{ steps.date.outputs.date }} - 源站异常 ${{ steps.run_python_script.outputs.source_error_count }} 个'
          to: ${{ secrets.MAIL_TO }}
          from: ${{ secrets.MAIL_USERNAME }}
          html_body: file://${{ steps.prepare_alert.outputs.alert_path }}

      - name: Fail if notice pipeline errored
        if: steps.run_python_script.outputs.exit_code == '2'
        run: |
          echo "::error::Python 脚本执行失败，exit_code=${{ steps.run_python_script.outputs.exit_code }}。"
          exit 1
```

Keep the existing daily `Send Email` step guarded by `steps.check_file.outputs.found == 'true'`. The intended outcomes are:

- `exit_code=1, source_error_count=0`: no new notices, no email, workflow succeeds.
- `exit_code=1, source_error_count>0`: no daily notice email, operational alert email, workflow succeeds.
- `exit_code=0, source_error_count>0`: daily notice email plus operational alert email, workflow succeeds.
- `exit_code=2`: operational alert email, then workflow fails.

- [ ] **Step 9: Add CLI test for source error count**

Add to `tests/notice_push/test_cli.py`:

```python
def test_cli_prints_source_error_count_for_no_report(monkeypatch, tmp_path, capsys):
    class SourceErrorPipeline:
        def run(self, **kwargs):
            from src.notice_push.models import SourceError

            return PipelineResult(
                report_path=None,
                new_count=0,
                summarized_count=0,
                source_errors=(
                    SourceError(
                        source_id="shu_official",
                        source_name="上海大学官网",
                        url="https://www.shu.edu.cn/tzgg.htm",
                        reason="timeout",
                    ),
                ),
            )

    monkeypatch.setattr("src.notice_push.__main__.build_pipeline", lambda config, profile: SourceErrorPipeline())

    assert main(["--state-path", str(tmp_path / "state.sqlite3"), "--output-dir", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "new_count=0" in output
    assert "summarized_count=0" in output
    assert "failed_count=0" in output
    assert "source_error_count=1" in output
```

- [ ] **Step 10: Run focused tests**

Run:

```bash
conda run --no-capture-output -n spider pytest tests/notice_push/test_pipeline.py tests/notice_push/test_cli.py -q
```

Expected: PASS.

---

### Task 3: Update Seen Notice Detail Hash Without Resending

**Files:**
- Modify: `src/notice_push/storage.py`
- Modify: `src/notice_push/pipeline.py`
- Test: `tests/notice_push/test_storage.py`
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Add failing storage test**

Add to `tests/notice_push/test_storage.py`:

```python
def test_storage_updates_changed_seen_detail_without_resending(tmp_path):
    config = load_config(env={}, repo_root=tmp_path)
    storage = NoticeStorage(tmp_path / "state.sqlite3", config.sources)
    storage.initialize()
    item = make_item("shu_official", "https://example.com/detail.htm")
    notice_id = storage.upsert_seen_item(item)

    storage.save_detail(
        notice_id,
        NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            content="旧详情正文",
            published_at=item.published_at,
            list_excerpt=item.list_excerpt,
        ),
    )
    before = storage.get_notice(notice_id)

    changed = storage.update_seen_detail_if_changed(
        notice_id,
        NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            content="新详情正文",
            published_at=item.published_at,
            list_excerpt=item.list_excerpt,
        ),
    )

    after = storage.get_notice(notice_id)
    assert changed is True
    assert after["content"] == "新详情正文"
    assert after["content_hash"] != before["content_hash"]
    assert after["status"] == "updated_seen"
    assert after["summary"] == ""
```

- [ ] **Step 2: Run failing storage test**

Run:

```bash
conda run --no-capture-output -n spider pytest tests/notice_push/test_storage.py::test_storage_updates_changed_seen_detail_without_resending -q
```

Expected: FAIL because the method does not exist.

- [ ] **Step 3: Implement storage helper**

Add to `NoticeStorage`:

```python
def find_seen_items(self, items: Iterable[NoticeListItem]) -> dict[str, sqlite3.Row]:
    rows: dict[str, sqlite3.Row] = {}
    with self._connect() as conn:
        for item in items:
            row = conn.execute(
                "select * from notices where source_id = ? and canonical_url = ?",
                (item.source_id, item.canonical_url),
            ).fetchone()
            if row is not None:
                rows[item.canonical_url] = row
    return rows

def update_seen_detail_if_changed(self, notice_id: int, detail: NoticeDetail) -> bool:
    content_hash = hashlib.sha256(detail.content.encode("utf-8")).hexdigest()
    with self._connect() as conn:
        row = conn.execute("select content_hash from notices where id = ?", (notice_id,)).fetchone()
        if row is None:
            raise KeyError(notice_id)
        if row["content_hash"] == content_hash:
            return False
        conn.execute(
            """
            update notices set
                title = ?,
                content = ?,
                published_at = coalesce(?, published_at),
                list_excerpt = ?,
                content_hash = ?,
                detail_fetched_at = ?,
                status = 'updated_seen',
                summary = '',
                summary_model = '',
                summary_prompt_version = '',
                summary_generated_at = null,
                error_message = ''
            where id = ?
            """,
            (
                detail.title,
                detail.content,
                _dt(detail.published_at),
                detail.list_excerpt,
                content_hash,
                _now(),
                notice_id,
            ),
        )
    return True
```

- [ ] **Step 4: Add pipeline test for seen detail update**

Add to `tests/notice_push/test_pipeline.py`:

```python
def test_pipeline_updates_seen_notice_detail_hash_without_resummarizing(tmp_path):
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
    notice_id = storage.upsert_seen_item(item)
    storage.save_detail(
        notice_id,
        NoticeDetail(
            source_id=item.source_id,
            url=item.url,
            canonical_url=item.canonical_url,
            title=item.title,
            content="旧详情正文",
            published_at=item.published_at,
            list_excerpt=item.list_excerpt,
        ),
    )

    class ChangedDetailAdapter(FakeAdapter):
        def parse_detail(self, html, item):
            detail = super().parse_detail(html, item)
            return NoticeDetail(
                source_id=detail.source_id,
                url=detail.url,
                canonical_url=detail.canonical_url,
                title=detail.title,
                content="这是一段足够长的新详情页正文，用于更新已见通知的 content_hash。",
                published_at=detail.published_at,
                list_excerpt=detail.list_excerpt,
            )

    http = FakeHttp({source.list_url: "list-1", "https://example.com/detail-1.htm": "detail"})
    summarizer = FakeSummarizer()
    pipeline = NoticePipeline(
        config=config,
        storage=storage,
        http_client=http,
        summarizer=summarizer,
        adapter_factory=lambda selected_source: ChangedDetailAdapter(selected_source),
    )

    result = pipeline.run(
        source_ids=["shu_official"],
        dry_run=False,
        limit=1,
        max_pages_per_source=1,
        stop_after_seen_pages=1,
        report_date=date(2026, 6, 30),
    )

    row = storage.find_by_source_url("shu_official", item.canonical_url)
    assert result.new_count == 0
    assert result.report_path is None
    assert summarizer.details == []
    assert row["status"] == "updated_seen"
    assert "新详情页正文" in row["content"]
```

- [ ] **Step 5: Implement pipeline seen change check**

In `pipeline.run()`, after `candidate_items = ...`, get seen rows for non-dry runs:

```python
seen_rows = {} if dry_run else self.storage.find_seen_items(list_items)
```

After handling selected new items, but before paging onward, fetch detail for seen items only when they were not candidates:

```python
if not dry_run and seen_rows:
    seen_items = [item for item in list_items if item.canonical_url in seen_rows]
    self._update_seen_details_if_changed(source, adapter, seen_items, seen_rows, failures)
```

Add helper:

```python
def _update_seen_details_if_changed(
    self,
    source: NoticeSource,
    adapter,
    items: list[NoticeListItem],
    seen_rows: dict[str, object],
    failures: list[FailedNotice],
) -> None:
    for item in items:
        try:
            detail_html = self.http_client.get_text(item.url)
            detail = adapter.parse_detail(detail_html, item)
            if len(detail.content.strip()) < self.config.detail_min_chars:
                continue
            notice_id = int(seen_rows[item.canonical_url]["id"])
            self.storage.update_seen_detail_if_changed(notice_id, detail)
        except Exception:
            continue
```

Do not add failures for seen item refresh problems; this path is best-effort and should not create emails.

- [ ] **Step 6: Run focused tests**

Run:

```bash
conda run --no-capture-output -n spider pytest tests/notice_push/test_storage.py tests/notice_push/test_pipeline.py -q
```

Expected: PASS.

---

### Task 4: Workflow Config and Repository Hygiene

**Files:**
- Modify: `.github/workflows/daily_report.yml`
- Modify: `.gitignore`
- Test: `tests/notice_push/test_cli.py`

- [ ] **Step 1: Add useful Action env overrides while keeping YAML defaults**

In `.github/workflows/daily_report.yml`, add under `env:`:

```yaml
PROMPT_NAME: ${{ vars.PROMPT_NAME || 'notice_summary_v1' }}
SUMMARY_MAX_WORKERS: ${{ vars.SUMMARY_MAX_WORKERS || '3' }}
SOURCE_SHU_OFFICIAL_ENABLED: ${{ vars.SOURCE_SHU_OFFICIAL_ENABLED || 'true' }}
SOURCE_MANAGEMENT_SCHOOL_ENABLED: ${{ vars.SOURCE_MANAGEMENT_SCHOOL_ENABLED || 'true' }}
SOURCE_GRADUATE_SCHOOL_ENABLED: ${{ vars.SOURCE_GRADUATE_SCHOOL_ENABLED || 'true' }}
```

Do not put secrets in YAML. Keep `DEEPSEEK_API_KEY` in GitHub Secrets.

- [ ] **Step 2: Ignore IDE/tool directories**

Append to `.gitignore`:

```gitignore
.idea/
.trae/
```

- [ ] **Step 3: Run workflow-adjacent tests**

Run:

```bash
conda run --no-capture-output -n spider pytest tests/notice_push/test_config_models.py tests/notice_push/test_cli.py -q
```

Expected: PASS.

---

### Task 5: Final Verification

**Files:**
- No code edits unless verification reveals a concrete bug.

- [ ] **Step 1: Run all offline tests**

Run:

```bash
conda run --no-capture-output -n spider pytest tests -q
```

Expected: `57 passed` or more if tests were added.

- [ ] **Step 2: Run first dry-run smoke**

Run:

```bash
conda run --no-capture-output -n spider python -m src.notice_push --dry-run --limit 1 --max-pages-per-source 1
```

Expected:

```text
new_count=3
summarized_count=0
failed_count=0
source_error_count=0
```

- [ ] **Step 3: Run pagination dry-run smoke**

Run:

```bash
conda run --no-capture-output -n spider python -m src.notice_push --dry-run --max-pages-per-source 2 --limit 1
```

Expected:

```text
new_count=3
summarized_count=0
failed_count=0
source_error_count=0
```

- [ ] **Step 4: Run static checks for forbidden weather/API-key regressions**

Run:

```bash
rg -n "WEATHER|weather_city|from src.notice_push.weather|sk-" -S src tests resources/config .github .env.example
```

Expected: no project-code hits except harmless documentation/placeholders in `.env.example` if any.

- [ ] **Step 5: Summarize remaining known limitations**

Report whether real API smoke was skipped. If skipped, say exactly:

```text
Real API smoke was not run; default verification used offline tests and dry-run network crawl only.
```

---

## Approval Notes

This plan intentionally does not change the approved daily/backfill profile values unless tests reveal a hard failure:

- daily: pages `5`, detail workers `2`, summary workers `3`, HTTP delay `0.8`
- backfill: unbounded pages, detail workers `4`, summary workers `3`, HTTP delay `1.0`

Source outage behavior is now fixed by requirement:

- Pure source directory failures do **not** send the daily notice email.
- Pure source directory failures are logged via `source_error_count`.
- `source_error_count > 0` sends a separate operational alert email.
- Fatal pipeline failures send the operational alert email first, then fail the workflow.
