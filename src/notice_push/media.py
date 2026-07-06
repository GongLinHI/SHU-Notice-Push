from __future__ import annotations

import base64
import mimetypes
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from src.notice_push.http import DownloadedBytes, HttpClient
from src.notice_push.models import NoticeAsset


def download_asset_to_temp(http_client: HttpClient, asset: NoticeAsset, max_bytes: int) -> Path:
    downloaded = _download_limited(http_client, asset.url, max_bytes)
    content = downloaded.content
    if not content:
        raise ValueError("downloaded media is empty")
    _validate_asset_type(asset, downloaded)
    suffix = _suffix_for_asset(asset, downloaded)
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    path = Path(handle.name)
    try:
        handle.write(content)
    finally:
        handle.close()
    return path


def image_path_to_data_url(path: Path, mime_type: str = "") -> str:
    active_mime_type = mime_type or mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{active_mime_type};base64,{encoded}"


def _download_limited(http_client: HttpClient, url: str, max_bytes: int) -> DownloadedBytes:
    get_download_limited = getattr(http_client, "get_download_limited", None)
    if callable(get_download_limited):
        return get_download_limited(url, max_bytes=max_bytes)
    return DownloadedBytes(
        content=http_client.get_bytes_limited(url, max_bytes=max_bytes),
        content_type="",
    )


def _suffix_for_asset(asset: NoticeAsset, downloaded: DownloadedBytes) -> str:
    if asset.kind == "pdf" and _is_pdf_content(downloaded.content):
        return ".pdf"
    image_suffix = _image_suffix_from_content(downloaded.content)
    if asset.kind == "image" and image_suffix:
        return image_suffix
    parsed_suffix = Path(urlparse(asset.url).path).suffix
    if parsed_suffix:
        return parsed_suffix
    name_suffix = Path(asset.name).suffix
    if name_suffix:
        return name_suffix
    guessed_suffix = mimetypes.guess_extension(asset.mime_type or downloaded.content_type)
    return guessed_suffix or ".bin"


def _validate_asset_type(asset: NoticeAsset, downloaded: DownloadedBytes) -> None:
    suffixes = _asset_suffixes(asset)
    mime_type = (asset.mime_type or "").lower()
    response_type = (downloaded.content_type or "").lower()
    if asset.kind == "pdf":
        has_pdf_hint = mime_type == "application/pdf" or response_type == "application/pdf" or ".pdf" in suffixes
        if _is_pdf_content(downloaded.content):
            return
        if has_pdf_hint:
            raise ValueError("PDF content signature is not recognized")
        raise ValueError("PDF asset must have .pdf suffix, application/pdf MIME type, or PDF content signature")
    if asset.kind == "image":
        has_image_hint = mime_type.startswith("image/") or response_type.startswith("image/") or any(
            _is_image_suffix(suffix) for suffix in suffixes
        )
        if _image_suffix_from_content(downloaded.content):
            return
        if has_image_hint:
            raise ValueError("image content signature is not recognized")
        raise ValueError("image asset must have image suffix, image/* MIME type, or image content signature")


def _asset_suffixes(asset: NoticeAsset) -> set[str]:
    return {
        suffix.lower()
        for suffix in (Path(urlparse(asset.url).path).suffix, Path(asset.name).suffix)
        if suffix
    }


def _is_image_suffix(suffix: str) -> bool:
    guessed_mime_type = mimetypes.types_map.get(suffix.lower(), "")
    return guessed_mime_type.startswith("image/")


def _is_pdf_content(content: bytes) -> bool:
    return content.lstrip().startswith(b"%PDF")


def _image_suffix_from_content(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return ".gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return ""
