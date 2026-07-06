from pathlib import Path

import pytest

from notice_push.parsing import media as media_module
from notice_push.parsing.media import download_asset_to_temp
from notice_push.domain import NoticeAsset


PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"


class _BytesHttpClient:
    def __init__(self, content: bytes):
        self.content = content
        self.requests = []

    def get_bytes_limited(self, url: str, max_bytes: int) -> bytes:
        self.requests.append((url, max_bytes))
        return self.content


class _DownloadHttpClient:
    def __init__(self, content: bytes, content_type: str):
        self.content = content
        self.content_type = content_type
        self.requests = []

    def get_download_limited(self, url: str, max_bytes: int):
        from notice_push.http import DownloadedBytes

        self.requests.append((url, max_bytes))
        return DownloadedBytes(content=self.content, content_type=self.content_type)


class _FailingHttpClient:
    def get_bytes_limited(self, url: str, max_bytes: int) -> bytes:
        raise RuntimeError("download failed")


def test_download_asset_to_temp_writes_downloaded_bytes():
    asset = NoticeAsset(
        kind="image",
        role="primary",
        name="duty.png",
        url="https://ms.shu.edu.cn/__local/duty.png",
        mime_type="image/png",
    )

    http_client = _BytesHttpClient(PNG_BYTES)
    path = download_asset_to_temp(http_client, asset, max_bytes=1024)

    try:
        assert path.suffix == ".png"
        assert path.read_bytes() == PNG_BYTES
        assert http_client.requests == [(asset.url, 1024)]
    finally:
        Path(path).unlink(missing_ok=True)


def test_download_asset_to_temp_does_not_create_file_when_download_fails(tmp_path, monkeypatch):
    original_named_temporary_file = media_module.tempfile.NamedTemporaryFile

    def named_temporary_file_in_tmp_path(*args, **kwargs):
        kwargs["dir"] = tmp_path
        return original_named_temporary_file(*args, **kwargs)

    monkeypatch.setattr(media_module.tempfile, "NamedTemporaryFile", named_temporary_file_in_tmp_path)
    asset = NoticeAsset(
        kind="pdf",
        role="primary",
        name="notice.pdf",
        url="https://ms.shu.edu.cn/__local/notice.pdf",
        mime_type="application/pdf",
    )

    with pytest.raises(RuntimeError, match="download failed"):
        download_asset_to_temp(_FailingHttpClient(), asset, max_bytes=1024)

    assert list(tmp_path.iterdir()) == []


def test_download_asset_to_temp_rejects_empty_download():
    asset = NoticeAsset(
        kind="pdf",
        role="primary",
        name="notice.pdf",
        url="https://ms.shu.edu.cn/__local/notice.pdf",
        mime_type="application/pdf",
    )

    with pytest.raises(ValueError, match="downloaded media is empty"):
        download_asset_to_temp(_BytesHttpClient(b""), asset, max_bytes=1024)


def test_download_asset_to_temp_validates_pdf_type():
    asset = NoticeAsset(
        kind="pdf",
        role="primary",
        name="notice.txt",
        url="https://ms.shu.edu.cn/__local/notice.txt",
        mime_type="text/plain",
    )

    with pytest.raises(ValueError, match="PDF asset must have"):
        download_asset_to_temp(_BytesHttpClient(b"not a pdf"), asset, max_bytes=1024)


def test_download_asset_to_temp_validates_image_type():
    asset = NoticeAsset(
        kind="image",
        role="primary",
        name="notice.bin",
        url="https://ms.shu.edu.cn/__local/notice.bin",
        mime_type="application/octet-stream",
    )

    with pytest.raises(ValueError, match="image asset must have"):
        download_asset_to_temp(_BytesHttpClient(b"not an image"), asset, max_bytes=1024)


def test_pdf_download_accepts_query_url_when_magic_bytes_match():
    asset = NoticeAsset("pdf", "primary", "download", "https://example.com/download?id=1", "")
    client = _DownloadHttpClient(b"%PDF-1.7 body", "application/octet-stream")
    path = download_asset_to_temp(client, asset, max_bytes=1024)

    try:
        assert path.suffix == ".pdf"
        assert path.read_bytes().startswith(b"%PDF")
    finally:
        Path(path).unlink(missing_ok=True)


def test_image_download_rejects_wrong_magic_bytes_even_when_url_looks_like_png():
    asset = NoticeAsset("image", "primary", "notice.png", "https://example.com/notice.png", "image/png")

    with pytest.raises(ValueError, match="image content signature"):
        download_asset_to_temp(_DownloadHttpClient(b"not image", "image/png"), asset, max_bytes=1024)
