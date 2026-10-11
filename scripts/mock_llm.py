"""本地假的 OpenAI 兼容服务，用来在不花 API 费用的前提下测试大模型分支。

    python scripts/mock_llm.py            # 监听 127.0.0.1:8199

然后在 .env 里设置：
    LLM_API_KEY=test
    LLM_BASE_URL=http://127.0.0.1:8199/v1
    LLM_MODEL=mock-model
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

app = FastAPI(title="Mock OpenAI-compatible LLM")


def reply_for(messages) -> str:
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    has_context = "【知识库】" in system and "（本次没有检索到相关内容）" not in system
    n = system.count("\n[") + system.count("\n[1]")
    if not has_context:
        return "这个问题我暂时没有查到准确信息，建议通过学校官方渠道核实。"
    return (
        f"（这是模拟模型的回答，用于验证链路）\n\n"
        f"你的问题是：{user}\n\n"
        f"系统提示词里包含 {max(n, 1)} 条知识片段，包含【知识库】分区：是。\n\n"
        f"- 回答将严格依据检索到的资料 [1]\n"
        f"- 超出资料范围的内容会提示以学校正式通知为准\n"
    )


@app.post("/v1/chat/completions")
async def completions(request: Request):
    payload = await request.json()
    messages = payload.get("messages", [])
    text = reply_for(messages)
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    if not payload.get("stream"):
        return {
            "id": cid,
            "object": "chat.completion",
            "created": created,
            "model": payload.get("model", "mock-model"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    async def gen():
        step = 12
        for i in range(0, len(text), step):
            chunk = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": payload.get("model", "mock-model"),
                "choices": [
                    {"index": 0, "delta": {"content": text[i : i + step]}, "finish_reason": None}
                ],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.02)
        end = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": payload.get("model", "mock-model"),
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(end, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    print("Mock LLM 监听 http://127.0.0.1:8199/v1")
    uvicorn.run(app, host="127.0.0.1", port=8199, log_level="warning")
