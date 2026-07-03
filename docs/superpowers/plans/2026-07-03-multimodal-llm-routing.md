# Multimodal LLM Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support notice summaries whose main body is text, PDF, or image, and classify video-body notices as explicitly unsupported instead of incorrectly failing them as empty detail content.

**Architecture:** Split detail parsing into text extraction plus content asset detection, then route summarization by content type. Text notices continue to use DeepSeek; PDF and image notices use Kimi K2.7 Code through the OpenAI-compatible Moonshot API; video notices are recorded for manual review with a clear unsupported reason.

**Tech Stack:** Python, BeautifulSoup, OpenAI SDK, SQLite, pytest, GitHub Actions, `resources/config/runtime.yml`.

---

## Development Workflow

This work must be developed on a dedicated feature branch, pushed incrementally to GitHub, and kept separate from `main` until the user approves the finished result.

- Before implementation, inspect the current branch and working tree. Do not start feature work on `main` or `master`.
- Create and switch to a feature branch named `feature/multimodal-llm-routing`.
- Preserve unrelated local changes. At the time this plan was written, `resources/notice_records.csv` may contain unrelated local changes and must not be reverted or included unless the user explicitly asks.
- Use TDD for behavior changes: write the failing test, verify it fails for the expected reason, implement the smallest passing change, then verify it passes.
- Treat a "feature" as a user-visible or architecture-visible capability, not as every small checklist step. After each feature below is complete and verified, commit and push it to the remote feature branch.
- Commit and push checkpoints:
  - Feature 1: content asset model, detail validation, and unsupported video classification.
  - Feature 2: source adapter asset extraction for PDF/image/video bodies.
  - Feature 3: YAML-driven multi-provider LLM configuration.
  - Feature 4: routed DeepSeek/Kimi summarization and media handling.
  - Feature 5: CLI, GitHub Actions, README, and final verification.
- Push command for each checkpoint:

```powershell
git push -u MAIN feature/multimodal-llm-routing
```

Use `git push` after the upstream branch exists.

- After all tasks pass verification, stop on `feature/multimodal-llm-routing` and ask the user to review. Do not merge, rebase onto `main`, squash, force-push, or open a destructive history rewrite unless the user explicitly approves that final integration action.
- If the user approves integration, use `superpowers:finishing-a-development-branch` and present merge/rebase/PR options before doing anything to `main`.

## Context

The current pipeline treats a notice detail as failed when `len(detail.content.strip()) < detail_min_chars`. This is correct for truly empty text pages, but wrong for notices whose real body is a PDF or image. The examples from `resources/results/2026-07-03.md` show this:

- PDF body: `https://ms.shu.edu.cn/info/1245/91745.htm`
- PDF body: `https://gs.shu.edu.cn/info/1029/172562.htm`
- Image body: `https://ms.shu.edu.cn/info/1245/91475.htm`
- Video body: `https://www.kankanews.com/detail/dZ2e81vaawR`

The implementation must stop using "short text" as the only definition of detail failure. It must decide whether a page has any supported summarizable body: text, PDF, or image. Video is out of scope for this round and should be classified as unsupported.

Official Kimi references checked while preparing this plan:

- `https://platform.kimi.com/docs/guide/start-using-kimi-api`
- `https://platform.kimi.com/docs/guide/kimi-k2-7-code-quickstart`
- `https://platform.kimi.com/docs/guide/use-kimi-vision-model`
- `https://platform.kimi.com/docs/api/files-upload`
- `https://platform.kimi.com/docs/api/files-content`

## File Structure

- Modify `src/notice_push/models.py`: add content asset models and keep backward compatibility with existing `Attachment`.
- Modify `src/notice_push/html_utils.py`: add reusable PDF/image/video asset extraction helpers.
- Modify source adapters under `src/notice_push/sources/`: populate assets from detail pages.
- Create `src/notice_push/llm.py`: OpenAI-compatible provider config/client helpers.
- Create `src/notice_push/media.py`: temporary media download, MIME detection, base64 conversion, and Kimi file cleanup helpers.
- Modify `src/notice_push/summarizer.py`: split text summarization from routed multimodal summarization.
- Modify `src/notice_push/config.py` and `resources/config/runtime.yml`: move LLM provider/routing config into YAML while keeping API keys and model overrides in environment variables.
- Modify `src/notice_push/pipeline.py`: replace text-length-only validation with supported-content validation and clear unsupported failure classification.
- Modify `.github/workflows/daily_report.yml`, `.env.example`, and `README.md`: document and pass Kimi secrets/config.
- Add or update tests under `tests/notice_push/` and fixtures under `tests/fixtures/source_pages/`.

## Task 1: Add Content Asset Model And Summarizable Detail Rules

**Files:**
- Modify: `src/notice_push/models.py`
- Modify: `src/notice_push/pipeline.py`
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Write failing tests for supported media details**

Add tests that prove PDF/image details are accepted even when text is short, while empty details still fail.

```python
from src.notice_push.models import NoticeAsset, NoticeDetail
from src.notice_push.pipeline import is_summarizable_detail


def test_pdf_detail_is_summarizable_even_when_text_is_short():
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
                url="https://ms.shu.edu.cn/__local/report.pdf",
                mime_type="application/pdf",
            ),
        ),
        content_kind="pdf",
    )

    assert is_summarizable_detail(detail, min_chars=30)


def test_image_detail_is_summarizable_even_when_text_is_short():
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

    assert is_summarizable_detail(detail, min_chars=30)


def test_empty_detail_without_supported_assets_is_not_summarizable():
    detail = NoticeDetail(
        source_id="graduate_school",
        url="https://gs.shu.edu.cn/info/1029/empty.htm",
        canonical_url="https://gs.shu.edu.cn/info/1029/empty.htm",
        title="空详情",
        content="",
    )

    assert not is_summarizable_detail(detail, min_chars=30)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
conda run -n spider pytest tests/notice_push/test_pipeline.py -q
```

Expected: fail because `NoticeAsset`, `assets`, `content_kind`, or `is_summarizable_detail` does not exist yet.

- [ ] **Step 3: Implement model additions**

In `src/notice_push/models.py`, add:

```python
@dataclass(frozen=True)
class NoticeAsset:
    kind: str
    role: str
    name: str
    url: str
    mime_type: str = ""
```

Update `NoticeDetail`:

```python
@dataclass(frozen=True)
class NoticeDetail:
    source_id: str
    url: str
    canonical_url: str
    title: str
    content: str
    published_at: Optional[datetime] = None
    list_excerpt: str = ""
    attachments: tuple[Attachment, ...] = field(default_factory=tuple)
    assets: tuple[NoticeAsset, ...] = field(default_factory=tuple)
    content_kind: str = "text"
```

- [ ] **Step 4: Implement supported-content helper**

In `src/notice_push/pipeline.py`, add:

```python
SUPPORTED_ASSET_KINDS = {"pdf", "image"}
SUPPORTED_ASSET_ROLES = {"primary", "attachment"}


def is_summarizable_detail(detail: NoticeDetail, min_chars: int) -> bool:
    if len(detail.content.strip()) >= min_chars:
        return True
    return any(
        asset.kind in SUPPORTED_ASSET_KINDS and asset.role in SUPPORTED_ASSET_ROLES
        for asset in detail.assets
    )
```

- [ ] **Step 5: Replace detail validation in pipeline**

Replace:

```python
if len(detail.content.strip()) < self.config.detail_min_chars:
    raise ValueError("detail content is empty or too short")
```

with:

```python
if not is_summarizable_detail(detail, self.config.detail_min_chars):
    if detail.content_kind in {"video", "external_video"}:
        raise UnsupportedContentError("unsupported video content")
    raise ValueError("detail content is empty or too short")
```

Also define:

```python
class UnsupportedContentError(ValueError):
    pass
```

- [ ] **Step 6: Run tests and verify pass**

Run:

```powershell
conda run -n spider pytest tests/notice_push/test_pipeline.py -q
```

Expected: the new tests pass.

- [ ] **Step 7: Commit and push Feature 1**

Run:

```powershell
git status --short
git add src/notice_push/models.py src/notice_push/pipeline.py tests/notice_push/test_pipeline.py
git commit -m "feat: classify multimodal notice details"
git push -u MAIN feature/multimodal-llm-routing
```

Expected: commit contains only Feature 1 files and the remote feature branch is updated.

## Task 2: Extract PDF, Image, And Video Assets From Detail HTML

**Files:**
- Modify: `src/notice_push/html_utils.py`
- Modify: `src/notice_push/sources/management_school.py`
- Modify: `src/notice_push/sources/graduate_school.py`
- Modify: `src/notice_push/sources/shu_official.py`
- Test: `tests/notice_push/test_sources.py`
- Add fixtures: `tests/fixtures/source_pages/management_school_pdf_detail.html`
- Add fixtures: `tests/fixtures/source_pages/management_school_image_detail.html`

- [ ] **Step 1: Add source fixture tests**

Add tests that parse representative PDF and image detail pages:

```python
def test_management_school_extracts_pdf_asset():
    html = fixture_text("source_pages/management_school_pdf_detail.html")
    source = NoticeSource(
        id="management_school",
        name="上海大学管理学院",
        base_url="https://ms.shu.edu.cn/",
        list_url="https://ms.shu.edu.cn/syzl/zytz.htm",
        adapter="src.notice_push.sources.management_school.ManagementSchoolAdapter",
    )
    item = NoticeListItem(
        source_id=source.id,
        url="https://ms.shu.edu.cn/info/1245/91745.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91745.htm",
        title="巡察公告",
    )

    detail = ManagementSchoolAdapter(source).parse_detail(html, item)

    assert detail.content_kind == "pdf"
    assert any(asset.kind == "pdf" for asset in detail.assets)


def test_management_school_extracts_image_asset():
    html = fixture_text("source_pages/management_school_image_detail.html")
    source = NoticeSource(
        id="management_school",
        name="上海大学管理学院",
        base_url="https://ms.shu.edu.cn/",
        list_url="https://ms.shu.edu.cn/syzl/zytz.htm",
        adapter="src.notice_push.sources.management_school.ManagementSchoolAdapter",
    )
    item = NoticeListItem(
        source_id=source.id,
        url="https://ms.shu.edu.cn/info/1245/91475.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91475.htm",
        title="管理学院2026年寒假值班安排",
    )

    detail = ManagementSchoolAdapter(source).parse_detail(html, item)

    assert detail.content_kind == "image"
    assert any(asset.kind == "image" for asset in detail.assets)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
conda run -n spider pytest tests/notice_push/test_sources.py -q
```

Expected: fail because assets are not extracted.

- [ ] **Step 3: Implement generic asset extraction helpers**

In `src/notice_push/html_utils.py`, add helpers:

```python
DOCUMENT_EXTENSIONS = {
    ".pdf": ("pdf", "application/pdf"),
    ".doc": ("file", "application/msword"),
    ".docx": ("file", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".xls": ("file", "application/vnd.ms-excel"),
    ".xlsx": ("file", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
}
IMAGE_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
VIDEO_EXTENSIONS = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}
EXTERNAL_VIDEO_DOMAINS = ("kankanews.com",)
```

Add functions:

```python
def extract_assets(root: Tag, page_url: str) -> tuple[NoticeAsset, ...]:
    assets: list[NoticeAsset] = []
    assets.extend(extract_link_assets(root, page_url))
    assets.extend(extract_image_assets(root, page_url))
    assets.extend(extract_video_assets(root, page_url))
    return tuple(_dedupe_assets(assets))
```

The implementation should:

- resolve URLs with `absolute_url`.
- mark PDFs as `kind="pdf"`, `role="attachment"` unless they are the only meaningful body, where adapters may later treat them as primary by `content_kind`.
- mark images as `kind="image"`, `role="primary"` when inside main content.
- ignore image URLs containing `logo`, `icon`, `wx`, `weixin`, `qr`, `blank`, `spacer`.
- mark videos and external video links as `kind="video"` or `kind="external_video"`.

- [ ] **Step 4: Update source adapters**

In each adapter `parse_detail`, after `content_node` is selected:

```python
assets = extract_assets(content_node, item.url) if content_node else ()
content_kind = infer_content_kind(content, assets)
```

Return:

```python
NoticeDetail(
    ...,
    content=content,
    attachments=attachments,
    assets=assets,
    content_kind=content_kind,
)
```

For `GraduateSchoolAdapter`, preserve the existing `_extract_attachments` behavior and ensure PDF attachments also appear in `assets`.

- [ ] **Step 5: Add content-kind inference helper**

In `html_utils.py`, add:

```python
def infer_content_kind(content: str, assets: tuple[NoticeAsset, ...]) -> str:
    if content.strip():
        return "text"
    kinds = {asset.kind for asset in assets}
    if "pdf" in kinds:
        return "pdf"
    if "image" in kinds:
        return "image"
    if "video" in kinds or "external_video" in kinds:
        return "video"
    return "empty"
```

- [ ] **Step 6: Run source tests**

Run:

```powershell
conda run -n spider pytest tests/notice_push/test_sources.py -q
```

Expected: pass.

- [ ] **Step 7: Commit and push Feature 2**

Run:

```powershell
git status --short
git add src/notice_push/html_utils.py src/notice_push/sources tests/notice_push/test_sources.py tests/fixtures/source_pages
git commit -m "feat: extract notice media assets"
git push
```

Expected: commit contains source parsing and fixture changes only.

## Task 3: Add Multi-Provider LLM Configuration

**Files:**
- Modify: `resources/config/runtime.yml`
- Modify: `.env.example`
- Modify: `src/notice_push/config.py`
- Create: `src/notice_push/llm.py`
- Test: `tests/notice_push/test_config_models.py`

- [ ] **Step 1: Write config tests**

Add a test that loads DeepSeek and Kimi provider config:

```python
def test_loads_llm_provider_and_routing_config(tmp_path, monkeypatch):
    config_dir = tmp_path / "resources" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "runtime.yml").write_text(
        "\n".join(
            [
                "prompt_name: notice_summary_v1",
                "detail_min_chars: 30",
                "llm:",
                "  providers:",
                "    deepseek:",
                "      base_url: https://api.deepseek.com",
                "      api_key_env: DEEPSEEK_API_KEY",
                "      model_env: DEEPSEEK_MODEL",
                "      default_model: deepseek-v4-flash",
                "    kimi:",
                "      base_url: https://api.moonshot.cn/v1",
                "      api_key_env: KIMI_API_KEY",
                "      model_env: KIMI_MODEL",
                "      default_model: kimi-k2.7-code",
                "  routing:",
                "    text: deepseek",
                "    pdf: kimi",
                "    image: kimi",
                "sources: {}",
                "profiles:",
                "  daily:",
                "    max_pages_per_source: 5",
                "    stop_after_seen_pages: 2",
                "    lookback_days: 365",
                "    detail_max_workers: 2",
                "    summary_max_workers: 3",
                "    retry_failed: true",
                "    failed_retry_limit: 3",
                "    failed_retry_after_hours: 12",
                "    refresh_seen_details: false",
                "    refresh_seen_max_workers: 1",
                "    refresh_seen_limit: 0",
                "    http_timeout: 12",
                "    http_max_retries: 2",
                "    http_initial_retry_delay: 0.8",
                "    llm_timeout: 60",
                "    llm_max_retries: 3",
                "    llm_initial_retry_delay: 1.0",
                "    llm_retry_backoff: 2.0",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(tmp_path, env={})

    assert config.llm_providers["deepseek"].default_model == "deepseek-v4-flash"
    assert config.llm_providers["kimi"].base_url == "https://api.moonshot.cn/v1"
    assert config.llm_routing["pdf"] == "kimi"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
conda run -n spider pytest tests/notice_push/test_config_models.py -q
```

Expected: fail because LLM provider config models do not exist.

- [ ] **Step 3: Add config dataclasses**

In `src/notice_push/models.py`, add:

```python
@dataclass(frozen=True)
class LLMProviderConfig:
    name: str
    base_url: str
    api_key_env: str
    model_env: str
    default_model: str
```

Update `AppConfig`:

```python
llm_providers: dict[str, LLMProviderConfig]
llm_routing: dict[str, str]
```

- [ ] **Step 4: Update runtime YAML**

In `resources/config/runtime.yml`, replace top-level `deepseek_model` with:

```yaml
llm:
  providers:
    deepseek:
      base_url: https://api.deepseek.com
      api_key_env: DEEPSEEK_API_KEY
      model_env: DEEPSEEK_MODEL
      default_model: deepseek-v4-flash
    kimi:
      base_url: https://api.moonshot.cn/v1
      api_key_env: KIMI_API_KEY
      model_env: KIMI_MODEL
      default_model: kimi-k2.7-code
  routing:
    text: deepseek
    pdf: kimi
    image: kimi
```

Keep backward compatibility in `load_config`: if old `deepseek_model` exists, map it to `llm.providers.deepseek.default_model`.

- [ ] **Step 5: Update `.env.example`**

Make `.env.example` contain only:

```env
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_MODEL=deepseek-v4-flash
KIMI_API_KEY=your_kimi_api_key_here
KIMI_MODEL=kimi-k2.7-code
```

- [ ] **Step 6: Create OpenAI-compatible provider helper**

Create `src/notice_push/llm.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass

from openai import OpenAI

from src.notice_push.models import LLMProviderConfig


@dataclass(frozen=True)
class ResolvedLLMProvider:
    name: str
    base_url: str
    api_key: str
    model: str


def resolve_provider(name: str, config: LLMProviderConfig, env: dict[str, str] | None = None) -> ResolvedLLMProvider:
    active_env = env or os.environ
    api_key = active_env.get(config.api_key_env, "")
    if not api_key:
        raise ValueError(f"{config.api_key_env} must be provided for provider '{name}'")
    model = active_env.get(config.model_env, config.default_model)
    return ResolvedLLMProvider(
        name=name,
        base_url=config.base_url,
        api_key=api_key,
        model=model,
    )


def create_openai_client(provider: ResolvedLLMProvider) -> OpenAI:
    return OpenAI(api_key=provider.api_key, base_url=provider.base_url)
```

- [ ] **Step 7: Run config tests**

Run:

```powershell
conda run -n spider pytest tests/notice_push/test_config_models.py -q
```

Expected: pass.

- [ ] **Step 8: Commit and push Feature 3**

Run:

```powershell
git status --short
git add resources/config/runtime.yml .env.example src/notice_push/config.py src/notice_push/llm.py src/notice_push/models.py tests/notice_push/test_config_models.py
git commit -m "feat: configure multiple llm providers"
git push
```

Expected: commit contains configuration/model/provider setup only.

## Task 4: Implement Routed Text, PDF, And Image Summarization

**Files:**
- Modify: `src/notice_push/summarizer.py`
- Create: `src/notice_push/media.py`
- Test: `tests/notice_push/test_summarizer.py`

- [ ] **Step 1: Add fake-client tests for routing**

Add tests that verify:

- `content_kind="text"` uses DeepSeek provider.
- `content_kind="pdf"` uses Kimi file extraction flow.
- `content_kind="image"` sends a content array with `image_url`.

Use fake clients; do not call real APIs in unit tests.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
conda run -n spider pytest tests/notice_push/test_summarizer.py -q
```

Expected: fail because router and media handling are not implemented.

- [ ] **Step 3: Add media helper**

Create `src/notice_push/media.py`:

```python
from __future__ import annotations

import base64
import mimetypes
import tempfile
from pathlib import Path

from src.notice_push.http import HttpClient
from src.notice_push.models import NoticeAsset


def download_asset_to_temp(http_client: HttpClient, asset: NoticeAsset) -> Path:
    suffix = Path(asset.url).suffix or mimetypes.guess_extension(asset.mime_type) or ".bin"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    path = Path(handle.name)
    handle.close()
    content = http_client.get_bytes(asset.url)
    path.write_bytes(content)
    return path


def image_path_to_data_url(path: Path, mime_type: str = "") -> str:
    active_mime_type = mime_type or mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{active_mime_type};base64,{encoded}"
```

Add `HttpClient.get_bytes(url)` using the existing timeout/retry/session behavior.

- [ ] **Step 4: Split summarizer responsibilities**

Keep `NoticeSummarizer` for text compatibility, but introduce:

```python
class SummarizerRouter:
    def __init__(self, text_summarizer, kimi_summarizer, routing: dict[str, str]):
        self.text_summarizer = text_summarizer
        self.kimi_summarizer = kimi_summarizer
        self.routing = routing

    def summarize(self, notice_id: int, detail: NoticeDetail, source_name: str | None = None) -> NoticeSummary:
        if detail.content_kind == "text":
            return self.text_summarizer.summarize(notice_id, detail, source_name=source_name)
        if detail.content_kind in {"pdf", "image"}:
            return self.kimi_summarizer.summarize(notice_id, detail, source_name=source_name)
        raise ValueError(f"unsupported content kind: {detail.content_kind}")
```

- [ ] **Step 5: Implement Kimi PDF summary flow**

For a PDF asset:

```python
file_object = client.files.create(file=pdf_path, purpose="file-extract")
file_content = client.files.content(file_id=file_object.id).text
```

Then call chat completions with:

```python
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "system", "content": file_content},
    {"role": "user", "content": rendered_notice_instruction},
]
```

After completion, attempt:

```python
client.files.delete(file_id=file_object.id)
```

Deletion failure should not fail the notice summary; log or ignore it.

- [ ] **Step 6: Implement Kimi image summary flow**

For an image asset, send:

```python
messages = [
    {"role": "system", "content": system_prompt},
    {
        "role": "user",
        "content": [
            {
                "type": "image_url",
                "image_url": {"url": image_data_url},
            },
            {
                "type": "text",
                "text": rendered_notice_instruction,
            },
        ],
    },
]
```

Do not JSON-serialize the content array.

- [ ] **Step 7: Respect Kimi K2.7 Code parameter limits**

Do not pass `thinking={"type": "disabled"}` or custom `temperature` for Kimi K2.7 Code. The official docs say K2.7 Code does not support disabling thinking and has fixed parameter behavior.

- [ ] **Step 8: Run summarizer tests**

Run:

```powershell
conda run -n spider pytest tests/notice_push/test_summarizer.py -q
```

Expected: pass.

- [ ] **Step 9: Commit and push Feature 4**

Run:

```powershell
git status --short
git add src/notice_push/summarizer.py src/notice_push/media.py src/notice_push/http.py tests/notice_push/test_summarizer.py
git commit -m "feat: route summaries by notice content type"
git push
```

Expected: commit contains routed summarization and media handling only.

## Task 5: Classify Unsupported Video Notices Clearly

**Files:**
- Modify: `src/notice_push/pipeline.py`
- Modify: `src/notice_push/report.py` if a clearer report label is needed
- Test: `tests/notice_push/test_pipeline.py`

- [ ] **Step 1: Add a pipeline test for video details**

Add a test where adapter returns:

```python
NoticeDetail(
    source_id="graduate_school",
    url="https://www.kankanews.com/detail/dZ2e81vaawR",
    canonical_url="https://www.kankanews.com/detail/dZ2e81vaawR",
    title="卓越工程师学院承办上海市工程硕博士培养改革2026年招生工作校企对接会",
    content="",
    assets=(
        NoticeAsset(
            kind="external_video",
            role="primary",
            name="看看新闻视频页",
            url="https://www.kankanews.com/detail/dZ2e81vaawR",
            mime_type="text/html",
        ),
    ),
    content_kind="video",
)
```

Assert the failure type stored in SQLite is `unsupported_video_content` and the report reason is `unsupported video content`.

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
conda run -n spider pytest tests/notice_push/test_pipeline.py -q
```

Expected: fail until classification is implemented.

- [ ] **Step 3: Update failure classifier**

In `_classify_failure`, add:

```python
if isinstance(exc, UnsupportedContentError) or "unsupported video content" in message:
    return "unsupported_video_content"
```

- [ ] **Step 4: Ensure retry semantics remain clear**

Keep unsupported video records as failed records. They may be retried under the existing failed-notice retry policy, but they will deterministically fail until video support is intentionally implemented. This is acceptable for this version because the user requested video not be processed.

- [ ] **Step 5: Run pipeline tests**

Run:

```powershell
conda run -n spider pytest tests/notice_push/test_pipeline.py -q
```

Expected: pass.

This task is part of Feature 1 if implemented there. If it is implemented later as a separate behavior fix, commit and push it before continuing:

```powershell
git status --short
git add src/notice_push/pipeline.py src/notice_push/report.py tests/notice_push/test_pipeline.py
git commit -m "fix: report unsupported video notices explicitly"
git push
```

## Task 6: Wire Router Into CLI And GitHub Actions

**Files:**
- Modify: `src/notice_push/__main__.py`
- Modify: `.github/workflows/daily_report.yml`
- Modify: `README.md`
- Test: `tests/notice_push/test_cli.py`

- [ ] **Step 1: Add CLI construction tests**

Update CLI tests to assert the application can run with provider config present and no longer depends on top-level `deepseek_model`.

- [ ] **Step 2: Update CLI summarizer construction**

In `src/notice_push/__main__.py`, construct:

- DeepSeek text summarizer from the `deepseek` provider.
- Kimi multimodal summarizer from the `kimi` provider.
- `SummarizerRouter` using `config.llm_routing`.

Use the active runtime profile for timeout and retry parameters.

- [ ] **Step 3: Update GitHub Actions**

In `.github/workflows/daily_report.yml`, add:

```yaml
KIMI_API_KEY: ${{ secrets.KIMI_API_KEY }}
KIMI_MODEL: ${{ secrets.KIMI_MODEL || 'kimi-k2.7-code' }}
```

Keep:

```yaml
DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
DEEPSEEK_MODEL: ${{ secrets.DEEPSEEK_MODEL || 'deepseek-v4-flash' }}
```

- [ ] **Step 4: Update README**

Add GitHub Secrets documentation:

- `DEEPSEEK_API_KEY`: required for text notices.
- `DEEPSEEK_MODEL`: optional, default `deepseek-v4-flash`.
- `KIMI_API_KEY`: required for PDF/image notices.
- `KIMI_MODEL`: optional, default `kimi-k2.7-code`.

Document that video-body notices are currently detected but not summarized.

- [ ] **Step 5: Run CLI tests**

Run:

```powershell
conda run -n spider pytest tests/notice_push/test_cli.py -q
```

Expected: pass.

- [ ] **Step 6: Commit and push Feature 5**

Run:

```powershell
git status --short
git add src/notice_push/__main__.py .github/workflows/daily_report.yml README.md tests/notice_push/test_cli.py
git commit -m "docs: wire multimodal llm configuration"
git push
```

Expected: commit contains CLI/workflow/documentation wiring only.

## Task 7: Integration Verification

**Files:**
- No required source edits unless tests reveal defects.

- [ ] **Step 1: Run focused test suite**

Run:

```powershell
conda run -n spider pytest tests/notice_push -q
```

Expected: pass.

- [ ] **Step 2: Run dry-run smoke test**

Run:

```powershell
conda run -n spider python -m src.notice_push --dry-run --limit 1
```

Expected: command completes without writing real report data.

- [ ] **Step 3: Optional real API smoke test without polluting real data**

If using real API keys, run with an isolated temp output/state directory through test config or `.tmp/` fixture setup. Do not write to `resources/results/` or the real SQLite state.

- [ ] **Step 4: Inspect expected behavior for 2026-07-03-style cases**

Verify:

- PDF-only notices no longer fail as `detail content is empty or too short`.
- Image-only notices no longer fail as `detail content is empty or too short`.
- Video notices fail as `unsupported video content`.
- Text notices still summarize through DeepSeek.

- [ ] **Step 5: Push final branch state and stop for user approval**

Run:

```powershell
git status --short
git log --oneline --decorate -5
git push
```

Expected:

- The feature branch is pushed to GitHub.
- There are no unintended uncommitted implementation changes.
- Unrelated local files such as `resources/notice_records.csv`, if still modified, are not included in feature commits.
- The assistant reports the branch name, latest commit, test commands run, and any remaining risks to the user.
- The assistant does not merge, rebase, squash, or force-push until the user approves final integration.

## Acceptance Criteria

- [ ] Text notices continue to use DeepSeek and keep the existing report format.
- [ ] PDF notices are detected from detail pages and summarized through Kimi K2.7 Code.
- [ ] Image notices are detected from detail pages and summarized through Kimi K2.7 Code.
- [ ] Video or external-video notices are explicitly marked `unsupported_video_content`.
- [ ] `detail content is empty or too short` is reserved for pages with no supported text/PDF/image body.
- [ ] GitHub Actions passes `KIMI_API_KEY` and `KIMI_MODEL`.
- [ ] `.env.example` contains only API keys and model names.
- [ ] Unit tests use fake clients and do not call real APIs.
- [ ] Any real API smoke test uses `.tmp/` or another isolated path and does not pollute real data.
- [ ] All feature commits are pushed to `MAIN/feature/multimodal-llm-routing`.
- [ ] Final integration into `main` is not performed until after explicit user approval.
