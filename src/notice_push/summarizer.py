from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from openai import OpenAI

from src.notice_push.http import HttpClient
from src.notice_push.llm_chat import create_chat_completion_with_retry
from src.notice_push.media import download_asset_to_temp, image_path_to_data_url
from src.notice_push.models import NoticeAsset, NoticeDetail, NoticeSummary
from src.notice_push.resources import visible_notice_resources


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
KIMI_BASE_URL = "https://api.moonshot.cn/v1"
MEDIA_ASSET_ROLES = {"primary", "attachment"}


def load_prompt(prompt_dir: Path, prompt_name: str) -> str:
    path = Path(prompt_dir) / f"{prompt_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def render_notice_user_prompt(
    detail: NoticeDetail,
    source_name: Optional[str] = None,
    content: Optional[str] = None,
) -> str:
    resources = visible_notice_resources(detail)
    attachments = "\n".join(f"- {name}: {url}" for name, url in resources) or "未提及"
    published_at = detail.published_at.isoformat(sep=" ") if detail.published_at else "未提及"
    body = detail.content if content is None else content
    return (
        f"- 来源：{source_name or detail.source_id}\n"
        f"- 标题：{detail.title}\n"
        f"- 发布时间：{published_at}\n"
        f"- url：{detail.url}\n"
        f"- 附件：\n{attachments}\n"
        f"- 目录页摘要（仅供参考，不可替代正文）：{detail.list_excerpt or '未提及'}\n"
        f"- 正文：{body}\n"
    )


class NoticeSummarizer:
    def __init__(
        self,
        prompt_dir: Path,
        prompt_name: str,
        model: str,
        api_key: Optional[str] = None,
        base_url: str = DEEPSEEK_BASE_URL,
        client=None,
        timeout: int = 60,
        max_retries: int = 2,
        initial_retry_delay: float = 0.5,
        retry_backoff: float = 2.0,
    ):
        self.prompt_dir = Path(prompt_dir)
        self.prompt_name = prompt_name
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self._client = client
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.initial_retry_delay = max(0.0, initial_retry_delay)
        self.retry_backoff = max(1.0, retry_backoff)
        self._system_prompt: Optional[str] = None

    def summarize(self, notice_id: int, detail: NoticeDetail, source_name: Optional[str] = None) -> NoticeSummary:
        if not detail.content.strip():
            raise ValueError("detail content is required for summarization")

        system_prompt = self._get_system_prompt()
        user_prompt = self.render_user_prompt(detail, source_name=source_name)
        content = self._chat(system_prompt, user_prompt)

        return NoticeSummary(
            notice_id=notice_id,
            markdown=content,
            model=self.model,
            prompt_version=self.prompt_name,
            generated_at=datetime.now(timezone.utc).replace(microsecond=0),
        )

    def render_user_prompt(self, detail: NoticeDetail, source_name: Optional[str] = None) -> str:
        return render_notice_user_prompt(detail, source_name=source_name)

    def _chat(self, system_prompt: str, user_prompt: str) -> str:
        return create_chat_completion_with_retry(
            self._get_client(),
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=self.timeout,
            max_retries=self.max_retries,
            initial_retry_delay=self.initial_retry_delay,
            retry_backoff=self.retry_backoff,
        )

    def _get_system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = load_prompt(self.prompt_dir, self.prompt_name)
        return self._system_prompt

    def _get_client(self):
        if self._client is not None:
            return self._client

        api_key = self.api_key or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY must be provided for real summarization")
        self._client = OpenAI(api_key=api_key, base_url=self.base_url)
        return self._client


class KimiMultimodalSummarizer:
    def __init__(
        self,
        prompt_dir: Path,
        prompt_name: str,
        model: str,
        api_key: Optional[str] = None,
        base_url: str = KIMI_BASE_URL,
        client=None,
        http_client: Optional[HttpClient] = None,
        downloader: Optional[Callable[[NoticeAsset], Path]] = None,
        timeout: int = 60,
        max_retries: int = 2,
        initial_retry_delay: float = 0.5,
        retry_backoff: float = 2.0,
    ):
        self.prompt_dir = Path(prompt_dir)
        self.prompt_name = prompt_name
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self._client = client
        self.http_client = http_client or HttpClient()
        if downloader is None:
            self._downloader = lambda asset: download_asset_to_temp(self.http_client, asset)
            self._owns_downloads = True
        else:
            self._downloader = downloader
            self._owns_downloads = False
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.initial_retry_delay = max(0.0, initial_retry_delay)
        self.retry_backoff = max(1.0, retry_backoff)
        self._system_prompt: Optional[str] = None

    def summarize(self, notice_id: int, detail: NoticeDetail, source_name: Optional[str] = None) -> NoticeSummary:
        if detail.content_kind == "pdf":
            markdown = self._summarize_pdf(detail, source_name=source_name)
        elif detail.content_kind == "image":
            markdown = self._summarize_image(detail, source_name=source_name)
        else:
            raise ValueError(f"unsupported Kimi content kind: {detail.content_kind}")

        return NoticeSummary(
            notice_id=notice_id,
            markdown=markdown,
            model=self.model,
            prompt_version=self.prompt_name,
            generated_at=datetime.now(timezone.utc).replace(microsecond=0),
        )

    def _summarize_pdf(self, detail: NoticeDetail, source_name: Optional[str] = None) -> str:
        asset = self._select_asset(detail, "pdf")
        path = self._downloader(asset)
        file_id = ""
        try:
            file_object = self._get_client().files.create(file=path, purpose="file-extract")
            file_id = getattr(file_object, "id")
            if not file_id:
                raise ValueError("Kimi file upload did not return a file id")
            file_content = self._get_client().files.content(file_id=file_id).text
            if not file_content or not file_content.strip():
                raise ValueError("empty PDF extraction response from Kimi")
            messages = [
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "system", "content": file_content},
                {
                    "role": "user",
                    "content": render_notice_user_prompt(
                        detail,
                        source_name=source_name,
                        content="PDF 解析文本已在上一条 system 消息提供，请以该正文为准。",
                    ),
                },
            ]
            return self._chat(messages)
        finally:
            if file_id:
                try:
                    self._get_client().files.delete(file_id=file_id)
                except Exception:
                    pass
            self._cleanup_download(path)

    def _summarize_image(self, detail: NoticeDetail, source_name: Optional[str] = None) -> str:
        asset = self._select_asset(detail, "image")
        path = self._downloader(asset)
        try:
            image_data_url = image_path_to_data_url(path, mime_type=asset.mime_type)
            messages = [
                {"role": "system", "content": self._get_system_prompt()},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_url},
                        },
                        {
                            "type": "text",
                            "text": render_notice_user_prompt(
                                detail,
                                source_name=source_name,
                                content="通知正文是一张图片，请直接阅读图片内容后总结。",
                            ),
                        },
                    ],
                },
            ]
            return self._chat(messages)
        finally:
            self._cleanup_download(path)

    def _chat(self, messages: list[dict]) -> str:
        return create_chat_completion_with_retry(
            self._get_client(),
            model=self.model,
            messages=messages,
            timeout=self.timeout,
            max_retries=self.max_retries,
            initial_retry_delay=self.initial_retry_delay,
            retry_backoff=self.retry_backoff,
        )

    def _select_asset(self, detail: NoticeDetail, kind: str) -> NoticeAsset:
        for asset in detail.assets:
            if asset.kind == kind and asset.role in MEDIA_ASSET_ROLES:
                return asset
        raise ValueError(f"no {kind} asset found for notice detail")

    def _cleanup_download(self, path: Path) -> None:
        if not self._owns_downloads:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    def _get_system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = load_prompt(self.prompt_dir, self.prompt_name)
        return self._system_prompt

    def _get_client(self):
        if self._client is not None:
            return self._client

        api_key = self.api_key or os.getenv("KIMI_API_KEY")
        if not api_key:
            raise ValueError("KIMI_API_KEY must be provided for real multimodal summarization")
        self._client = OpenAI(api_key=api_key, base_url=self.base_url)
        return self._client


class SummarizerRouter:
    def __init__(self, text_summarizer, kimi_summarizer, routing: dict[str, str]):
        self.routing = dict(routing)
        self.provider_summarizers = {
            "deepseek": text_summarizer,
            "kimi": kimi_summarizer,
        }

    def summarize(self, notice_id: int, detail: NoticeDetail, source_name: Optional[str] = None) -> NoticeSummary:
        content_kind = detail.content_kind or "text"
        provider_name = self.routing.get(content_kind)
        if not provider_name:
            raise ValueError(f"unsupported content kind: {content_kind}")
        summarizer = self.provider_summarizers.get(provider_name)
        if summarizer is None:
            raise ValueError(f"no summarizer configured for provider: {provider_name}")
        return summarizer.summarize(notice_id, detail, source_name=source_name)
