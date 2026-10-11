"""OpenAI 兼容的对话补全客户端（流式 + 非流式）。"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Dict, List, Optional

import httpx

from .embeddings import endpoint
from .settings import Settings

log = logging.getLogger("dcai.llm")


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        cfg = settings.llm
        self.base_url = cfg.base_url
        self.model = cfg.model
        self.temperature = cfg.temperature
        self.max_tokens = cfg.max_tokens
        self.timeout = cfg.timeout
        self.api_key = settings.llm_api_key

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _payload(self, messages: List[Dict[str, str]], stream: bool) -> Dict:
        return {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }

    async def complete(self, messages: List[Dict[str, str]]) -> str:
        if not self.enabled:
            raise LLMError("未配置 LLM_API_KEY")
        url = endpoint(self.base_url, "/chat/completions")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                url, headers=self._headers(), json=self._payload(messages, stream=False)
            )
            if resp.status_code >= 400:
                raise LLMError(f"HTTP {resp.status_code}: {resp.text[:400]}")
            data = resp.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"响应格式异常: {str(data)[:300]}") from exc

    async def stream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        if not self.enabled:
            raise LLMError("未配置 LLM_API_KEY")
        url = endpoint(self.base_url, "/chat/completions")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", url, headers=self._headers(), json=self._payload(messages, stream=True)
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "ignore")
                    raise LLMError(f"HTTP {resp.status_code}: {body[:400]}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield piece

    async def health(self) -> Optional[str]:
        """返回 None 表示正常，否则返回错误说明。"""
        if not self.enabled:
            return "未配置 LLM_API_KEY（当前为纯检索模式）"
        try:
            await self.complete([{"role": "user", "content": "ping"}])
            return None
        except Exception as exc:  # noqa: BLE001
            return str(exc)[:200]
