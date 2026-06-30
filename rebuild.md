# SHU-Notice-Push Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Rebuild the project into a source-adapter based notice crawler that supports Shanghai University official notices, Management School notices, and Graduate School notices, with SQLite-backed state, maintainable prompts, and improved email reports.

**Architecture:** Replace the current hard-coded spider with a small pipeline: load source configs, paginate directory pages, collect notice detail URLs, parse detail pages, persist crawl state in SQLite, summarize detail-page bodies through a pluggable LLM service, render a daily Markdown/HTML report, and let GitHub Actions send the email. Each notification source owns only its list/detail/pagination parsing rules; shared concerns such as HTTP, deduplication, persistence, summarization, and rendering live in common services.

**Tech Stack:** Python 3.12, `requests`, `beautifulsoup4`, `sqlite3`, `openai`, `python-dotenv`, `pytest`, GitHub Actions, `pandoc`. All local testing and running must use the conda environment named `spider`. Real API keys may be used for opt-in live smoke tests, but those tests must write only to temporary state/output paths and must not mutate production data under `resources/`.

---

## Current Findings

- `src/spider/Spider.py` previously coordinated every step, wrote Markdown, mixed in unrelated weather logic, and used `ProcessPoolExecutor` for LLM summaries.
- `src/spider/notice_getter.py` only supports `https://www.shu.edu.cn/tzgg.htm` and writes dedup state directly to `resources/notice_records.csv`.
- `src/spider/page_parser.py` assumes detail pages have `h1[align=center]`, `.v_news_content`, and `.xx[align=center]`.
- `src/spider/deepseek.py` initializes the DeepSeek client at import time and loads a single prompt file from `resources/system_prompt.md`.
- Existing tests depend on live websites, mutate real state, and `tests/spider/test_deepseek.py` contains a hard-coded API key. This must be removed during the rebuild.
- GitHub Actions sends email from rendered Markdown via `dawidd6/action-send-mail@v3`; Python currently does not send mail directly.

## Target File Structure

- Create `src/notice_push/config.py`: environment loading, source loading, runtime paths, test/live-smoke path overrides, model settings, concurrency settings.
- Create `src/notice_push/models.py`: dataclasses for `NoticeSource`, `NoticeListItem`, `NoticeDetail`, `NoticeSummary`, and `PipelineResult`.
- Create `src/notice_push/http.py`: shared HTTP session with timeout, retry, user-agent, encoding handling, and URL normalization.
- Create `src/notice_push/sources/base.py`: `NoticeSourceAdapter` protocol with `parse_list_page()`, `find_next_page_url()`, and `parse_detail()` methods.
- Create `src/notice_push/sources/shu_official.py`: adapter for `https://www.shu.edu.cn/tzgg.htm`.
- Create `src/notice_push/sources/management_school.py`: adapter for `https://ms.shu.edu.cn/syzl/zytz.htm`.
- Create `src/notice_push/sources/graduate_school.py`: adapter for `https://gs.shu.edu.cn/xwlb/sy.htm`.
- Create `src/notice_push/storage.py`: SQLite schema creation, CSV migration, deduplication, crawl status, and summary persistence.
- Create `src/notice_push/summarizer.py`: DeepSeek/OpenAI-compatible client wrapper, prompt rendering, retry, and test-friendly dependency injection.
- Create `src/notice_push/report.py`: Markdown and email HTML rendering, source grouping, run summary, and failure section rendering.
- Create `src/notice_push/pipeline.py`: orchestration for list fetch, SQLite dedup, detail parsing, summarization, persistence, and report generation.
- Create `src/notice_push/__main__.py`: CLI entrypoint used by local runs and GitHub Actions.
- Do not include weather logic in the rebuilt notice pipeline; this project only crawls, summarizes, and pushes notices.
- Keep `src/entry/notice.py`, `src/spider/Spider.py`, `src/spider/notice_getter.py`, `src/spider/page_parser.py`, and `src/spider/deepseek.py` only as temporary compatibility shims during migration, then remove them after tests and workflow use the new package.

## SQLite Design

- Store runtime state in `resources/notice_state.sqlite3`.
- Production runs use `resources/notice_state.sqlite3`; unit tests and live API smoke tests must override the state path with a temporary database.
- Create table `sources` with `id`, `name`, `base_url`, `list_url`, `enabled`, `adapter`, `created_at`, and `updated_at`.
- Create table `notices` with `id`, `source_id`, `url`, `canonical_url`, `title`, `list_excerpt`, `content`, `published_at`, `first_seen_at`, `last_seen_at`, `content_hash`, `status`, `summary`, `summary_model`, `summary_prompt_version`, `summary_generated_at`, `detail_fetched_at`, and `error_message`.
- Create a unique index on `(source_id, canonical_url)` and a secondary index on `(published_at, first_seen_at)`.
- On first run, migrate existing `resources/notice_records.csv` rows into `notices` with source `shu_official`, `status='seen_legacy'`, empty content, and `first_seen_at` set to migration time.
- After migration, stop writing `resources/notice_records.csv`; keep it as an import artifact and update GitHub Actions to commit `resources/notice_state.sqlite3`.
- Treat a notice as new when `(source_id, canonical_url)` is absent. If a seen notice has changed title/content hash, update `last_seen_at` and `content_hash`, but do not resend unless a future config flag enables change notifications.
- For newly added sources, support a bootstrap mode that paginates directory pages and records existing notices as `seen_baseline` without detail parsing or summarization, preventing a first run from emailing hundreds of historical notices.

## Source Parsing Rules

- Directory pages are discovery pages only. They may provide title/date/list excerpt, but the summarizer must never summarize directory-page snippets as if they were notification content.
- Every new notice must fetch its detail URL and summarize the cleaned detail body. If the detail body cannot be fetched or is empty after cleanup, mark the notice as failed and include it in the report's manual-review section instead of sending a model summary based on directory metadata.
- All source adapters must expose pagination by parsing the current list page's `下页` link. The pipeline follows that link until there is no next page, `MAX_PAGES_PER_SOURCE` is reached, or the configured stop-after-seen rule fires.
- `shu_official` list parsing:
  - List page: `https://www.shu.edu.cn/tzgg.htm`
  - Pagination: first page is `tzgg.htm`; current observed next page is `https://www.shu.edu.cn/tzgg/123.htm`; tail page is `https://www.shu.edu.cn/tzgg/1.htm`; prefer parsing the `下页` anchor over constructing URLs.
  - Items: `.ej_main ul li a[href]`
  - Title: `.bt`
  - List excerpt: `.zy`
  - Published date: `.sj`, format `%Y.%m.%d`
  - Detail content: `.v_news_content`
  - Detail date fallback: `.xx` text matching `发布时间：YYYY-MM-DD`
- `management_school` list parsing:
  - List page: `https://ms.shu.edu.cn/syzl/zytz.htm`
  - Pagination: first page is `zytz.htm`; current observed next page is `https://ms.shu.edu.cn/syzl/zytz/52.htm`; tail page is `https://ms.shu.edu.cn/syzl/zytz/1.htm`; page text currently shows `共1043条 1/53`.
  - Items: `table.ArtList`
  - Title: `a.linkfont1[title]`, fallback to anchor text
  - Published date: `span.linkfont1`, format `%Y-%m-%d`
  - Detail content: `.v_news_content`
  - Detail title fallback: `#HRCMS_ctr13929_CalendarDetail_lblTitle`
  - Detail date fallback: text matching `创建时间： YYYY-MM-DD`
- `graduate_school` list parsing:
  - List page: `https://gs.shu.edu.cn/xwlb/sy.htm`
  - Pagination: first page is `sy.htm`; current observed next page is `https://gs.shu.edu.cn/xwlb/sy/6.htm`; tail page is `https://gs.shu.edu.cn/xwlb/sy/1.htm`; page text currently shows `共126条 首页上页12345...7下页尾页`.
  - Items: `tr[id^="line_u17_"]`
  - Title: first `a[href]` text
  - Published datetime: second `td` text, format `%Y/%m/%d %H:%M:%S`
  - Detail content: `#vsb_content .v_news_content`, fallback `.v_news_content`
  - Detail date fallback: text matching `时间: YYYY年MM月DD日 HH:MM`
  - Attachment links: anchors near the detail content whose text contains `附件` or whose URL ends with document/archive extensions.
- For all sources, normalize relative URLs with the list page URL, preserve external URLs, strip navigation/footer text, remove `<script>` and `<style>` nodes before extracting detail content, and keep list title/date when detail parsing cannot improve them.

## Pagination and Detail Fetching Design

- Add config defaults: `MAX_PAGES_PER_SOURCE=3`, `STOP_AFTER_SEEN_PAGES=2`, and `DETAIL_MIN_CHARS=30`.
- The scheduled run should fetch pages newest-first. For each page, parse directory items, deduplicate by `(source_id, canonical_url)`, and fetch detail pages only for new items that will be summarized.
- Stop paginating a source when either no `下页` link exists, `MAX_PAGES_PER_SOURCE` pages have been scanned, or `STOP_AFTER_SEEN_PAGES` consecutive pages contain no new notices.
- Add CLI flags `--max-pages-per-source`, `--stop-after-seen-pages`, and `--bootstrap-seen`. `--bootstrap-seen` records existing directory items as already seen and must not call the LLM.
- Full historical backfill is opt-in by setting a high `--max-pages-per-source` together with `--bootstrap-seen`; normal scheduled runs should avoid crawling every historical page.
- `list_excerpt` is retained for context and debugging only. The prompt input's `content` field must come from detail-page extraction.

## Prompt and LLM Design

- Replace `resources/system_prompt.md` with versioned prompts under `resources/prompts/`.
- Create `resources/prompts/notice_summary_v1.md` as the initial default prompt.
- Add `PROMPT_NAME=notice_summary_v1` and `DEEPSEEK_MODEL` support in config; the prompt version must be stored with each generated summary.
- Prompt input must include `source_name`, `title`, `published_at`, `url`, `attachments`, `list_excerpt`, and cleaned detail-page `content`.
- Require the model to output compact Markdown using this schema:

```markdown
## [来源]|[通知类型]|[紧急度]|[标题]
- **发布时间**: ...
- **影响对象**: ...
- **核心信息**: ...
- **行动指引**: ...
- **截止时间**: ...
- **相关链接**: ...
```

- Prompt should prefer actionable extraction over long rewriting, explicitly preserve deadlines, locations, contacts, attachment names, and original URLs, and mark missing fields as `未提及`.
- `summarizer.py` must lazy-initialize the API client so importing tests never requires `DEEPSEEK_API_KEY`.
- Unit tests must use fake clients. A real `DEEPSEEK_API_KEY` may be used only in explicit smoke-test commands that also pass temporary state and output paths.
- Use `ThreadPoolExecutor` for LLM calls, because API calls are network I/O; default concurrency should be `SUMMARY_MAX_WORKERS=5`.

## Report and Email Design

- Generate Markdown at `resources/results/YYYY-MM-DD.md` as today.
- Render sections in this order: run summary, source-grouped summarized notices, failed notices needing manual review.
- The run summary should include total new notices, count by source, and count of failed detail/summary operations.
- For each successfully summarized notice, include the LLM summary, source name, original detail URL, and attachment links.
- For each failed notice, include source name, title, original detail URL, list date, and the failure reason; do not include an LLM summary generated from directory text.
- Generate HTML at `resources/results/html/YYYY-MM-DD.html` locally in GitHub Actions with `pandoc`, preserving the existing mail action.
- Improve email subject to `上海大学通知汇总 - YYYY-MM-DD - 新增 N 条`.
- If no new notices are found, exit with code `1` to keep the existing workflow skip behavior, but log a clear message and do not create an empty report.
- If some sources fail but at least one notice succeeds, exit with code `0`, include failures in the report, and send the email.

## Implementation Tasks

### Task 1: Baseline Safety and Secret Cleanup

**Files:**
- Modify: `tests/spider/test_deepseek.py`
- Modify: `.gitignore`
- Create: `tests/fixtures/`

- [ ] Remove the hard-coded DeepSeek API key from `tests/spider/test_deepseek.py`.
- [ ] Replace live LLM tests with a fake client that returns deterministic Markdown.
- [ ] Add `.env`, `__pycache__/`, `.pytest_cache/`, `.playwright-mcp/`, `.tmp/`, and `resources/results/html/` to `.gitignore`.
- [ ] Run: `conda run -n spider pytest tests -q`
- [ ] Expected: tests no longer require real API credentials.

### Task 2: Add Core Package and Models

**Files:**
- Create: `src/notice_push/__init__.py`
- Create: `src/notice_push/models.py`
- Create: `src/notice_push/config.py`

- [ ] Define immutable dataclasses for source config, list items, details, summaries, attachments, and pipeline results.
- [ ] Add runtime config loading from environment variables and explicit defaults.
- [ ] Add explicit overrides for `state_path` and `output_dir` so tests and live smoke runs can avoid real project data.
- [ ] Keep paths relative to the repository root, not the current working directory.
- [ ] Run: `conda run -n spider pytest tests -q`
- [ ] Expected: existing tests still pass or only fail where imports intentionally move in later tasks.

### Task 3: Build HTTP and HTML Utilities

**Files:**
- Create: `src/notice_push/http.py`
- Create: `src/notice_push/html_utils.py`
- Test: `tests/notice_push/test_html_utils.py`

- [ ] Add `HttpClient.get_text(url)` with timeout, user-agent, encoding fallback, and `raise_for_status()`.
- [ ] Add utilities for `absolute_url()`, `clean_text()`, `extract_text_blocks()`, `remove_noise_nodes()`, and date parsing.
- [ ] Test URL normalization, text cleanup, Chinese date parsing, slash date parsing, dot date parsing, and missing date behavior.
- [ ] Run: `conda run -n spider pytest tests/notice_push/test_html_utils.py -q`
- [ ] Expected: utility tests pass without network.

### Task 4: Implement Source Adapters

**Files:**
- Create: `src/notice_push/sources/base.py`
- Create: `src/notice_push/sources/shu_official.py`
- Create: `src/notice_push/sources/management_school.py`
- Create: `src/notice_push/sources/graduate_school.py`
- Create: `tests/fixtures/source_pages/`
- Test: `tests/notice_push/test_sources.py`

- [ ] Save representative list/detail HTML fixtures for all three sources from the current observed templates.
- [ ] Implement each adapter against the list, detail, and pagination parsing rules in this plan.
- [ ] Ensure adapters return list metadata even when detail pages are unavailable.
- [ ] Test each adapter with fixtures for list count, title, URL normalization, published date, next-page URL extraction, content extraction, and attachment extraction.
- [ ] Test that detail extraction removes directory/navigation/footer text and returns the actual notification body.
- [ ] Run: `conda run -n spider pytest tests/notice_push/test_sources.py -q`
- [ ] Expected: all source tests pass without live network.

### Task 5: Replace CSV State With SQLite

**Files:**
- Create: `src/notice_push/storage.py`
- Test: `tests/notice_push/test_storage.py`

- [ ] Create the SQLite schema on startup if missing.
- [ ] Insert the three source records with stable IDs: `shu_official`, `management_school`, `graduate_school`.
- [ ] Implement CSV migration from `resources/notice_records.csv` into SQLite.
- [ ] Implement `filter_new_items()`, `upsert_seen_item()`, `save_detail()`, `save_summary()`, `mark_failed()`, and `mark_seen_baseline()`.
- [ ] Test deduplication per source, same URL across different sources, CSV migration, bootstrap baseline status, and failed status persistence with a temporary database.
- [ ] Run: `conda run -n spider pytest tests/notice_push/test_storage.py -q`
- [ ] Expected: storage tests pass and do not touch the real `resources/notice_state.sqlite3`.

### Task 6: Refactor LLM Summarization

**Files:**
- Create: `src/notice_push/summarizer.py`
- Create: `resources/prompts/notice_summary_v1.md`
- Test: `tests/notice_push/test_summarizer.py`

- [ ] Move prompt text into `resources/prompts/notice_summary_v1.md`.
- [ ] Load prompts by name from config.
- [ ] Lazy-initialize the OpenAI-compatible client only when a real summary call is made.
- [ ] Add retry for transient API exceptions and store the final failure message for reporting.
- [ ] Test prompt rendering, prompt file missing errors, fake-client summary generation, and missing API key behavior.
- [ ] Test that prompt rendering uses `NoticeDetail.content` and never substitutes `NoticeListItem.list_excerpt` for missing detail content.
- [ ] Keep real API calls out of unit tests; put optional real-key verification in Task 10 only.
- [ ] Run: `conda run -n spider pytest tests/notice_push/test_summarizer.py -q`
- [ ] Expected: summarizer tests pass without real network or API key.

### Task 7: Build Report Rendering

**Files:**
- Create: `src/notice_push/report.py`
- Test: `tests/notice_push/test_report.py`

- [ ] Render source-grouped Markdown with run summary, summaries, attachments, and failures.
- [ ] Keep output path `resources/results/YYYY-MM-DD.md`.
- [ ] Test report output for multiple sources, failed notices, attachments, and no-new-notice behavior.
- [ ] Run: `conda run -n spider pytest tests/notice_push/test_report.py -q`
- [ ] Expected: report tests pass without network.

### Task 8: Build Pipeline and CLI

**Files:**
- Create: `src/notice_push/pipeline.py`
- Create: `src/notice_push/__main__.py`
- Modify: `src/spider/Spider.py`

- [ ] Orchestrate enabled sources, paginated directory crawling, SQLite deduplication, detail parsing, LLM summarization, report generation, and exit codes.
- [ ] Keep `python -m src.spider.Spider` as a compatibility wrapper that calls `src.notice_push.__main__`.
- [ ] Add CLI flags: `--source`, `--all-sources`, `--dry-run`, `--limit`, `--date`, `--state-path`, `--output-dir`, `--max-pages-per-source`, `--stop-after-seen-pages`, and `--bootstrap-seen`.
- [ ] Ensure `--dry-run` fetches/parses but does not write SQLite or reports.
- [ ] Ensure `--state-path` and `--output-dir` override production paths for isolated tests and smoke runs.
- [ ] Ensure `--bootstrap-seen` paginates and writes baseline records without fetching detail pages, generating summaries, or creating reports.
- [ ] Run: `conda run -n spider python -m src.notice_push --dry-run --limit 1`
- [ ] Expected: command fetches at most one item per source and does not mutate state.
- [ ] Run: `conda run -n spider python -m src.notice_push --dry-run --max-pages-per-source 2 --limit 1`
- [ ] Expected: command follows second-page URLs where present, but still summarizes nothing and mutates no state.
- [ ] Run: `conda run -n spider pytest tests -q`
- [ ] Expected: unit tests pass.

### Task 9: Update GitHub Actions

**Files:**
- Modify: `.github/workflows/daily_report.yml`
- Modify: `.env.example`

- [ ] Replace `python -m src.spider.Spider` with `python -m src.notice_push`.
- [ ] Commit `resources/notice_state.sqlite3` and `resources/results`, excluding `resources/results/html`.
- [ ] Keep `pandoc` HTML rendering and `dawidd6/action-send-mail@v3`.
- [ ] Set email subject to include the new notice count from pipeline output.
- [ ] Add environment variables for `PROMPT_NAME`, `SUMMARY_MAX_WORKERS`, and per-source enable flags.
- [ ] Run locally: `conda run -n spider pytest tests -q`
- [ ] Expected: workflow changes are syntax-level safe and tests pass.

### Task 10: Migration Verification and Live Smoke Test

**Files:**
- Modify only if verification reveals a concrete defect.

- [ ] Run: `conda run -n spider pytest tests -q`
- [ ] Run: `conda run -n spider python -m src.notice_push --dry-run --limit 2`
- [ ] Run: `conda run -n spider python -m src.notice_push --dry-run --max-pages-per-source 2 --limit 1`
- [ ] Before any real-key smoke run, capture the current production state checksum if it exists: `conda run -n spider python -c "from pathlib import Path; import hashlib; p=Path('resources/notice_state.sqlite3'); print(hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else 'missing')"`
- [ ] Run with real credentials only when `.env` has `DEEPSEEK_API_KEY`, using isolated paths: `conda run -n spider python -m src.notice_push --limit 1 --state-path .tmp/live-smoke/notice_state.sqlite3 --output-dir .tmp/live-smoke/results`
- [ ] Verify the real-key smoke summary is based on detail-page body text by comparing the generated report with the fetched detail content, not the directory snippet.
- [ ] Verify `.tmp/live-smoke/notice_state.sqlite3` contains source rows, new notice rows, and summary metadata.
- [ ] Verify `.tmp/live-smoke/results/YYYY-MM-DD.md` groups notices by source and includes run summary, original links, and failures if any.
- [ ] Recompute the production state checksum and verify `resources/notice_state.sqlite3`, `resources/results/`, and `resources/notice_records.csv` were not changed by the smoke run.

## Acceptance Criteria

- The project can fetch and summarize notices from all three configured sources.
- The project follows pagination for each directory source and has configurable page/seen stop limits.
- LLM summaries are generated only from fetched detail-page bodies, never from directory-page snippets.
- Adding a fourth source requires adding a new adapter and one source config entry, without changing storage, summarizer, report, or pipeline code.
- Prompt updates are file-based and versioned; generated summaries record the prompt version.
- The system uses SQLite for deduplication and summary state, with one-time migration from the existing CSV.
- Unit tests run offline with `conda run -n spider pytest tests -q`.
- Local smoke runs use `conda run -n spider python -m src.notice_push ...`.
- Real API smoke tests are allowed only with `--state-path .tmp/...` and `--output-dir .tmp/...`, so production SQLite, CSV, and report files remain unchanged.
- GitHub Actions still skips email when there are no new notices and sends email when there is at least one new notice.
- No source code or tests contain real API keys.

## Implementation Notes

- Prefer `ThreadPoolExecutor` over `ProcessPoolExecutor` for summary calls.
- Do not overwrite useful list metadata with empty detail parser results.
- Do not call the LLM when detail content is missing or shorter than `DETAIL_MIN_CHARS`; mark the notice failed for manual review.
- Use parsed `下页` links as the primary pagination mechanism because all three observed sites use reverse page IDs.
- Keep external links from the Graduate School list; if detail parsing fails, report the title, source, original URL, and failure reason.
- Keep live-network tests separate from unit tests. Unit tests should use fixtures and temporary SQLite databases.
- Never use a real API key in default test runs. Real-key checks must be explicit, isolated under `.tmp/live-smoke/`, and verified against production file checksums.
- Commit generated `resources/notice_state.sqlite3` in GitHub Actions because the repository is currently the only persistent state between scheduled runs.
