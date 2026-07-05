# Remaining Optimization Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the remaining optimization items from `docs/superpowers/reviews/2026-07-05-project-optimization-review.md` after the first batch fixes.

**Architecture:** Keep `src.notice_push` as the only supported runtime path. Improve SQLite write robustness, separate new-vs-retry report counts, make mixed text/video parsing prefer text, move parser constants into YAML config, remove old `src/spider` and `src/entry` compatibility code, and remove old `deepseek_model` compatibility.

**Tech Stack:** Python 3.12, pytest, sqlite3, PyYAML, GitHub Actions, conda environment `spider`.

---

## Scope

Implement:

- SQLite write lock plus WAL/busy timeout.
- `new_count`, `retried_count`, and `manual_review_count` reporting.
- mixed text/video page classification fix.
- configurable parsing rules for external video domains and noise image markers.
- removal of old `src/spider`, `src/entry`, and their tests.
- removal of `AppConfig.deepseek_model` and legacy top-level `deepseek_model` YAML compatibility.

Do not implement:

- video summarization.
- new source adapters.
- Git commit or GitHub push.
- any change to `resources/notice_records.csv`.

## Task 1: Harden SQLite Writes

**Files:**
- Modify: `src/notice_push/storage.py`
- Test: `tests/notice_push/test_storage.py`

- [ ] Add tests proving `NoticeStorage` has a shared write lock and sets `journal_mode=wal` plus `busy_timeout`.
- [ ] Implement `self._write_lock = threading.RLock()` in `NoticeStorage.__init__`.
- [ ] Wrap methods that mutate SQLite state with `with self._write_lock:`.
- [ ] In `_connect()`, after creating the connection, execute `pragma busy_timeout = 30000`.
- [ ] During `initialize()`, execute `pragma journal_mode = wal`.
- [ ] Run `conda run -n spider pytest tests/notice_push/test_storage.py -q`.

## Task 2: Split New And Retry Counts

**Files:**
- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/storage.py`
- Modify: `src/notice_push/pipeline.py`
- Modify: `src/notice_push/__main__.py`
- Modify: `.github/workflows/daily_report.yml`
- Test: `tests/notice_push/test_storage.py`
- Test: `tests/notice_push/test_pipeline.py`
- Test: `tests/notice_push/test_cli.py`

- [ ] Add `retried_count: int = 0` and `manual_review_count: int = 0` to `PipelineResult`.
- [ ] Add `NoticeStorage.split_processable_items(...) -> tuple[list[NoticeListItem], list[NoticeListItem]]`, returning first-seen items and retryable failed items separately.
- [ ] Keep `filter_processable_items()` as a compatibility helper inside `notice_push` tests if useful, but make pipeline use the split method.
- [ ] In `NoticePipeline.run()`, compute `new_count` from first-seen items only and `retried_count` from retryable failed items.
- [ ] Set `manual_review_count=len(failures)` in the returned result.
- [ ] Print `retried_count=` and `manual_review_count=` in CLI output.
- [ ] In GitHub Actions, parse both new outputs and pass `manual_review_count` as metadata; keep email subject based on `new_count`.
- [ ] Add tests where a retryable failed notice is processed again but `new_count == 0` and `retried_count == 1`.
- [ ] Run `conda run -n spider pytest tests/notice_push/test_storage.py tests/notice_push/test_pipeline.py tests/notice_push/test_cli.py -q`.

## Task 3: Prefer Text On Mixed Text/Video Pages

**Files:**
- Modify: `src/notice_push/html_utils.py`
- Test: `tests/notice_push/test_html_utils.py`

- [ ] Add a test for `infer_content_kind("有足够文字正文", (external_video_asset,)) == "text"`.
- [ ] Change `infer_content_kind()` to return text when substantive text exists and is not only an asset label.
- [ ] Keep empty video-only pages classified as `video`.
- [ ] Run `conda run -n spider pytest tests/notice_push/test_html_utils.py tests/notice_push/test_sources.py -q`.

## Task 4: Move Parser Constants Into YAML Config

**Files:**
- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/config.py`
- Modify: `src/notice_push/html_utils.py`
- Modify: `src/notice_push/__main__.py`
- Modify: `resources/config/runtime.yml`
- Test: `tests/notice_push/test_config_models.py`
- Test: `tests/notice_push/test_html_utils.py`

- [ ] Add `ParsingConfig` dataclass with `external_video_domains` and `noise_image_markers`.
- [ ] Add `parsing: ParsingConfig` to `AppConfig`.
- [ ] Load optional `parsing.external_video_domains` and `parsing.noise_image_markers` from `runtime.yml`, defaulting to current constants.
- [ ] Keep `html_utils` default constants, but add `configure_parsing(external_video_domains, noise_image_markers)`.
- [ ] Call `configure_parsing()` in `load_config()` or `build_pipeline()` after YAML parsing.
- [ ] Add YAML defaults in `resources/config/runtime.yml`.
- [ ] Test that YAML overrides are loaded and affect external video detection / noise image filtering.
- [ ] Run `conda run -n spider pytest tests/notice_push/test_config_models.py tests/notice_push/test_html_utils.py -q`.

## Task 5: Remove Old Entry And Spider Code

**Files:**
- Delete: `src/spider/`
- Delete: `src/entry/`
- Delete: `tests/spider/`
- Delete: `tests/entry/`
- Modify: `README.md` only if it references old entry points.

- [ ] Search for all `src.spider`, `src.entry`, `python -m src.spider`, `NoticeGetter`, `DeepSeekClient`, and `PageParser` references.
- [ ] Delete old source and test directories.
- [ ] Remove stale documentation references if any.
- [ ] Run `conda run -n spider pytest -q`; expected tests count drops because legacy tests are gone.

## Task 6: Remove Legacy DeepSeek Model Compatibility

**Files:**
- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/config.py`
- Modify: `tests/notice_push/test_config_models.py`
- Modify: `README.md` only if needed.

- [ ] Remove `AppConfig.deepseek_model`.
- [ ] Remove `deepseek_model` top-level YAML compatibility in `_llm_providers()`.
- [ ] Update config tests to assert the DeepSeek model lives only in `config.llm_providers["deepseek"].default_model`.
- [ ] Update any remaining code references to use `config.llm_providers["deepseek"].default_model`.
- [ ] Run `conda run -n spider pytest tests/notice_push/test_config_models.py -q`.

## Final Verification

- [ ] Run `conda run -n spider pytest -q`.
- [ ] Run `conda run -n spider python -m compileall -q src`.
- [ ] Run `git status --short`.
- [ ] Confirm no Git commit and no GitHub push were performed.
- [ ] Confirm `resources/notice_records.csv` remains unstaged and untouched by this plan.

