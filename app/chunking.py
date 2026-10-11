"""把 markdown / txt / csv / jsonl 知识文件切成可检索片段。"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .textutil import tokenize

_RE_H = re.compile(r"^(#{1,6})\s+(.*)$")
_RE_FENCE = re.compile(r"^\s*```")
_RE_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


@dataclass
class Chunk:
    id: str
    source: str
    doc_title: str
    breadcrumb: str
    text: str
    tokens: List[str] = field(default_factory=list)
    kind: str = "doc"

    def to_dict(self) -> Dict:
        return asdict(self)


def _split_sections(md: str) -> List[Tuple[List[str], str]]:
    sections: List[Tuple[List[str], str]] = []
    stack: List[Tuple[int, str]] = []
    buf: List[str] = []
    in_fence = False

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append(([t for _, t in stack if t], body))
        buf.clear()

    for line in md.splitlines():
        if _RE_FENCE.match(line):
            in_fence = not in_fence
            buf.append(line)
            continue
        if not in_fence:
            m = _RE_H.match(line.strip())
            if m:
                flush()
                level = len(m.group(1))
                title = m.group(2).strip()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                continue
        buf.append(line)
    flush()
    return sections


def _paragraphs(body: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]


def _pack(paras: Iterable[str], size: int, overlap: int) -> List[str]:
    chunks: List[str] = []
    cur = ""
    for p in paras:
        if len(p) > size:
            for s in re.split(r"(?<=[。！？；!?;])", p):
                s = s.strip()
                if not s:
                    continue
                if len(cur) + len(s) + 1 > size and cur:
                    chunks.append(cur.strip())
                    cur = (cur[-overlap:] if overlap else "") + "\n" + s
                else:
                    cur = (cur + "\n" + s).strip()
            continue
        if len(cur) + len(p) + 1 > size and cur:
            chunks.append(cur.strip())
            cur = (cur[-overlap:] if overlap else "") + "\n" + p
        else:
            cur = (cur + "\n" + p).strip()
    if cur.strip():
        chunks.append(cur.strip())
    return [c for c in chunks if len(c) >= 12]


def _make(source: str, idx: int, title: str, crumb: str, text: str, kind: str) -> Chunk:
    return Chunk(
        id=f"{source}::{idx}",
        source=source,
        doc_title=title,
        breadcrumb=crumb,
        text=text,
        tokens=tokenize(f"{title} {crumb} {text}"),
        kind=kind,
    )


def chunk_markdown(
    md: str, source: str, size: int, overlap: int, title: Optional[str] = None
) -> List[Chunk]:
    doc_title = title or Path(source).stem
    chunks: List[Chunk] = []
    for heads, body in _split_sections(md):
        crumb = " > ".join(heads) if heads else doc_title
        if not title and heads and doc_title == Path(source).stem:
            doc_title = heads[0]
        for piece in _pack(_paragraphs(body), size, overlap):
            chunks.append(_make(source, len(chunks), doc_title, crumb, piece, "doc"))
    if not chunks:
        for piece in _pack(_paragraphs(md), size, overlap):
            chunks.append(_make(source, len(chunks), doc_title, doc_title, piece, "doc"))
    return chunks


def chunk_plain(text: str, source: str, size: int, overlap: int) -> List[Chunk]:
    doc_title = Path(source).stem
    return [
        _make(source, i, doc_title, doc_title, piece, "doc")
        for i, piece in enumerate(_pack(_paragraphs(text), size, overlap))
    ]


_FAQ_Q = ("question", "q", "问题", "问", "标题")
_FAQ_A = ("answer", "a", "答案", "答", "内容", "回复")


def _pick(row: Dict[str, str], keys) -> str:
    for k in keys:
        for rk, rv in row.items():
            if rk and rk.strip().lower() == k:
                return (rv or "").strip()
    return ""


def chunk_faq(rows: List[Dict[str, str]], source: str) -> List[Chunk]:
    chunks: List[Chunk] = []
    doc_title = f"{Path(source).stem}（常见问答）"
    for row in rows:
        if not isinstance(row, dict):
            continue
        q = _pick(row, _FAQ_Q)
        a = _pick(row, _FAQ_A)
        if not q or not a:
            continue
        chunks.append(_make(source, len(chunks), doc_title, q, f"问：{q}\n答：{a}", "faq"))
    return chunks


def _read_json_rows(raw: str, suffix: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if suffix == ".jsonl":
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return rows
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        items = data.get("items") or data.get("faq") or []
        return [d for d in items if isinstance(d, dict)]
    return rows


def load_documents(knowledge_dir: Path, size: int, overlap: int) -> List[Chunk]:
    chunks: List[Chunk] = []
    if not knowledge_dir.exists():
        return chunks

    for path in sorted(knowledge_dir.rglob("*")):
        if not path.is_file() or path.name.startswith((".", "_")):
            continue
        rel = path.relative_to(knowledge_dir).as_posix()
        suffix = path.suffix.lower()
        try:
            raw = path.read_text(encoding="utf-8-sig")  # utf-8-sig 同时兼容带/不带 BOM
        except UnicodeDecodeError:
            raw = path.read_text(encoding="gbk", errors="ignore")
        except Exception:  # noqa: BLE001
            continue

        # 把 <!-- --> 注释当成编写者备注，不进入知识库
        raw = _RE_HTML_COMMENT.sub("", raw)

        if suffix in (".md", ".markdown"):
            chunks.extend(chunk_markdown(raw, rel, size, overlap))
        elif suffix == ".txt":
            chunks.extend(chunk_plain(raw, rel, size, overlap))
        elif suffix == ".csv":
            rows = list(csv.DictReader(raw.splitlines()))
            chunks.extend(chunk_faq(rows, rel) or chunk_plain(raw, rel, size, overlap))
        elif suffix in (".jsonl", ".json"):
            rows = _read_json_rows(raw, suffix)
            chunks.extend(chunk_faq(rows, rel) or chunk_plain(raw, rel, size, overlap))

    return chunks
