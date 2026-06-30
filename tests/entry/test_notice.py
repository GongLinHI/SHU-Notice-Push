import pytest
from datetime import date
from src.entry.notice import Notice


def test_notice_init_and_properties():
    n = Notice(
        url="http://example.com",
        title="Test Title",
        content="Test Content",
        upload_time=date(2024, 6, 1),
        summary="Test Summary"
    )
    assert n.url == "http://example.com"
    assert n.title == "Test Title"
    assert n.content == "Test Content"
    assert n.upload_time == date(2024, 6, 1)
    assert n.summary == "Test Summary"


def test_notice_setters():
    n = Notice(url="http://a.com")
    n.url = "http://b.com"
    n.title = "New Title"
    n.content = "New Content"
    n.upload_time = date(2023, 1, 1)
    n.summary = "New Summary"
    assert n.url == "http://b.com"
    assert n.title == "New Title"
    assert n.content == "New Content"
    assert n.upload_time == date(2023, 1, 1)
    assert n.summary == "New Summary"


def test_notice_default_upload_time(monkeypatch):
    today = date(2024, 6, 1)
    monkeypatch.setattr("src.entry.notice.date", type("MockDate", (), {"today": staticmethod(lambda: today)}))
    n = Notice(url="http://a.com")
    assert n.upload_time == today


def test_builder_success():
    builder = Notice.Builder()
    n = (builder
         .set_url("http://builder.com")
         .set_title("Builder Title")
         .set_content("Builder Content")
         .set_upload_time(date(2022, 2, 2))
         .set_summary("Builder Summary")
         .build())
    assert n.url == "http://builder.com"
    assert n.title == "Builder Title"
    assert n.content == "Builder Content"
    assert n.upload_time == date(2022, 2, 2)
    assert n.summary == "Builder Summary"


def test_builder_missing_url():
    builder = Notice.Builder()
    with pytest.raises(ValueError):
        builder.build()
