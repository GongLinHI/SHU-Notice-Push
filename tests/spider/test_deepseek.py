from datetime import date

from src.entry.notice import Notice
from src.spider.deepseek import DeepSeekClient, DeepSeekSummary


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


class _FakeOpenAIClient:
    def __init__(self):
        self.chat = _FakeChat()


class TestDeepSeekClient:
    def test_chat_uses_configured_model_and_prompts_without_real_api_call(self):
        client = DeepSeekClient(api_key="test-api-key", model="test-model")
        fake_client = _FakeOpenAIClient()
        client._client = fake_client

        response_text = client.chat(
            system_prompt="system prompt",
            user_prompt="user prompt",
        )

        assert response_text == "## 官网|行政|周常事务|测试通知"
        assert fake_client.chat.completions.last_request == {
            "model": "test-model",
            "messages": [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "user prompt"},
            ],
            "stream": False,
        }


def test_legacy_summary_uses_versioned_prompt_file():
    DeepSeekSummary._system_prompt = None

    DeepSeekSummary.set_system_prompt()

    assert "目录页摘要只能作为辅助线索" in DeepSeekSummary._system_prompt


def test_legacy_summary_delegates_to_notice_summarizer(monkeypatch):
    calls = {}

    class FakeSummarizer:
        def summarize(self, notice_id, detail, source_name=None):
            calls["notice_id"] = notice_id
            calls["detail"] = detail
            calls["source_name"] = source_name

            class Summary:
                markdown = "## 上海大学官网|行政|周常事务|测试通知"

            return Summary()

    monkeypatch.setattr("src.spider.deepseek.NoticeSummarizer", lambda **kwargs: FakeSummarizer())

    notice = Notice(
        url="https://www.shu.edu.cn/info/1051/397035.htm",
        title="测试通知",
        content="详情页正文",
        upload_time=date(2026, 6, 30),
    )

    assert DeepSeekSummary.get_summary(notice) == "## 上海大学官网|行政|周常事务|测试通知"
    assert calls["notice_id"] == 0
    assert calls["source_name"] == "上海大学官网"
    assert calls["detail"].content == "详情页正文"
