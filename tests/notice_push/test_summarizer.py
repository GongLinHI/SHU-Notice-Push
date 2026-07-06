from datetime import datetime

import pytest

from notice_push.domain import Attachment, MediaPolicy, NoticeAsset, NoticeDetail
from notice_push.llm.kimi import KimiMultimodalSummarizer
from notice_push.llm.prompts import load_prompt, render_notice_user_prompt
from notice_push.llm.router import SummarizerRouter
from notice_push.llm.text import NoticeSummarizer
from notice_push.summary_validator import normalize_summary_markdown, validate_summary_markdown


VALID_SUMMARY = "\n".join(
    [
        "## 官网|行政|周常事务|测试通知",
        "- **发布时间**: 2026-06-16",
        "- **影响对象**: 全校师生",
        "- **核心信息**: 测试通知核心内容",
        "- **行动指引**: 按要求办理",
        "- **截止时间**: 未提及",
        "- **相关链接**: 未提及",
    ]
)


class _FakeMessage:
    def __init__(self, content: str = VALID_SUMMARY):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str = VALID_SUMMARY):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str = VALID_SUMMARY):
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


class _FakeFileObject:
    def __init__(self, file_id: str):
        self.id = file_id


class _FakeFileContent:
    def __init__(self, text: str):
        self.text = text


class _FakeFiles:
    def __init__(self, extracted_text: str = "PDF 正文内容"):
        self.create_requests = []
        self.content_requests = []
        self.delete_requests = []
        self.extracted_text = extracted_text

    def create(self, **kwargs):
        self.create_requests.append(kwargs)
        return _FakeFileObject("file-test-1")

    def content(self, **kwargs):
        self.content_requests.append(kwargs)
        return _FakeFileContent(self.extracted_text)

    def delete(self, **kwargs):
        self.delete_requests.append(kwargs)


class _FakeKimiClient(_FakeClient):
    def __init__(self, extracted_text: str = "PDF 正文内容"):
        super().__init__()
        self.files = _FakeFiles(extracted_text=extracted_text)


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


class _InvalidSummaryCompletions:
    def create(self, **kwargs):
        return _FakeResponse("## 官网|行政|周常事务|测试通知\n- 缺少结构化字段")


class _RepairableSummaryCompletions:
    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) == 1:
            return _FakeResponse("## 官网|行政|周常事务|测试通知\n- 缺少结构化字段")
        return _FakeResponse(VALID_SUMMARY)


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


def make_pdf_detail() -> NoticeDetail:
    return NoticeDetail(
        source_id="management_school",
        url="https://ms.shu.edu.cn/info/1245/91745.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91745.htm",
        title="巡察公告",
        content="",
        assets=(
            NoticeAsset(
                kind="pdf",
                role="primary",
                name="巡察公告.pdf",
                url="https://example.com/inspection.pdf",
                mime_type="application/pdf",
            ),
        ),
        content_kind="pdf",
    )


def make_image_detail() -> NoticeDetail:
    return NoticeDetail(
        source_id="management_school",
        url="https://ms.shu.edu.cn/info/1245/91475.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91475.htm",
        title="管理学院2026年寒假值班安排",
        content="",
        assets=(
            NoticeAsset(
                kind="image",
                role="primary",
                name="值班安排.png",
                url="https://example.com/duty.png",
                mime_type="image/png",
            ),
        ),
        content_kind="image",
    )


def test_render_notice_user_prompt_includes_assets_when_attachments_are_empty():
    detail = NoticeDetail(
        source_id="management_school",
        url="https://ms.shu.edu.cn/info/1245/91745.htm",
        canonical_url="https://ms.shu.edu.cn/info/1245/91745.htm",
        title="巡察公告",
        content="",
        assets=(
            NoticeAsset(
                kind="pdf",
                role="primary",
                name="巡察公告.pdf",
                url="https://ms.shu.edu.cn/__local/inspection.pdf",
                mime_type="application/pdf",
            ),
        ),
        content_kind="pdf",
    )

    prompt = render_notice_user_prompt(detail, source_name="上海大学管理学院")

    assert "- 巡察公告.pdf: https://ms.shu.edu.cn/__local/inspection.pdf" in prompt


def test_load_prompt_reads_named_prompt(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "notice_summary_v1.md").write_text("系统提示词", encoding="utf-8")

    assert load_prompt(prompt_dir, "notice_summary_v1") == "系统提示词"


def test_load_prompt_rejects_missing_prompt(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_prompt(tmp_path, "missing")


def test_summary_validator_normalizes_full_width_colon_fields():
    markdown = "\n".join(
        [
            "## 官网|行政|周常事务|测试通知",
            "- **发布时间：** 2026-06-16",
            "- **影响对象：** 全校师生",
            "- **核心信息：** 核心内容",
            "- **行动指引：** 按要求办理",
            "- **截止时间：** 未提及",
            "- **相关链接：** 未提及",
        ]
    )

    normalized = normalize_summary_markdown(markdown)

    assert "- **发布时间**: 2026-06-16" in normalized
    validate_summary_markdown(normalized)


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
    assert summary.markdown == VALID_SUMMARY
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
    monkeypatch.setattr("notice_push.llm.chat.time.sleep", sleep_calls.append)
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

    assert summary.markdown == VALID_SUMMARY
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


def test_summarizer_rejects_invalid_summary_markdown(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "notice_summary_v1.md").write_text("系统提示词", encoding="utf-8")
    fake_client = _FakeClient()
    fake_client.chat.completions = _InvalidSummaryCompletions()
    summarizer = NoticeSummarizer(
        prompt_dir=prompt_dir,
        prompt_name="notice_summary_v1",
        model="test-model",
        client=fake_client,
        max_retries=1,
    )

    with pytest.raises(ValueError, match="summary missing required field"):
        summarizer.summarize(42, make_detail())


def test_summarizer_repairs_invalid_summary_format_once(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "notice_summary_v1.md").write_text("系统提示词", encoding="utf-8")
    fake_client = _FakeClient()
    fake_client.chat.completions = _RepairableSummaryCompletions()
    summarizer = NoticeSummarizer(
        prompt_dir=prompt_dir,
        prompt_name="notice_summary_v1",
        model="test-model",
        client=fake_client,
        summary_format_repair_retries=1,
    )

    summary = summarizer.summarize(42, make_detail())

    assert summary.markdown == VALID_SUMMARY
    assert len(fake_client.chat.completions.requests) == 2
    assert "待修复摘要" in fake_client.chat.completions.requests[1]["messages"][1]["content"]


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


def test_summarizer_router_sends_text_details_to_text_summarizer(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "notice_summary_v1.md").write_text("系统提示词", encoding="utf-8")
    text_client = _FakeClient()
    kimi_client = _FakeKimiClient()
    router = SummarizerRouter(
        text_summarizer=NoticeSummarizer(
            prompt_dir=prompt_dir,
            prompt_name="notice_summary_v1",
            model="deepseek-test",
            client=text_client,
        ),
        kimi_summarizer=KimiMultimodalSummarizer(
            prompt_dir=prompt_dir,
            prompt_name="notice_summary_v1",
            model="kimi-test",
            client=kimi_client,
            downloader=lambda asset: tmp_path / "unused.bin",
        ),
        routing={"text": "deepseek", "pdf": "kimi", "image": "kimi"},
    )

    summary = router.summarize(7, make_detail(), source_name="上海大学官网")

    assert summary.model == "deepseek-test"
    assert text_client.chat.completions.last_request["model"] == "deepseek-test"
    assert kimi_client.chat.completions.last_request is None


def test_kimi_pdf_summarizer_extracts_file_content_before_chat(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "notice_summary_v1.md").write_text("系统提示词", encoding="utf-8")
    pdf_path = tmp_path / "notice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    fake_client = _FakeKimiClient(extracted_text="巡察公告 PDF 正文")
    summarizer = KimiMultimodalSummarizer(
        prompt_dir=prompt_dir,
        prompt_name="notice_summary_v1",
        model="kimi-k2.7-code",
        client=fake_client,
        downloader=lambda asset: pdf_path,
    )

    summary = summarizer.summarize(8, make_pdf_detail(), source_name="上海大学管理学院")

    assert summary.notice_id == 8
    assert summary.model == "kimi-k2.7-code"
    assert fake_client.files.create_requests == [{"file": pdf_path, "purpose": "file-extract"}]
    assert fake_client.files.content_requests == [{"file_id": "file-test-1"}]
    assert fake_client.files.delete_requests == [{"file_id": "file-test-1"}]
    request = fake_client.chat.completions.last_request
    assert request["model"] == "kimi-k2.7-code"
    assert request["messages"][0] == {"role": "system", "content": "系统提示词"}
    assert request["messages"][1] == {"role": "system", "content": "巡察公告 PDF 正文"}
    assert "巡察公告" in request["messages"][2]["content"]
    assert "正文：巡察公告 PDF 正文" not in request["messages"][2]["content"]
    assert "temperature" not in request
    assert "thinking" not in request


def test_kimi_pdf_summarizer_limits_extracted_text_before_chat(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "notice_summary_v1.md").write_text("系统提示词", encoding="utf-8")
    pdf_path = tmp_path / "notice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    fake_client = _FakeKimiClient(extracted_text="abcdefghij")
    summarizer = KimiMultimodalSummarizer(
        prompt_dir=prompt_dir,
        prompt_name="notice_summary_v1",
        model="kimi-k2.7-code",
        client=fake_client,
        downloader=lambda asset: pdf_path,
        media_policy=MediaPolicy(pdf_extracted_text_max_chars=4),
    )

    summarizer.summarize(8, make_pdf_detail(), source_name="上海大学管理学院")

    assert fake_client.chat.completions.last_request["messages"][1] == {
        "role": "system",
        "content": "abcd",
    }


def test_kimi_image_summarizer_sends_openai_compatible_image_message(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "notice_summary_v1.md").write_text("系统提示词", encoding="utf-8")
    image_path = tmp_path / "notice.png"
    image_path.write_bytes(b"fake image bytes")
    fake_client = _FakeKimiClient()
    summarizer = KimiMultimodalSummarizer(
        prompt_dir=prompt_dir,
        prompt_name="notice_summary_v1",
        model="kimi-k2.7-code",
        client=fake_client,
        downloader=lambda asset: image_path,
    )

    summarizer.summarize(9, make_image_detail(), source_name="上海大学管理学院")

    request = fake_client.chat.completions.last_request
    content = request["messages"][1]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1]["type"] == "text"
    assert "管理学院2026年寒假值班安排" in content[1]["text"]
    assert "temperature" not in request
    assert "thinking" not in request
