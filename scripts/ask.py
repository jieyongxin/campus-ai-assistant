"""命令行问答，用于不打开网页也能验证效果：

    python scripts/ask.py "学费多少钱一年"
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

from app.index_store import Index  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.rag import ChatEngine  # noqa: E402
from app.settings import get_settings  # noqa: E402


async def main() -> int:
    question = " ".join(sys.argv[1:]).strip() or "学校在哪个城市？"
    settings = get_settings()
    index = Index.load(settings)
    if index is None:
        print("尚未构建索引，请先运行：python scripts/build_index.py")
        return 1

    engine = ChatEngine(settings, index, LLMClient(settings))
    print(f"Q: {question}\n")
    sources = []
    async for event in engine.astream(question):
        if event["type"] == "sources":
            sources = event["items"]
        elif event["type"] == "delta":
            print(event["text"], end="", flush=True)
        elif event["type"] == "done":
            print(f"\n\n[模式] {event.get('mode')}   [耗时] {event.get('latency_ms')}ms")

    if sources:
        print("\n[命中来源]")
        for i, s in enumerate(sources, 1):
            print(f"  [{i}] {s['title']} · {s['section']}  (score={s['score']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
