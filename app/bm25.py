"""纯 Python 实现的 BM25 Okapi。"""

from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Sequence


class BM25:
    def __init__(self, corpus: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.N = len(corpus)
        self.tfs: List[Counter] = []
        self.lengths: List[int] = []
        df: Dict[str, int] = {}

        for doc in corpus:
            c = Counter(doc)
            self.tfs.append(c)
            self.lengths.append(len(doc))
            for term in c:
                df[term] = df.get(term, 0) + 1

        self.avgdl = (sum(self.lengths) / self.N) if self.N else 0.0
        self.idf = {
            t: math.log(1.0 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()
        }

    def scores(self, query: Sequence[str]) -> List[float]:
        out = [0.0] * self.N
        if not self.N or not query:
            return out
        for term in query:
            idf = self.idf.get(term)
            if idf is None or idf <= 0:
                continue
            for i, tf in enumerate(self.tfs):
                f = tf.get(term)
                if not f:
                    continue
                dl = self.lengths[i] or 1
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                out[i] += idf * f * (self.k1 + 1) / (denom or 1)
        return out
