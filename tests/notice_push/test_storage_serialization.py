from notice_push.domain import Attachment, NoticeAsset, NoticeDetail
from notice_push.storage.serialization import attachments_json, assets_json, detail_from_row


def test_storage_media_json_keeps_canonical_representation():
    detail = NoticeDetail(
        source_id="test",
        url="https://example.com/notice",
        canonical_url="https://example.com/notice",
        title="测试通知",
        content="",
        attachments=(Attachment(name="附件.pdf", url="https://example.com/a.pdf"),),
        assets=(
            NoticeAsset(
                kind="pdf",
                role="primary",
                name="附件.pdf",
                url="https://example.com/a.pdf",
                mime_type="application/pdf",
            ),
        ),
    )

    assert attachments_json(detail) == (
        '[{"name": "附件.pdf", "url": "https://example.com/a.pdf"}]'
    )
    assert assets_json(detail) == (
        '[{"kind": "pdf", "mime_type": "application/pdf", "name": "附件.pdf", '
        '"role": "primary", "url": "https://example.com/a.pdf"}]'
    )


def test_storage_media_json_rejects_invalid_historical_shapes_without_crashing():
    detail = detail_from_row(
        {
            "source_id": "test",
            "url": "https://example.com/notice",
            "canonical_url": "https://example.com/notice",
            "title": "测试通知",
            "content": "正文",
            "published_at": None,
            "list_excerpt": "",
            "attachments_json": '["invalid"]',
            "assets_json": '{"not": "a list"}',
            "content_kind": "text",
        }
    )

    assert detail.attachments == ()
    assert detail.assets == ()
