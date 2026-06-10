"""
通用 LLM 客户端 - 支持 DeepSeek 及任意 OpenAI 兼容 API

默认连接 DeepSeek API（OpenAI 兼容格式），通过环境变量切换服务商:
  LLM_BASE_URL  → 默认 https://api.deepseek.com
  LLM_API_KEY   → API Key
  LLM_MODEL     → 默认 deepseek-chat

兼容 OpenAI / DeepSeek / 通义千问 / 智谱 等所有 OpenAI 格式 API。
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


class LLMClient:
    """
    通用 OpenAI 兼容 LLM 客户端

    API 格式: POST /v1/chat/completions
    文档: https://api-docs.deepseek.com/
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = "deepseek-chat",
    ):
        self.base_url = base_url or os.getenv(
            "LLM_BASE_URL", "https://api.deepseek.com"
        ).rstrip("/")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL", "deepseek-chat")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self._client = httpx.AsyncClient(timeout=120.0, headers=headers)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        """
        调用 LLM 聊天接口

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            temperature: 温度参数
            max_tokens: 最大生成 token 数
            response_format: 输出格式约束 (如 {"type": "json_object"})

        Returns:
            模型生成的文本
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        url = f"{self.base_url}/v1/chat/completions"
        response = await self._client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        if "choices" in data and len(data["choices"]) > 0:
            content = data["choices"][0]["message"]["content"]
            return content

        logger.error(f"LLM API unexpected response: {data}")
        raise ValueError(f"Unexpected API response: {data}")

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict:
        """调用聊天接口并解析 JSON 输出"""
        text = await self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # JSON 解析失败的降级：尝试截取 {...} 片段
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
            raise

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
