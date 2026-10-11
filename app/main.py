"""FastAPI 入口。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .index_store import Index, build_index
from .llm import LLMClient
from .rag import ChatEngine
from .ratelimit import RateLimiter
from .routers import admin, chat
from .sessions import SessionStore
from .settings import get_settings
from .store import LogStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("dcai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.index_dir.mkdir(parents=True, exist_ok=True)

    index = Index.load(settings)
    if index is None:
        log.info("未发现索引，正在首次构建…")
        try:
            await build_index(settings)
            index = Index.load(settings)
        except Exception as exc:  # noqa: BLE001
            log.error("索引构建失败：%s", exc)

    app.state.settings = settings
    app.state.index = index
    app.state.llm = LLMClient(settings)
    app.state.engine = ChatEngine(settings, index, app.state.llm)
    app.state.sessions = SessionStore(
        ttl=settings.chat.session_ttl, max_turns=max(settings.chat.history_turns * 4, 12)
    )
    app.state.limiter = RateLimiter(settings.chat.rate_limit_per_minute)
    app.state.store = LogStore(settings.db_path)

    log.info(
        "启动完成 | 学校=%s | 知识片段=%s | 大模型=%s",
        settings.school.name,
        index.meta.get("chunks") if index else 0,
        settings.llm.model if settings.llm_enabled else "未配置（纯检索模式）",
    )
    if index and index.is_stale():
        log.warning("知识库已变更但索引未更新，请调用 POST /api/admin/reindex")

    try:
        yield
    finally:
        app.state.store.close()


app = FastAPI(
    title="校园 AI 客服",
    description="基于 RAG 的高校智能问答服务",
    version="0.1.0",
    lifespan=lifespan,
)

# 允许的跨域来源来自 config.yaml 的 server.cors_origins（原先硬编码为 ["*"]，
# 配置项写了也不生效）。同源访问（页面由本服务托管）不受 CORS 限制。
_cors_origins = get_settings().server.cors_origins or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(admin.router)


@app.exception_handler(Exception)
async def unhandled(request, exc):  # noqa: ANN001, ANN201
    log.exception("未处理异常: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "服务内部错误"})


_web = Path(__file__).resolve().parent.parent / "web"
if _web.exists():
    app.mount("/", StaticFiles(directory=str(_web), html=True), name="web")
