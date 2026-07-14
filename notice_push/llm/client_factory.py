from __future__ import annotations

import threading

from openai import OpenAI


class OpenAIClientProvider:
    def __init__(
        self,
        *,
        client,
        api_key: str | None,
        base_url: str | None,
        provider_name: str,
    ):
        self._client = client
        self._api_key = api_key
        self._base_url = base_url
        self._provider_name = provider_name
        self._lock = threading.Lock()

    def get(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError(
                f"api_key must be provided for provider '{self._provider_name}'"
            )
        if not self._base_url:
            raise ValueError(
                f"base_url must be provided for provider '{self._provider_name}'"
            )
        with self._lock:
            if self._client is None:
                self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client
