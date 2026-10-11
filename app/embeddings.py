"""向量化：本地 LSA（零依赖下载）与 OpenAI 兼容 Embedding 接口。"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import httpx
import numpy as np

from .textutil import tokenize


def l2norm(mat: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(mat, axis=-1, keepdims=True)
    n = np.where(n == 0, 1.0, n)
    return mat / n


class LocalLSA:
    """TF-IDF + 截断 SVD 的潜语义索引，只用 numpy，不下载任何模型。"""

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.terms: List[str] = []
        self.term_index: Dict[str, int] = {}
        self.idf: np.ndarray = np.zeros(0, dtype=np.float32)
        self.components: np.ndarray = np.zeros((0, 0), dtype=np.float32)
        self.doc_vectors: np.ndarray = np.zeros((0, 0), dtype=np.float32)

    def _matrix(self, docs_tokens: Sequence[Sequence[str]]) -> np.ndarray:
        df: Counter = Counter()
        for toks in docs_tokens:
            df.update(set(toks))
        n = len(docs_tokens)
        self.terms = sorted(df)
        self.term_index = {t: i for i, t in enumerate(self.terms)}
        self.idf = np.array(
            [math.log((1.0 + n) / (1.0 + df[t])) + 1.0 for t in self.terms],
            dtype=np.float32,
        )
        x = np.zeros((n, len(self.terms)), dtype=np.float32)
        for i, toks in enumerate(docs_tokens):
            if not toks:
                continue
            for term, count in Counter(toks).items():
                j = self.term_index.get(term)
                if j is not None:
                    x[i, j] = (1.0 + math.log(count)) * float(self.idf[j])
        return l2norm(x)

    def fit(self, docs_tokens: Sequence[Sequence[str]]) -> np.ndarray:
        x = self._matrix(docs_tokens)
        n, f = x.shape
        if n == 0 or f == 0:
            self.doc_vectors = np.zeros((n, 0), dtype=np.float32)
            return self.doc_vectors
        k = max(1, min(self.dim, f, max(1, n - 1)))
        u, s, vt = np.linalg.svd(x, full_matrices=False)
        k = max(1, min(k, u.shape[1]))
        self.components = vt[:k].astype(np.float32)
        self.doc_vectors = l2norm((u[:, :k] * s[:k]).astype(np.float32))
        return self.doc_vectors

    def encode(self, text: str) -> Optional[np.ndarray]:
        if self.components.size == 0:
            return None
        toks = tokenize(text)
        if not toks:
            return None
        q = np.zeros(len(self.terms), dtype=np.float32)
        hit = False
        for term, count in Counter(toks).items():
            j = self.term_index.get(term)
            if j is not None:
                q[j] = (1.0 + math.log(count)) * float(self.idf[j])
                hit = True
        if not hit:
            return None
        norm = float(np.linalg.norm(q))
        if norm == 0.0:
            return None
        v = (q / norm) @ self.components.T
        nv = float(np.linalg.norm(v))
        if nv == 0.0:
            return None
        return v / nv

    def save(self, index_dir: Path) -> None:
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / "vocab.json").write_text(
            json.dumps({"terms": self.terms}, ensure_ascii=False), encoding="utf-8"
        )
        np.savez_compressed(index_dir / "lsa.npz", idf=self.idf, components=self.components)

    @classmethod
    def load(cls, index_dir: Path, dim: int = 256) -> "LocalLSA":
        obj = cls(dim=dim)
        vocab_file = index_dir / "vocab.json"
        npz_file = index_dir / "lsa.npz"
        if not vocab_file.exists() or not npz_file.exists():
            return obj
        obj.terms = json.loads(vocab_file.read_text(encoding="utf-8")).get("terms", [])
        obj.term_index = {t: i for i, t in enumerate(obj.terms)}
        with np.load(npz_file) as z:
            obj.idf = z["idf"].astype(np.float32)
            obj.components = z["components"].astype(np.float32)
        return obj


def endpoint(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith(path):
        return base
    return f"{base}{path}"


class ApiEmbedder:
    """OpenAI 兼容 /embeddings 接口。"""

    def __init__(self, base_url: str, model: str, api_key: str, timeout: float = 60.0):
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    async def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        url = endpoint(self.base_url, "/embeddings")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        out: List[List[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for i in range(0, len(texts), 32):
                batch = [t[:4000] for t in texts[i : i + 32]]
                resp = await client.post(
                    url, headers=headers, json={"model": self.model, "input": batch}
                )
                resp.raise_for_status()
                data = resp.json().get("data", [])
                data.sort(key=lambda d: d.get("index", 0))
                out.extend([d.get("embedding", []) for d in data])
        return out
