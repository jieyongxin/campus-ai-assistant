"""检索增强问答主流程。"""

from __future__ import annotations

import logging
import re
import time
from typing import AsyncIterator, Dict, List, Optional, Sequence

from .index_store import Hit, Index
from .llm import LLMClient
from .prompt import build_messages, extractive_answer, no_hit_answer
from .settings import Settings
from .textutil import truncate

log = logging.getLogger("dcai.rag")

_INJECTION = re.compile(
    r"(忽略(以上|之前|前面)(所有)?(的)?(指令|规则|提示)|"
    r"你是(一个)?(?!校园)[^，。]{0,6}(助手|模型|AI)|"
    r"输出(你的)?(系统)?(提示词|prompt|指令)|"
    r"扮演|越狱|jailbreak|dan模式)",
    re.IGNORECASE,
)

_REFUSAL = (
    "我是{name}的校园客服助手，只能帮您查询学校的招生、专业、教务、校园生活等信息。\n\n"
    "关于其他类型的问题，建议换一个更合适的工具或渠道～有校园相关的问题随时问我。"
)


class ChatEngine:
    def __init__(self, settings: Settings, index: Optional[Index], llm: LLMClient):
        self.settings = settings
        self.index = index
        self.llm = llm

    def set_index(self, index: Optional[Index]) -> None:
        self.index = index

    def _history(self, history: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
        limit = max(0, self.settings.chat.history_turns) * 2
        cleaned: List[Dict[str, str]] = []
        for turn in history[-limit:] if limit else []:
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                cleaned.append({"role": role, "content": truncate(content, 1200)})
        return cleaned

    async def retrieve(self, question: str) -> List[Hit]:
        if self.index is None or not self.index.ready:
            return []
        try:
            return await self.index.search(question)
        except Exception as exc:  # noqa: BLE001
            log.exception("检索失败: %s", exc)
            return []

    @staticmethod
    def _last_user_question(history: Sequence[Dict[str, str]]) -> str:
        for turn in reversed(list(history)):
            if turn.get("role") == "user" and turn.get("content"):
                return turn["content"]
        return ""

    async def astream(
        self, question: str, history: Sequence[Dict[str, str]] | None = None
    ) -> AsyncIterator[Dict]:
        """产出事件：sources / delta / done。"""
        started = time.perf_counter()
        question = (question or "").strip()
        name = self.settings.school.assistant_name

        if not question:
            yield {"type": "delta", "text": "请先输入你想咨询的问题～"}
            yield {"type": "done", "mode": "empty", "latency_ms": 0}
            return

        if _INJECTION.search(question):
            yield {"type": "sources", "items": []}
            yield {"type": "delta", "text": _REFUSAL.format(name=name)}
            yield {
                "type": "done",
                "mode": "guard",
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
            return

        turns = self._history(history or [])
        hits = await self.retrieve(question)

        # 追问场景：出现"那……呢""那边""这个"等指代时，单轮检索会落空，
        # 这里用上一轮用户问题补全一次，避免答不上来。
        if not hits and turns:
            previous = self._last_user_question(turns)
            if previous:
                hits = await self.retrieve(f"{previous} {question}")
                if hits:
                    question = f"{previous} {question}"

        yield {"type": "sources", "items": [h.to_dict(with_text=False) for h in hits]}

        if not hits:
            yield {"type": "delta", "text": no_hit_answer(self.settings)}
            yield {
                "type": "done",
                "mode": "no_hit",
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
            return

        if not self.llm.enabled:
            text = extractive_answer(hits)
            note = "> 当前运行在**纯检索模式**（未配置大模型 API Key），以下是从知识库中命中的原文：\n\n"
            yield {"type": "delta", "text": note + text}
            yield {
                "type": "done",
                "mode": "retrieval",
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
            return

        messages = build_messages(self.settings, hits, turns, question)
        produced = False
        try:
            async for piece in self.llm.stream(messages):
                produced = True
                yield {"type": "delta", "text": piece}
        except Exception as exc:  # noqa: BLE001
            log.warning("大模型调用失败：%s", exc)
            if not produced:
                hint = f"> 大模型暂时不可用（{truncate(str(exc), 120)}），以下是知识库命中的原文：\n\n"
                yield {"type": "delta", "text": hint + extractive_answer(hits)}
                yield {
                    "type": "done",
                    "mode": "llm_error",
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                }
                return

        yield {
            "type": "done",
            "mode": "rag",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    async def answer(
        self, question: str, history: Sequence[Dict[str, str]] | None = None
    ) -> Dict:
        """非流式版本，供挂件或第三方系统调用。"""
        sources: List[Dict] = []
        parts: List[str] = []
        mode = "rag"
        latency = 0
        async for event in self.astream(question, history):
            if event["type"] == "sources":
                sources = event["items"]
            elif event["type"] == "delta":
                parts.append(event["text"])
            elif event["type"] == "done":
                mode = event.get("mode", mode)
                latency = event.get("latency_ms", 0)
        return {
            "answer": "".join(parts),
            "sources": sources,
            "mode": mode,
            "latency_ms": latency,
        }
