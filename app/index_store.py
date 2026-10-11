"""索引构建、加载与混合检索（BM25 + 向量，RRF 融合）。"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from .bm25 import BM25
from .chunking import Chunk, load_documents
from .embeddings import ApiEmbedder, LocalLSA, l2norm
from .settings import Settings
from .textutil import sub_tokens, tokenize

log = logging.getLogger("dcai.index")

META_FILE = "meta.json"
CHUNKS_FILE = "chunks.jsonl"
DOCVEC_FILE = "doc_vectors.npy"
KNOWLEDGE_EXTS = {".md", ".markdown", ".txt", ".csv", ".json", ".jsonl"}


@dataclass
class Hit:
    chunk_id: str
    source: str
    doc_title: str
    breadcrumb: str
    text: str
    score: float
    kind: str = "doc"
    lexical: float = 0.0
    semantic: float = 0.0
    coverage: float = 0.0

    def to_dict(self, with_text: bool = True) -> Dict:
        d = {
            "id": self.chunk_id,
            "source": self.source,
            "title": self.doc_title,
            "section": self.breadcrumb,
            "score": round(self.score, 4),
            "coverage": round(self.coverage, 4),
        }
        if with_text:
            d["text"] = self.text
        return d


def knowledge_files(knowledge_dir: Path) -> List[Path]:
    if not knowledge_dir.exists():
        return []
    return sorted(
        p
        for p in knowledge_dir.rglob("*")
        if p.is_file()
        and p.suffix.lower() in KNOWLEDGE_EXTS
        and not p.name.startswith((".", "_"))
    )


def _fingerprint(files: Sequence[Path]) -> str:
    h = hashlib.sha1()
    for p in files:
        try:
            st = p.stat()
            h.update(f"{p.name}:{st.st_size}:{int(st.st_mtime)}".encode())
        except OSError:
            continue
    return h.hexdigest()[:16]


async def build_index(settings: Settings, progress: Optional[Callable[[str], None]] = None) -> Dict:
    cfg = settings.retrieval
    index_dir = settings.index_dir

    def report(msg: str) -> None:
        log.info(msg)
        if progress:
            try:
                progress(msg)
            except Exception:  # noqa: BLE001
                pass

    report("读取知识库…")
    chunks: List[Chunk] = load_documents(settings.knowledge_dir, cfg.chunk_size, cfg.chunk_overlap)
    if not chunks:
        raise RuntimeError(
            f"知识库为空：{settings.knowledge_dir}。请先放入 .md / .txt / .csv / .jsonl 资料。"
        )
    report(f"切分出 {len(chunks)} 个片段")

    provider = "local"
    model = "lsa"
    doc_vectors = np.zeros((len(chunks), 0), dtype=np.float32)

    if settings.embedding_api_enabled:
        report("调用 Embedding 接口…")
        embedder = ApiEmbedder(
            base_url=cfg.embedding.base_url,
            model=cfg.embedding.model,
            api_key=settings.embedding_api_key,
        )
        try:
            vecs = await embedder.embed([c.text for c in chunks])
            arr = np.asarray(vecs, dtype=np.float32)
            if arr.ndim == 2 and arr.shape[0] == len(chunks):
                doc_vectors = l2norm(arr)
                provider = "api"
                model = cfg.embedding.model
                report(f"向量化完成，维度 {doc_vectors.shape[1]}")
        except Exception as exc:  # noqa: BLE001
            report(f"Embedding 接口不可用（{exc}），回退本地 LSA")

    if provider == "local":
        report("构建本地语义索引（TF-IDF + SVD）…")
        lsa = LocalLSA(dim=cfg.embedding.dim)
        doc_vectors = lsa.fit([c.tokens for c in chunks])
        lsa.save(index_dir)
        report(f"本地向量维度 {doc_vectors.shape[1] if doc_vectors.ndim == 2 else 0}")

    index_dir.mkdir(parents=True, exist_ok=True)
    with (index_dir / CHUNKS_FILE).open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")
    np.save(index_dir / DOCVEC_FILE, doc_vectors)

    files = knowledge_files(settings.knowledge_dir)
    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider,
        "model": model,
        "dim": int(doc_vectors.shape[1]) if doc_vectors.ndim == 2 else 0,
        "chunks": len(chunks),
        "documents": len({c.source for c in chunks}),
        "fingerprint": _fingerprint(files),
        "files": [p.name for p in files],
        "chunk_size": cfg.chunk_size,
        "chunk_overlap": cfg.chunk_overlap,
    }
    (index_dir / META_FILE).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report("索引已保存")
    return meta


class Index:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.meta: Dict = {}
        self.chunks: List[Dict] = []
        self.bm25: Optional[BM25] = None
        self.lsa: Optional[LocalLSA] = None
        self.doc_vectors: Optional[np.ndarray] = None
        self._api_embedder: Optional[ApiEmbedder] = None
        self._token_sets: List[set] = []
        self._max_idf: float = 1.0

    @classmethod
    def load(cls, settings: Settings) -> Optional["Index"]:
        idx = cls(settings)
        d = settings.index_dir
        meta_file = d / META_FILE
        chunks_file = d / CHUNKS_FILE
        vec_file = d / DOCVEC_FILE
        if not (meta_file.exists() and chunks_file.exists()):
            return None
        idx.meta = json.loads(meta_file.read_text(encoding="utf-8"))
        idx.chunks = [
            json.loads(line)
            for line in chunks_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not idx.chunks:
            return None
        idx.bm25 = BM25([c.get("tokens") or tokenize(c["text"]) for c in idx.chunks])
        idx._token_sets = [
            set(c.get("tokens") or tokenize(c["text"])) for c in idx.chunks
        ]
        idx._max_idf = max(idx.bm25.idf.values(), default=1.0)
        if vec_file.exists():
            vecs = np.load(vec_file).astype(np.float32)
            if vecs.ndim == 2 and vecs.shape[0] == len(idx.chunks):
                idx.doc_vectors = vecs
        if idx.meta.get("provider") == "local":
            idx.lsa = LocalLSA.load(d, dim=settings.retrieval.embedding.dim)
        elif settings.embedding_api_enabled:
            idx._api_embedder = ApiEmbedder(
                base_url=settings.retrieval.embedding.base_url,
                model=settings.retrieval.embedding.model,
                api_key=settings.embedding_api_key,
            )
        return idx

    @property
    def ready(self) -> bool:
        return bool(self.chunks) and self.bm25 is not None

    def is_stale(self) -> bool:
        return _fingerprint(knowledge_files(self.settings.knowledge_dir)) != self.meta.get(
            "fingerprint"
        )

    async def _query_vector(self, query: str) -> Optional[np.ndarray]:
        if self.meta.get("provider") == "local":
            return self.lsa.encode(query) if self.lsa else None
        if self._api_embedder is not None:
            try:
                vecs = await self._api_embedder.embed([query])
                if vecs and vecs[0]:
                    v = np.asarray(vecs[0], dtype=np.float32)
                    n = float(np.linalg.norm(v))
                    return v / n if n else None
            except Exception as exc:  # noqa: BLE001
                log.warning("查询向量化失败，降级为关键词检索：%s", exc)
        return None

    @staticmethod
    def _ranks(scores: Sequence[float], limit: int) -> Dict[int, int]:
        order = sorted(
            (i for i, s in enumerate(scores) if s > 0),
            key=lambda i: scores[i],
            reverse=True,
        )[:limit]
        return {i: r + 1 for r, i in enumerate(order)}

    def _query_weights(self, query_tokens: Sequence[str]) -> Dict[str, float]:
        """把查询词折算成"词 -> 权重"表，未登录词做子词回退。

        未在语料中出现过的词按最高 IDF 计权（它们最能体现"问的是新东西"），
        但有两类要特殊处理，否则会把覆盖率压到阈值以下、让有资料的问题也走兜底：

        1. 单字未登录词（"哪""学""带"）基本都是疑问字或口语填充，直接不计权；
        2. 多字未登录词先尝试拆成已知子词（"学校地址" -> "学校"+"地址"），
           拆得开就按子词计权，拆不开才当作真·新词保留最高 IDF。
        """
        if self.bm25 is None:
            return {}
        idf = self.bm25.idf
        weights: Dict[str, float] = {}
        for t in set(query_tokens):
            if t in idf:
                weights[t] = max(weights.get(t, 0.0), float(idf[t]))
                continue
            if len(t) < 2:
                continue
            parts = [p for p in sub_tokens(t) if p in idf]
            if parts:
                for p in parts:
                    weights[p] = max(weights.get(p, 0.0), float(idf[p]))
            else:
                weights[t] = max(weights.get(t, 0.0), self._max_idf)
        return weights

    def _coverage(self, weights: Dict[str, float]) -> List[float]:
        """查询词的 IDF 加权覆盖率：衡量片段到底覆盖了问题的多少关键信息。"""
        if self.bm25 is None or not weights:
            return [0.0] * len(self.chunks)
        total = sum(weights.values())
        if total <= 0:
            return [0.0] * len(self.chunks)
        return [
            sum(w for t, w in weights.items() if t in toks) / total
            for toks in self._token_sets
        ]

    async def search(self, query: str) -> List[Hit]:
        cfg = self.settings.retrieval
        if not self.ready or not query.strip() or self.bm25 is None:
            return []

        q_tokens = tokenize(query)
        # 词法通道也用扩展后的词表：否则"学校地址""就业率"这类词面与语料不一致的
        # 复合词会被整体判为未登录，BM25 得分为 0，等于整条查询词法上完全没匹配。
        weights = self._query_weights(q_tokens)
        if not weights:
            return []
        lex_scores = self.bm25.scores(list(weights))
        lex_ranks = self._ranks(lex_scores, cfg.candidate_k)
        coverage = self._coverage(weights)

        sem_ranks: Dict[int, int] = {}
        sem_scores = np.zeros(len(self.chunks), dtype=np.float32)
        qv = await self._query_vector(query)
        if qv is not None and self.doc_vectors is not None and self.doc_vectors.size:
            if qv.shape[0] == self.doc_vectors.shape[1]:
                sem_scores = self.doc_vectors @ qv
                sem_ranks = self._ranks([float(x) for x in sem_scores], cfg.candidate_k)

        lists = [r for r in (lex_ranks, sem_ranks) if r]
        if not lists:
            return []

        fused: Dict[int, float] = {}
        for ranks in lists:
            for i, r in ranks.items():
                fused[i] = fused.get(i, 0.0) + 1.0 / (cfg.rrf_k + r)

        denom = sum(1.0 / (cfg.rrf_k + 1) for _ in lists) or 1.0
        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[: cfg.top_k]

        hits: List[Hit] = []
        for i, raw in ordered:
            score = raw / denom
            cov = coverage[i]
            if score < cfg.min_score or cov < cfg.min_coverage:
                continue
            c = self.chunks[i]
            hits.append(
                Hit(
                    chunk_id=c["id"],
                    source=c["source"],
                    doc_title=c.get("doc_title", ""),
                    breadcrumb=c.get("breadcrumb", ""),
                    text=c["text"],
                    score=float(score),
                    kind=c.get("kind", "doc"),
                    lexical=float(lex_scores[i]),
                    semantic=float(sem_scores[i]) if sem_scores.size else 0.0,
                    coverage=float(cov),
                )
            )
        return hits

    def stats(self) -> Dict:
        return {
            **self.meta,
            "stale": self.is_stale(),
            "knowledge_dir": str(self.settings.knowledge_dir),
            "sources": sorted({c["source"] for c in self.chunks}),
        }
