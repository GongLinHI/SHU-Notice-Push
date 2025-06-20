from dotenv import load_dotenv

load_dotenv()  # 默认会加载根目录下的.env文件

import os
from pathlib import Path
from typing import Optional

from openai import OpenAI

from src.entry.notice import Notice


class DeepSeekClient:
    _BASE_URL = "https://api.deepseek.com"
    _DEFAULT_MODEL = "deepseek-chat"
    _ENV_DEEPSEEK_API_KEY = "DEEPSEEK_API_KEY"
    _ENV_DEEPSEEK_MODEL = "DEEPSEEK_MODEL"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
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
    _client = DeepSeekClient()
    _system_prompt = None

    @classmethod
    def set_system_prompt(cls):
        """
        设置系统提示词
        """
        path = Path(__file__).parent.parent.parent.joinpath('resources/system_prompt.md')
        if not path.exists():
            raise FileNotFoundError(f"System prompt file not found: {path}")
        with path.open('r', encoding='utf-8') as file:
            cls._system_prompt = file.read()
            # print(cls._system_prompt)

    @classmethod
    def get_summary(cls, notice: Notice):
        """
        获取通知公告的摘要
        """
        if cls._system_prompt is None:
            cls.set_system_prompt()

        user_prompt = \
            f'''
- 标题：{notice.title}
- 发布时间：{notice.upload_time}
- 正文：{notice.content}
- url：{notice.url}
'''
        response_text = cls._client.chat(system_prompt=cls._system_prompt, user_prompt=user_prompt)
        return response_text
