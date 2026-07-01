from datetime import datetime

import pytest

from src.notice_push.models import Attachment, NoticeDetail
from src.notice_push.summarizer import NoticeSummarizer, load_prompt


class _FakeMessage:
    def __init__(self, content: str = "## 官网|行政|周常事务|测试通知"):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str = "## 官网|行政|周常事务|测试通知"):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str = "## 官网|行政|周常事务|测试通知"):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self):
        self.last_request = None
        self.requests = []

    def create(self, **kwargs):
        self.last_request = kwargs
        self.requests.append(kwargs)
        return _FakeResponse()


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat()


class _FlakyCompletions:
    def __init__(self):
        self.calls = 0
        self.last_request = None

    def create(self, **kwargs):
        self.calls += 1
        self.last_request = kwargs
        if self.calls < 3:
            raise RuntimeError("rate limited")
        return _FakeResponse()


class _EmptyCompletions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return _FakeResponse("")


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


def test_summarizer_caches_prompt_for_repeated_summaries(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    prompt_path = prompt_dir / "notice_summary_v1.md"
    prompt_path.write_text("第一版系统提示词", encoding="utf-8")
    fake_client = _FakeClient()
    summarizer = NoticeSummarizer(
        prompt_dir=prompt_dir,
        prompt_name="notice_summary_v1",
        model="test-model",
        client=fake_client,
    )

    summarizer.summarize(1, make_detail())
    prompt_path.write_text("第二版系统提示词", encoding="utf-8")
    summarizer.summarize(2, make_detail())

    system_prompts = [request["messages"][0]["content"] for request in fake_client.chat.completions.requests]
    assert system_prompts == ["第一版系统提示词", "第一版系统提示词"]


def test_summarizer_retries_with_exponential_backoff_and_timeout(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "notice_summary_v1.md").write_text("系统提示词", encoding="utf-8")
    fake_client = _FakeClient()
    fake_client.chat.completions = _FlakyCompletions()
    sleep_calls = []
    monkeypatch.setattr("src.notice_push.summarizer.time.sleep", sleep_calls.append)
    summarizer = NoticeSummarizer(
        prompt_dir=prompt_dir,
        prompt_name="notice_summary_v1",
        model="test-model",
        client=fake_client,
        timeout=45,
        max_retries=3,
        initial_retry_delay=0.5,
        retry_backoff=2.0,
    )

    summary = summarizer.summarize(42, make_detail())

    assert summary.markdown == "## 官网|行政|周常事务|测试通知"
    assert fake_client.chat.completions.calls == 3
    assert fake_client.chat.completions.last_request["timeout"] == 45
    assert sleep_calls == [0.5, 1.0]


def test_summarizer_treats_empty_model_response_as_failure(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "notice_summary_v1.md").write_text("系统提示词", encoding="utf-8")
    fake_client = _FakeClient()
    fake_client.chat.completions = _EmptyCompletions()
    summarizer = NoticeSummarizer(
        prompt_dir=prompt_dir,
        prompt_name="notice_summary_v1",
        model="test-model",
        client=fake_client,
        max_retries=2,
        initial_retry_delay=0,
    )

    with pytest.raises(ValueError, match="empty summary"):
        summarizer.summarize(42, make_detail())

    assert fake_client.chat.completions.calls == 2


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
