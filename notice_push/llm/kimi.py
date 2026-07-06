from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from openai import OpenAI

from notice_push.http import HttpClient
from notice_push.llm.chat import create_chat_completion_with_retry
from notice_push.llm.prompts import load_prompt, render_notice_user_prompt
from notice_push.llm.repair import render_summary_repair_prompt
from notice_push.parsing.media import download_asset_to_temp, image_path_to_data_url
from notice_push.domain import MediaPolicy, NoticeAsset, NoticeDetail, NoticeSummary
from notice_push.summary_validator import normalize_summary_markdown, validate_summary_markdown


KIMI_BASE_URL = "https://api.moonshot.cn/v1"
MEDIA_ASSET_ROLES = {"primary", "attachment"}


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
        media_policy: MediaPolicy = MediaPolicy(),
        summary_format_repair_retries: int = 1,
    ):
        self.prompt_dir = Path(prompt_dir)
        self.prompt_name = prompt_name
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self._client = client
        self.http_client = http_client or HttpClient()
        self.media_policy = media_policy
        if downloader is None:
            self._downloader = lambda asset: download_asset_to_temp(
                self.http_client,
                asset,
                max_bytes=self._max_bytes_for_asset(asset),
            )
            self._owns_downloads = True
        else:
            self._downloader = downloader
            self._owns_downloads = False
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.initial_retry_delay = max(0.0, initial_retry_delay)
        self.retry_backoff = max(1.0, retry_backoff)
        self.summary_format_repair_retries = max(0, summary_format_repair_retries)
        self._system_prompt: Optional[str] = None

    def summarize(self, notice_id: int, detail: NoticeDetail, source_name: Optional[str] = None) -> NoticeSummary:
        if detail.content_kind == "pdf":
            markdown = self._summarize_pdf(detail, source_name=source_name)
        elif detail.content_kind == "image":
            markdown = self._summarize_image(detail, source_name=source_name)
        else:
            raise ValueError(f"unsupported Kimi content kind: {detail.content_kind}")
        markdown = self._normalize_validate_or_repair(markdown, detail, source_name)

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
            if len(file_content) > self.media_policy.pdf_extracted_text_max_chars:
                file_content = file_content[: self.media_policy.pdf_extracted_text_max_chars]
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

    def _normalize_validate_or_repair(
        self,
        markdown: str,
        detail: NoticeDetail,
        source_name: Optional[str],
    ) -> str:
        normalized = normalize_summary_markdown(markdown)
        try:
            validate_summary_markdown(normalized)
            return normalized
        except ValueError as original_error:
            last_error = original_error

        for _ in range(self.summary_format_repair_retries):
            repair_messages = [
                {"role": "system", "content": self._get_system_prompt()},
                {
                    "role": "user",
                    "content": render_summary_repair_prompt(
                        render_notice_user_prompt(detail, source_name=source_name),
                        normalized,
                    ),
                },
            ]
            normalized = normalize_summary_markdown(self._chat(repair_messages))
            try:
                validate_summary_markdown(normalized)
                return normalized
            except ValueError as exc:
                last_error = exc
        raise last_error

    def _select_asset(self, detail: NoticeDetail, kind: str) -> NoticeAsset:
        for asset in detail.assets:
            if asset.kind == kind and asset.role in MEDIA_ASSET_ROLES:
                return asset
        raise ValueError(f"no {kind} asset found for notice detail")

    def _max_bytes_for_asset(self, asset: NoticeAsset) -> int:
        if asset.kind == "pdf":
            return self.media_policy.pdf_max_bytes
        if asset.kind == "image":
            return self.media_policy.image_max_bytes
        raise ValueError(f"unsupported media asset kind: {asset.kind}")

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
