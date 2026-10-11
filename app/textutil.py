"""中文友好的分词与文本清洗。"""

from __future__ import annotations

import re
import unicodedata
from typing import List

try:
    import jieba

    jieba.setLogLevel(60)
    jieba.initialize()
    HAS_JIEBA = True
except Exception:  # noqa: BLE001
    HAS_JIEBA = False


_STOPWORDS = {
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "会", "着", "没有", "看", "好",
    "自己", "这", "那", "他", "她", "它", "们", "你", "您", "请问", "一下", "什么",
    "怎么", "如何", "哪些", "哪个", "多少", "吗", "呢", "吧", "啊", "呀", "哦", "嗯",
    "以及", "并且", "但是", "如果", "因为", "所以", "可以", "能", "需要", "关于",
    "对于", "还有", "或者", "然后", "就是", "这个", "那个", "我们", "你们", "他们",
    # 疑问 / 口语化填充词：它们几乎出现在所有提问里，不能作为"命中了资料"的证据
    "怎么样", "怎样", "什么样", "什么样", "是否", "有没有", "能不能", "可不可以",
    "需不需要", "会不会", "想问", "想了解", "麻烦", "帮我", "告知", "介绍",
    "大概", "可能", "时候", "地方", "东西", "事情", "情况", "方面", "相关",
    "有关", "具体", "一般", "通常", "目前", "现在", "应该", "以及", "等等",
    # 疑问代词与数量词：jieba 会把它们切成独立词，但语料里根本不存在这些词，
    # 若不剔除，它们会被当成"问的是新东西"按最高 IDF 计权，把覆盖率压到
    # 阈值以下，导致明明有资料却被兜底成"没查到"。
    "哪", "哪里", "哪儿", "哪边", "哪一年", "几个", "几号", "几年",
    "多久", "多长", "多长时间", "多少次",
}

_RE_WS = re.compile(r"\s+")
_RE_ENG = re.compile(r"[a-zA-Z]+|\d+(?:\.\d+)?")
_RE_CJK = re.compile(r"[\u4e00-\u9fff]+")
_RE_BAD = re.compile(r"^[\W_]+$")


def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u3000", " ")
    return _RE_WS.sub(" ", text).strip()


def tokenize(text: str) -> List[str]:
    text = normalize(text)
    if not text:
        return []

    if HAS_JIEBA:
        tokens: List[str] = []
        for word in jieba.cut(text):
            word = word.strip().lower()
            if not word or word in _STOPWORDS or _RE_BAD.match(word):
                continue
            tokens.append(word)
    else:
        tokens = [w.lower() for w in _RE_ENG.findall(text)]
        for seg in _RE_CJK.findall(text):
            if len(seg) == 1:
                tokens.append(seg)
                continue
            tokens.extend(seg)
            tokens.extend(seg[i : i + 2] for i in range(len(seg) - 1))

    return [t for t in tokens if t and t not in _STOPWORDS]


def sub_tokens(term: str) -> List[str]:
    """把复合词拆成更小的子词，供"未登录词回退匹配"使用。

    查询里的复合词和语料里的切分方式经常对不上：语料里是"学校"+"地址"，
    查询却被 jieba 切成一个"学校地址"，于是词面上永远匹配不上。这里先用
    jieba 再切一次，切不开就用相邻二元组兜底，调用方再按语料词表过滤。
    """
    term = (term or "").strip().lower()
    if len(term) < 2:
        return []

    parts: List[str] = []
    if HAS_JIEBA:
        parts = [
            w.strip().lower()
            for w in jieba.cut(term)
            if w.strip() and w.strip().lower() != term and not _RE_BAD.match(w.strip())
        ]
    if not parts:
        # jieba 把它当成一个整体词（切不开），退化为相邻二元组
        parts = [term[i : i + 2] for i in range(len(term) - 1)]

    seen = set()
    out: List[str] = []
    for p in parts:
        if p and p != term and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))] + suffix


