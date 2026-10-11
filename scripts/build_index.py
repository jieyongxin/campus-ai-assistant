"""重建知识库索引：python scripts/build_index.py"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

from app.index_store import build_index  # noqa: E402
from app.settings import get_settings  # noqa: E402


async def main() -> int:
    settings = get_settings()
    print(f"知识库目录：{settings.knowledge_dir}")
    print(f"索引目录：{settings.index_dir}")
    try:
        meta = await build_index(settings, progress=lambda m: print(f"  · {m}"))
    except Exception as exc:  # noqa: BLE001
        print(f"\n[失败] {exc}")
        return 1
    print("\n[完成]")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
