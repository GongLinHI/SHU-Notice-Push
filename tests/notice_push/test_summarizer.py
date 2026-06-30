from datetime import datetime

import pytest

from src.notice_push.models import Attachment, NoticeDetail
from src.notice_push.summarizer import NoticeSummarizer, load_prompt


class _FakeMessage:
    content = "## 官网|行政|周常事务|测试通知"


class _FakeChoice:
    message = _FakeMessage()


class _FakeResponse:
    choices = [_FakeChoice()]


class _FakeCompletions:
    def __init__(self):
        self.last_request = None

    def create(self, **kwargs):
        self.last_request = kwargs
        return _FakeResponse()


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat()


def make_detail(content: str = "详情页正文包含完整办理要求。") -> NoticeDetail:
    return NoticeDetail(
        source_id="shu_official",
        url="https://www.shu.edu.cn/info/1051/397035.htm",
        canonical_url="https://www.shu.edu.cn/info/1051/397035.htm",
        title="关于宝山校区部分楼宇停电的通知",
        content=content,
        published_at=datetime(2026, 6, 16),
        list_excerpt="目录页摘要不应替代正文",
        attachments=(Attachment(name="附件.pdf", url="https://example.com/a.pdf"),),
    )


def test_load_prompt_reads_named_prompt(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "notice_summary_v1.md").write_text("系统提示词", encoding="utf-8")

    assert load_prompt(prompt_dir, "notice_summary_v1") == "系统提示词"


def test_load_prompt_rejects_missing_prompt(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_prompt(tmp_path, "missing")


def test_summarizer_uses_detail_content_and_fake_client(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "notice_summary_v1.md").write_text("系统提示词", encoding="utf-8")
    fake_client = _FakeClient()
    summarizer = NoticeSummarizer(
        prompt_dir=prompt_dir,
        prompt_name="notice_summary_v1",
        model="test-model",
        client=fake_client,
    )

    summary = summarizer.summarize(42, make_detail())

    assert summary.notice_id == 42
    assert summary.markdown == "## 官网|行政|周常事务|测试通知"
    request = fake_client.chat.completions.last_request
    assert request["model"] == "test-model"
    assert request["messages"][0] == {"role": "system", "content": "系统提示词"}
    assert "详情页正文包含完整办理要求。" in request["messages"][1]["content"]
    assert "目录页摘要不应替代正文" in request["messages"][1]["content"]


def test_summarizer_rejects_empty_detail_content_without_using_excerpt(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "notice_summary_v1.md").write_text("系统提示词", encoding="utf-8")
    summarizer = NoticeSummarizer(
        prompt_dir=prompt_dir,
        prompt_name="notice_summary_v1",
        model="test-model",
        client=_FakeClient(),
    )

    with pytest.raises(ValueError, match="detail content"):
        summarizer.summarize(1, make_detail(content=""))


def test_summarizer_requires_api_key_only_when_real_client_is_needed(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "notice_summary_v1.md").write_text("系统提示词", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    summarizer = NoticeSummarizer(
        prompt_dir=prompt_dir,
        prompt_name="notice_summary_v1",
        model="test-model",
    )

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        summarizer.summarize(1, make_detail())
