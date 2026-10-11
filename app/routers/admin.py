"""知识库管理接口（需 X-Admin-Token）。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile

from ..index_store import Index, build_index, knowledge_files
from ..prompt import build_system_prompt

log = logging.getLogger("dcai.admin")
router = APIRouter(prefix="/api/admin", tags=["admin"])

ALLOWED_SUFFIX = {".md", ".markdown", ".txt", ".csv", ".json", ".jsonl"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


async def require_admin(
    request: Request, x_admin_token: str = Header(default="", alias="X-Admin-Token")
) -> None:
    expected = request.app.state.settings.admin_token
    if not expected or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="管理令牌无效")


@router.get("/stats", dependencies=[Depends(require_admin)])
async def stats(request: Request, days: int = 7) -> Dict[str, Any]:
    state = request.app.state
    index = state.index
    return {
        "index": index.stats() if index else {"ready": False},
        "usage": state.store.summary(days),
        "top_questions": state.store.top_questions(days, 30),
        "active_sessions": state.sessions.active,
        "llm_enabled": state.settings.llm_enabled,
        "llm_model": state.settings.llm.model if state.settings.llm_enabled else "",
    }


@router.get("/misses", dependencies=[Depends(require_admin)])
async def misses(request: Request, days: int = 7, limit: int = 50) -> Dict[str, Any]:
    """未命中的问题清单 —— 最该优先补进知识库的内容。"""
    return {"items": request.app.state.store.misses(days, limit)}


@router.get("/documents", dependencies=[Depends(require_admin)])
async def documents(request: Request) -> Dict[str, Any]:
    s = request.app.state.settings
    index = request.app.state.index
    counts: Dict[str, int] = {}
    if index:
        for c in index.chunks:
            counts[c["source"]] = counts.get(c["source"], 0) + 1
    items: List[Dict[str, Any]] = []
    for p in knowledge_files(s.knowledge_dir):
        rel = p.relative_to(s.knowledge_dir).as_posix()
        items.append(
            {
                "path": rel,
                "size": p.stat().st_size,
                "chunks": counts.get(rel, 0),
                "indexed": rel in counts,
            }
        )
    return {"items": items, "count": len(items)}


@router.post("/reindex", dependencies=[Depends(require_admin)])
async def reindex(request: Request) -> Dict[str, Any]:
    state = request.app.state
    try:
        meta = await build_index(state.settings)
    except Exception as exc:  # noqa: BLE001
        log.exception("重建索引失败")
        raise HTTPException(status_code=400, detail=f"重建索引失败：{exc}") from exc
    state.index = Index.load(state.settings)
    state.engine.set_index(state.index)
    return {"status": "ok", "meta": meta}


@router.post("/upload", dependencies=[Depends(require_admin)])
async def upload(request: Request, files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    s = request.app.state.settings
    knowledge_dir = s.knowledge_dir
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    saved: List[str] = []
    skipped: List[str] = []

    for f in files:
        name = Path(f.filename or "").name
        if not name or Path(name).suffix.lower() not in ALLOWED_SUFFIX:
            skipped.append(f.filename or "(未命名)")
            continue
        data = await f.read()
        if len(data) > MAX_UPLOAD_BYTES:
            skipped.append(f"{name}（超过 8MB）")
            continue
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("gbk", errors="ignore")
        (knowledge_dir / name).write_text(text, encoding="utf-8")
        saved.append(name)

    if saved:
        await build_index(s)
        request.app.state.index = Index.load(s)
        request.app.state.engine.set_index(request.app.state.index)

    return {"saved": saved, "skipped": skipped, "reindexed": bool(saved)}


@router.delete("/document", dependencies=[Depends(require_admin)])
async def delete_document(request: Request, path: str) -> Dict[str, Any]:
    """path 为 data/knowledge 下的相对路径。"""
    s = request.app.state.settings
    base = s.knowledge_dir.resolve()
    target = (base / path).resolve()
    if base != target and base not in target.parents:
        raise HTTPException(status_code=400, detail="非法路径")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    target.unlink()
    await build_index(s)
    request.app.state.index = Index.load(s)
    request.app.state.engine.set_index(request.app.state.index)
    return {"status": "ok", "deleted": path}


@router.get("/preview-prompt", dependencies=[Depends(require_admin)])
async def preview_prompt(request: Request) -> Dict[str, str]:
    """查看当前系统提示词，便于校方审阅话术。"""
    return {"prompt": build_system_prompt(request.app.state.settings, [])}


@router.get("/llm-check", dependencies=[Depends(require_admin)])
async def llm_check(request: Request) -> Dict[str, Any]:
    err = await request.app.state.llm.health()
    return {"ok": err is None, "detail": err or "正常"}
