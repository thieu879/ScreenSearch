"""Scene-diversity reranker — the fix for near-duplicate collapse.

Promoted from `experiments/m1/scenesearch/retrieval/diversity.py`; measured 2026-07-30.

Keyframes are sampled at 2 Hz, so consecutive frames of one clip are nearly identical vectors and a
relevance-only ranking answers "show me examples of X" with one example shown ten times. Measured on
this corpus, SigLIP2's top-10 spans only **2.75 distinct scenes**; a cap of 2 doubles that to 5.50.

Unlike the research build, this is **on by default** in the product. There it was off so published
ids reproduced bit-identically; here near-duplicate collapse is simply the wrong answer to give a
user, and the fidelity test pins the undiversified path separately.

**The window is the whole design.** Set it to the number of results displayed and no larger — with
cap 2, distinct-scenes@10 is 5.50 at window 10, window 50, *and* full ranking, so reordering past
the head buys no diversity at all and costs a great deal of ranking quality:

    config                single   multi   relational   distinct@10
    baseline (no cap)     +0.277  +0.271       +0.129          2.75
    cap 2, full ranking   +0.087  +0.072       +0.031          5.50
    cap 2, window 50      +0.168  +0.132       +0.077          5.50
    cap 2, window 10      +0.254  +0.219       +0.113          5.50
"""

from __future__ import annotations


class SceneCapReranker:
    """Caps how many frames from one scene may occupy the head of a ranking.

    Round-robin passes over the first `window` positions: each pass walks the remaining items in
    relevance order taking at most `max_per_group` from any one group, and whatever is skipped
    carries to the next pass. With G groups, any prefix of length `max_per_group * G` holds at most
    `max_per_group` per group. Past the window, relevance order is returned untouched.
    """

    def __init__(self, group_of: dict[str, str], max_per_group: int = 2, window: int = 10):
        if max_per_group < 1:
            raise ValueError(f"max_per_group must be >= 1, got {max_per_group}")
        if window < 1:
            raise ValueError(f"window must be >= 1, got {window}")
        self.group_of = group_of
        self.max_per_group = max_per_group
        self.window = window
        self.name = f"scene-cap-{max_per_group}@{window}"

    def rank(self, ranked: list[str], scores: dict[str, float]) -> list[str]:
        """Diversify the first `window` slots; leave the tail in relevance order.

        `scores` is unused: the input is already in relevance order, and re-reading scores would
        only risk disagreeing with it.
        """
        remaining = list(ranked)
        head: list[str] = []
        while remaining and len(head) < self.window:
            taken: dict[str, int] = {}
            deferred: list[str] = []
            for item in remaining:
                g = self.group_of.get(item, item)  # ungrouped items are their own group
                if len(head) < self.window and taken.get(g, 0) < self.max_per_group:
                    taken[g] = taken.get(g, 0) + 1
                    head.append(item)
                else:
                    deferred.append(item)
            remaining = deferred
        return head + remaining
