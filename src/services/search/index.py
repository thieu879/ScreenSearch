"""Exact flat inner-product index.

Promoted from `experiments/m1/scenesearch/index/flat.py`; validated under experiment `40095e80`.

Still exact, still numpy, and that is a decision rather than an omission. At 404 vectors this is one
matmul plus an argsort — measured at 69 ms per query, of which almost all is the text-tower forward
pass and only a sliver is the search. M2_DESIGN §5 is clear that the flat index does not survive to
7.2M frames and that ANN is an M3 item; it is equally clear that swapping in an approximate index
here would trade measurable recall for no measurable latency.
"""

from __future__ import annotations

import numpy as np


class FlatIndex:
    """Full-corpus cosine ranking over L2-normalised vectors."""

    def __init__(self, embeddings: np.ndarray, item_ids: list[str]):
        # The research version asserts this. `assert` is stripped under `python -O`, and a length
        # mismatch here silently returns the wrong frame for every query, so it raises instead.
        if embeddings.shape[0] != len(item_ids):
            raise ValueError(f"embeddings has {embeddings.shape[0]} rows but got {len(item_ids)} ids")
        self.emb = np.ascontiguousarray(embeddings.astype("float32"))
        self.ids = list(item_ids)

    def search(self, query_vec: np.ndarray) -> tuple[list[str], dict[str, float]]:
        """Full-corpus ranking by cosine similarity. Returns (ranked_ids, {id: score}).

        `kind="stable"` is load-bearing, not tidiness: SigLIP2 scores tie often enough at this
        corpus size that an unstable sort would make identical queries return different orderings
        across runs, and the fidelity test against `40095e80` would flake.
        """
        q = query_vec.reshape(-1).astype("float32")
        sims = self.emb @ q
        order = np.argsort(-sims, kind="stable")
        ranked = [self.ids[i] for i in order]
        scores = {self.ids[i]: float(sims[i]) for i in order}
        return ranked, scores
