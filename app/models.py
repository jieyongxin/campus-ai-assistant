"""请求 / 响应模型。"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., description="用户问题")
    session_id: Optional[str] = None


class SourceOut(BaseModel):
    id: str
    source: str
    title: str
    section: str
    score: float
    coverage: float = 0.0


class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceOut] = []
    mode: str = "rag"
    session_id: str = ""
    latency_ms: int = 0


class FeedbackRequest(BaseModel):
    session_id: Optional[str] = None
    question: str = ""
    answer: str = ""
    rating: str = Field("up", description="up / down")
    comment: str = ""


class SessionResetRequest(BaseModel):
    session_id: str
