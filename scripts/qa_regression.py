"""问答回归测试：用真实考生/家长问题校验检索与兜底行为。

    python scripts/qa_regression.py                 # 用 config.yaml 里的阈值
    python scripts/qa_regression.py --min-coverage 0.35     # 临时改阈值做对比
    python scripts/qa_regression.py --list-misses

与 smoke_test.py 的区别：smoke_test 只验证链路是否通；本脚本用一组
**真实口语化提问**衡量召回质量，统计"资料里有却答不上来"的假阴性
（miss）和"跑题问题被硬答"的假阳性（false positive）。

退出码：0 = 全部符合预期；1 = 存在用例不符合预期。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

from app.index_store import Index  # noqa: E402
from app.settings import get_settings  # noqa: E402


@dataclass
class Case:
    question: str
    keywords: tuple  # 命中片段里应该出现的关键词（任一即可）
    note: str = ""


# --- 应该答上来的问题（假阴性检测）-------------------------------------------
SHOULD_HIT = [
    Case("学费一年多少钱？", ("学费", "元/生")),
    Case("住宿费多少钱？", ("住宿费", "人间")),
    Case("滇池学院以前叫什么名字？", ("云南大学滇池学院", "转设")),
    Case("学校什么时候改名的？", ("2023", "转设", "更名")),
    Case("学校在哪个城市？", ("昆明",)),
    Case("报到需要带什么材料？", ("报到", "入学")),
    Case("怎么申请奖学金？", ("奖学金",)),
    Case("助学贷款能贷多少？", ("助学贷款", "国家助学金")),
    Case("可以转专业吗？", ("转专业",)),
    Case("图书馆开放时间是什么时候？", ("图书馆",)),
    Case("校园卡丢了怎么办？", ("校园卡",)),
    Case("招生办电话是多少？", ("0871",)),
    Case("学校有哪些学院和专业？", ("学院", "专业")),
    Case("毕业生就业情况怎么样？", ("就业", "95%")),
    Case("艺术类专业怎么录取？", ("艺术",)),
    Case("宿舍是几人间？", ("人间", "宿舍")),
    Case("学校有几个校区？", ("校区",)),
    Case("考研究生有什么奖励？", ("研究生", "50000")),
    Case("学校是公办还是民办？", ("民办",)),
    Case("录取分数线是多少？", ("分数线", "考试院")),
    Case("新生什么时候开学报到？", ("报到", "通知书")),
    Case("学校地址在哪里？", ("地址", "红塔东路", "路")),
]

# --- 不该硬答的问题（假阳性检测）：语料里没有答案，应走兜底 --------------------
SHOULD_MISS = [
    Case("帮我写一篇3000字的英语作文", (), "跑题：写作"),
    Case("今天昆明天气怎么样", (), "跑题：天气"),
    Case("怎么用 Python 写一个爬虫", (), "跑题：编程"),
    Case("推荐几部好看的电影", (), "跑题：闲聊"),
    Case("滇池学院2027年火星校区招生计划", (), "校方没有的信息"),
]


async def evaluate(index: Index, min_coverage: float, top_k: int) -> dict:
    cfg = index.settings.retrieval
    cfg.min_coverage = min_coverage
    cfg.top_k = top_k

    hit_pass, hit_fail = [], []
    for case in SHOULD_HIT:
        hits = await index.search(case.question)
        text = " ".join(h.text for h in hits[:3])
        if hits and (not case.keywords or any(k in text for k in case.keywords)):
            top = f"{hits[0].doc_title} · {hits[0].breadcrumb} (cov={hits[0].coverage:.2f})"
            hit_pass.append((case, top))
        else:
            cov = f"{hits[0].coverage:.2f}" if hits else "—"
            hit_fail.append((case, f"命中={len(hits)} 最高覆盖率={cov}"))

    fp, miss_ok = [], []
    for case in SHOULD_MISS:
        hits = await index.search(case.question)
        if hits:
            fp.append((case, f"{hits[0].doc_title} · {hits[0].breadcrumb} (cov={hits[0].coverage:.2f})"))
        else:
            miss_ok.append(case)

    return {
        "hit_pass": hit_pass,
        "hit_fail": hit_fail,
        "false_positive": fp,
        "miss_ok": miss_ok,
        "min_coverage": min_coverage,
        "top_k": top_k,
    }


def report(result: dict, verbose: bool) -> bool:
    total = len(SHOULD_HIT)
    ok_hit = len(result["hit_pass"])
    print(
        f"\n[阈值 min_coverage={result['min_coverage']} top_k={result['top_k']}]"
        f"  召回 {ok_hit}/{total}   跑题误答 {len(result['false_positive'])}/{len(SHOULD_MISS)}"
    )
    if verbose:
        for case, top in result["hit_pass"]:
            print(f"  [命中] {case.question}  ->  {top}")
    for case, why in result["hit_fail"]:
        print(f"  [漏答] {case.question}  ({why})")
    for case, why in result["false_positive"]:
        print(f"  [误答] {case.question}  ->  {why}  <- {case.note}")
    if verbose:
        for case in result["miss_ok"]:
            print(f"  [兜底] {case.question}")
    return not result["hit_fail"] and not result["false_positive"]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-coverage", type=float, default=None, help="临时覆盖阈值做对比")
    parser.add_argument("--top-k", type=int, default=None, help="临时覆盖 top_k")
    parser.add_argument("--sweep", action="store_true", help="扫多组参数，输出对比表")
    parser.add_argument("--list-misses", action="store_true", help="只打印漏答的题目")
    args = parser.parse_args()

    settings = get_settings()
    index = Index.load(settings)
    if index is None:
        print("尚未构建索引，请先运行：python scripts/build_index.py")
        return 1

    base_cov = args.min_coverage or settings.retrieval.min_coverage
    top_k = args.top_k or settings.retrieval.top_k

    if args.sweep:
        print("说明：调低阈值几乎不涨召回，却会立刻放出跑题误答，所以阈值不该用来兜语法差异。")
        print(f"{'覆盖率阈值':>10} {'召回':>9} {'漏答':>6} {'误答':>6}")
        for cov in (0.60, 0.50, 0.42, 0.38, 0.35, 0.32, 0.30, 0.25):
            r = await evaluate(index, cov, top_k)
            flag = "" if not r["hit_fail"] and not r["false_positive"] else "  <- 不合格"
            print(
                f"{cov:>10.2f} {len(r['hit_pass']):>5}/{len(SHOULD_HIT):<3}"
                f" {len(r['hit_fail']):>6} {len(r['false_positive']):>6}{flag}"
            )
        return 0

    result = await evaluate(index, base_cov, top_k)
    passed = report(result, verbose=not args.list_misses)
    if args.list_misses:
        for case, why in result["hit_fail"]:
            print(f"{case.question}\t{why}")
    print("\n" + ("回归通过 ✅" if passed else "存在不符合预期的用例 ❌"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
