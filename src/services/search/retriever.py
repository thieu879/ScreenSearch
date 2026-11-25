"""Query vector → candidate retrieval → ordered rerank chain → results.

Promoted from `experiments/m1/scenesearch/retrieval/retriever.py`.

A chain rather than a single reranker slot because the rerankers compose and **the order is
load-bearing**: the metadata filter promotes frames satisfying the structured constraint, and scene
diversity then spreads what is shown. Reversed, the filter immediately undoes diversity's
arrangement. This is why the graph applies them as one step rather than as two nodes a router could
reorder.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import numpy as np


class Reranker(Protocol):
    """Anything that reorders a ranking. Must return a permutation of its input."""

    name: str

    def rank(self, ranked: list[str], scores: dict[str, float]) -> list[str]: ...


class Retriever:
    """Index search followed by an ordered chain of rerankers."""

    def __init__(self, index, rerankers: Sequence[Reranker] = ()):
        self.index = index
        self.rerankers = list(rerankers)

    def search(self, query_vec: np.ndarray, extra: Sequence[Reranker] = ()) -> tuple[list[str], dict[str, float]]:
        """`extra` runs before the static chain — it carries per-query rerankers.

        The metadata filter's constraint differs per query and the diversity window follows the
        caller's `top_k`, so neither can be fixed at construction time.
        """
        ranked, scores = self.index.search(query_vec)
        for r in list(extra) + self.rerankers:
            ranked = r.rank(ranked, scores)
        return ranked, scores
