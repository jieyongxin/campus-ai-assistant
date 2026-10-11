"""对话相关接口。"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..models import ChatRequest, ChatResponse, FeedbackRequest, SessionResetRequest

log = logging.getLogger("dcai.chat")
router = APIRouter(prefix="/api", tags=["chat"])


def client_id(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/meta")
async def meta(request: Request) -> Dict[str, Any]:
    s = request.app.state.settings
    index = request.app.state.index
    return {
        "school": {
            "name": s.school.name,
            "short_name": s.school.short_name,
            "assistant_name": s.school.assistant_name,
            "website": s.school.website,
            "hotline": s.school.hotline,
            "admissions_phone": s.school.admissions_phone,
            "service_hours": s.school.service_hours,
        },
        "brand": s.brand.model_dump(),
        "quick_questions": s.quick_questions,
        "llm_enabled": s.llm_enabled,
        "llm_model": s.llm.model if s.llm_enabled else "",
        "index": {
            "ready": bool(index and index.ready),
            "chunks": index.meta.get("chunks", 0) if index else 0,
            "documents": index.meta.get("documents", 0) if index else 0,
            "provider": index.meta.get("provider", "") if index else "",
            "built_at": index.meta.get("built_at", "") if index else "",
            "stale": index.is_stale() if index else False,
        },
    }


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request) -> ChatResponse:
    state = request.app.state
    s = state.settings
    if not state.limiter.allow(client_id(request)):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    question = req.question.strip()[: s.chat.max_question_chars]
    sid = state.sessions.ensure(req.session_id)
    history = state.sessions.history(sid)

    result = await state.engine.answer(question, history)
    state.sessions.append(sid, question, result["answer"])
    state.store.log_answer(
        sid,
        question,
        result["answer"],
        result["mode"],
        result["sources"],
        result["latency_ms"],
        client_id(request),
    )
    return ChatResponse(session_id=sid, **result)


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    state = request.app.state
    s = state.settings
    if not state.limiter.allow(client_id(request)):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    question = req.question.strip()[: s.chat.max_question_chars]
    sid = state.sessions.ensure(req.session_id)
    history = state.sessions.history(sid)
    who = client_id(request)

    async def gen():
        collected: List[str] = []
        sources: List[Dict] = []
        mode = "rag"
        latency = 0
        try:
            async for event in state.engine.astream(question, history):
                if event["type"] == "sources":
                    sources = event["items"]
                elif event["type"] == "delta":
                    collected.append(event["text"])
                elif event["type"] == "done":
                    mode = event.get("mode", mode)
                    latency = event.get("latency_ms", 0)
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001
            log.exception("流式回答失败")
            mode = "error"
            yield _sse({"type": "error", "message": str(exc)[:200]})
        finally:
            answer = "".join(collected)
            if answer:
                state.sessions.append(sid, question, answer)
                try:
                    state.store.log_answer(
                        sid, question, answer, mode, sources, latency, who
                    )
                except Exception:  # noqa: BLE001
                    log.exception("写日志失败")
        try:
            yield _sse(
                {
                    "type": "end",
                    "session_id": sid,
                    "mode": mode,
                    "latency_ms": latency,
                }
            )
        except RuntimeError:  # 客户端已断开
            pass

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/feedback")
async def feedback(req: FeedbackRequest, request: Request) -> Dict[str, str]:
    state = request.app.state
    state.store.log_feedback(
        req.session_id or "",
        req.question,
        req.answer,
        req.rating,
        req.comment,
    )
    return {"status": "ok"}


@router.post("/session/reset")
async def reset(req: SessionResetRequest, request: Request) -> Dict[str, str]:
    request.app.state.sessions.clear(req.session_id)
    return {"status": "ok"}


@router.get("/health")
async def health(request: Request) -> Dict[str, Any]:
    s = request.app.state.settings
    index = request.app.state.index
    return {
        "status": "ok",
        "llm_enabled": s.llm_enabled,
        "index_ready": bool(index and index.ready),
        "index_stale": index.is_stale() if index else True,
        "active_sessions": request.app.state.sessions.active,
    }
