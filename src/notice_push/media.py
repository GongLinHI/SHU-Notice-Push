from __future__ import annotations

import base64
import mimetypes
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from src.notice_push.http import HttpClient
from src.notice_push.models import NoticeAsset


def download_asset_to_temp(http_client: HttpClient, asset: NoticeAsset) -> Path:
    suffix = _suffix_for_asset(asset)
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    path = Path(handle.name)
    handle.close()
    path.write_bytes(http_client.get_bytes(asset.url))
    return path


def image_path_to_data_url(path: Path, mime_type: str = "") -> str:
    active_mime_type = mime_type or mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{active_mime_type};base64,{encoded}"


def _suffix_for_asset(asset: NoticeAsset) -> str:
    parsed_suffix = Path(urlparse(asset.url).path).suffix
    if parsed_suffix:
        return parsed_suffix
    guessed_suffix = mimetypes.guess_extension(asset.mime_type)
    return guessed_suffix or ".bin"
