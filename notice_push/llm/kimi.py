from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from notice_push.http import HttpClient
from notice_push.llm.chat import call_with_retry, create_chat_completion_with_retry
from notice_push.llm.client_factory import OpenAIClientProvider
from notice_push.llm.prompts import CachedPrompt, render_notice_user_prompt
from notice_push.llm.summary_format import SummaryFormatProcessor
from notice_push.parsing.media import download_asset_to_temp, image_path_to_data_url
from notice_push.domain import MediaPolicy, NoticeAsset, NoticeDetail, NoticeSummary


MEDIA_ASSET_ROLES = {"primary", "attachment"}


class KimiMultimodalSummarizer:
    def __init__(
        self,
        prompt_dir: Path,
        prompt_name: str,
        model: str,
        media_policy: MediaPolicy,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        provider_name: str = "kimi",
        client=None,
        http_client: Optional[HttpClient] = None,
        downloader: Optional[Callable[[NoticeAsset], Path]] = None,
        timeout: int = 60,
        max_retries: int = 2,
        initial_retry_delay: float = 0.5,
        retry_backoff: float = 2.0,
        summary_format_repair_retries: int = 1,
    ):
        self.prompt_dir = Path(prompt_dir)
        self.prompt_name = prompt_name
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.provider_name = provider_name
        self._client_provider = OpenAIClientProvider(
            client=client,
            api_key=api_key,
            base_url=base_url,
            provider_name=provider_name,
        )
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
        self._format_processor = SummaryFormatProcessor(summary_format_repair_retries)
        self._system_prompt = CachedPrompt(self.prompt_dir, self.prompt_name)

    def summarize(self, notice_id: int, detail: NoticeDetail, source_name: Optional[str] = None) -> NoticeSummary:
        if detail.content_kind == "pdf":
            markdown = self._summarize_pdf(detail, source_name=source_name)
        elif detail.content_kind == "image":
            markdown = self._summarize_image(detail, source_name=source_name)
        else:
            raise ValueError(f"unsupported Kimi content kind: {detail.content_kind}")
        markdown = self._format_processor.normalize_validate_or_repair(
            markdown,
            source_detail=detail,
            source_name=source_name,
            chat_for_repair=self._chat_for_repair,
        )

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
            file_object = call_with_retry(
                lambda: self._get_client().files.create(file=path, purpose="file-extract", timeout=self.timeout),
                max_retries=self.max_retries,
                initial_retry_delay=self.initial_retry_delay,
                retry_backoff=self.retry_backoff,
            )
            file_id = getattr(file_object, "id")
            if not file_id:
                raise ValueError("Kimi file upload did not return a file id")
            file_content = call_with_retry(
                lambda: self._get_client().files.content(file_id=file_id, timeout=self.timeout),
                max_retries=self.max_retries,
                initial_retry_delay=self.initial_retry_delay,
                retry_backoff=self.retry_backoff,
            ).text
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

    def _chat_for_repair(self, repair_prompt: str) -> str:
        return self._chat(
            [
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": repair_prompt},
            ]
        )

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
        return self._system_prompt.get()

    def _get_client(self):
        return self._client_provider.get()
