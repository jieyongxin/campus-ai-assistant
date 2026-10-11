"""不上网的自检脚本：验证知识库、分词、索引与检索链路。

    python scripts/smoke_test.py
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

from app.chunking import load_documents  # noqa: E402
from app.index_store import Index, build_index  # noqa: E402
from app.settings import get_settings  # noqa: E402
from app.textutil import HAS_JIEBA, tokenize  # noqa: E402

CASES = [
    ("学费一年多少钱？", ["学费", "收费"]),
    ("报到要带什么材料", ["报到", "入学须知", "材料"]),
    ("学校在哪个城市", ["昆明", "地址", "校区"]),
    ("怎么申请奖学金", ["奖学金", "助学金"]),
    ("图书馆能借几本书", ["图书馆", "借阅"]),
    ("招生办电话是多少", ["招生", "电话"]),
]


async def main() -> int:
    settings = get_settings()
    ok = True

    print("1) 分词")
    print(f"   jieba: {'可用' if HAS_JIEBA else '不可用（已退化到字符 n-gram）'}")
    print(f"   tokenize('学费多少钱一年') -> {tokenize('学费多少钱一年')}")

    print("\n2) 读取知识库")
    chunks = load_documents(settings.knowledge_dir, settings.retrieval.chunk_size, settings.retrieval.chunk_overlap)
    print(f"   片段数：{len(chunks)}，文档数：{len({c.source for c in chunks})}")
    if not chunks:
        print("   [失败] 没有读到任何知识片段")
        return 1

    print("\n3) 构建索引")
    try:
        meta = await build_index(settings)
    except Exception as exc:  # noqa: BLE001
        print(f"   [失败] {exc}")
        return 1
    print(f"   provider={meta['provider']} dim={meta['dim']} chunks={meta['chunks']}")

    index = Index.load(settings)
    if index is None:
        print("   [失败] 索引加载失败")
        return 1

    print("\n4) 检索回归测试")
    for question, keywords in CASES:
        hits = await index.search(question)
        text = " ".join(h.text for h in hits[:3])
        hit = bool(hits) and any(k in text for k in keywords)
        flag = "PASS" if hit else "FAIL"
        if not hit:
            ok = False
        top = f"{hits[0].doc_title} · {hits[0].breadcrumb} (score={hits[0].score:.3f})" if hits else "无命中"
        print(f"   [{flag}] {question}  ->  {top}")

    print("\n" + ("全部通过 ✅" if ok else "存在失败用例 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
