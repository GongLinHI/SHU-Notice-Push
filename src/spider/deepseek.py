import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

from src.entry.notice import Notice
from src.notice_push.config import load_config
from src.notice_push.models import NoticeDetail
from src.notice_push.summarizer import NoticeSummarizer, load_prompt


class DeepSeekClient:
    _BASE_URL = "https://api.deepseek.com"
    _DEFAULT_MODEL = "deepseek-v4-flash"
    _ENV_DEEPSEEK_API_KEY = "DEEPSEEK_API_KEY"
    _ENV_DEEPSEEK_MODEL = "DEEPSEEK_MODEL"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        load_dotenv()
        # 优先从环境变量读取
        self._api_key = api_key or os.getenv(self._ENV_DEEPSEEK_API_KEY)
        # print(f"API Key: {self._api_key}")
        if not self._api_key:
            raise ValueError("DeepSeek API key must be provided via argument or DEEPSEEK_API_KEY environment variable")
        self._model = model or os.getenv(self._ENV_DEEPSEEK_MODEL, self._DEFAULT_MODEL)
        self._client = OpenAI(api_key=self._api_key, base_url=self._BASE_URL)

    # region Property Getters
    @property
    def api_key(self) -> str:
        """获取当前使用的API Key"""
        return self._api_key

    @property
    def model(self) -> str:
        """获取当前使用的模型名称"""
        return self._model

    @property
    def client(self) -> OpenAI:
        """获取OpenAI客户端实例（只读）"""
        return self._client

    # endregion
    # region Setters
    @api_key.setter
    def api_key(self, value: str) -> None:
        """设置新的API Key并重置客户端连接"""
        self._api_key = value
        self._client = OpenAI(api_key=value, base_url=self._BASE_URL)

    @model.setter
    def model(self, value: str) -> None:
        """设置新的模型名称"""
        if not isinstance(value, str):
            raise TypeError("Model name must be a string")
        self._model = value

    def chat(self, user_prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Chat with the DeepSeek API.
        """
        response = self.client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system",
                 "content": "You are a helpful assistant" if system_prompt is None else system_prompt},
                {"role": "user",
                 "content": user_prompt},
            ],
            stream=False
        )
        content = response.choices[0].message.content
        return content


class DeepSeekSummary:
    _client = None
    _system_prompt = None

    @classmethod
    def get_client(cls) -> DeepSeekClient:
        if cls._client is None:
            cls._client = DeepSeekClient()
        return cls._client

    @classmethod
    def set_system_prompt(cls, prompt_name: str = "notice_summary_v1"):
        """
        设置系统提示词。旧接口保留为兼容层，实际读取新的版本化 prompt。
        """
        prompt_dir = Path(__file__).parent.parent.parent.joinpath("resources", "prompts")
        cls._system_prompt = load_prompt(prompt_dir, prompt_name)

    @classmethod
    def get_summary(cls, notice: Notice):
        """
        获取通知公告的摘要。旧接口委托给新的 NoticeSummarizer，避免维护两套摘要链路。
        """
        config = load_config()
        summarizer = NoticeSummarizer(
            prompt_dir=config.repo_root / "resources" / "prompts",
            prompt_name=config.prompt_name,
            model=config.deepseek_model,
        )
        detail = NoticeDetail(
            source_id="shu_official",
            url=notice.url,
            canonical_url=notice.url,
            title=notice.title or "",
            content=notice.content or "",
            published_at=None,
        )
        return summarizer.summarize(0, detail, source_name="上海大学官网").markdown
