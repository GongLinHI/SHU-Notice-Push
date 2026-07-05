from pathlib import Path

import pytest

from src.notice_push import media as media_module
from src.notice_push.media import download_asset_to_temp
from src.notice_push.models import NoticeAsset


class _BytesHttpClient:
    def __init__(self, content: bytes):
        self.content = content

    def get_bytes(self, url: str) -> bytes:
        return self.content


class _FailingHttpClient:
    def get_bytes(self, url: str) -> bytes:
        raise RuntimeError("download failed")


def test_download_asset_to_temp_writes_downloaded_bytes():
    asset = NoticeAsset(
        kind="image",
        role="primary",
        name="duty.png",
        url="https://ms.shu.edu.cn/__local/duty.png",
        mime_type="image/png",
    )

    path = download_asset_to_temp(_BytesHttpClient(b"image-bytes"), asset)

    try:
        assert path.suffix == ".png"
        assert path.read_bytes() == b"image-bytes"
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
        download_asset_to_temp(_FailingHttpClient(), asset)

    assert list(tmp_path.iterdir()) == []
