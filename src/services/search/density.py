"""How far apart in time are this corpus's frames, and can a keyframe strip be built from them?

**The failure this makes visible.** `context.py` returns "the frames leading up to a hit" on any
corpus, and the word *strip* means something different on each. nuScenes keyframes sit **0.50 s**
apart, so a ±3 s window is 7 stills covering 2.9 s — a moment. The staged Hanoi corpus sits **5.00 s**
apart, so the same request returns **1 frame covering 0.0 s in 83% of cases**: the frame already on
screen, relabelled as a moment. Promote a sparse corpus today and the route starts saying that while
`/health`, `/status` and the whole suite stay green — the third instance of one bug class, after the
spatial band and the rejection band (PR #117).

**This is DERIVED, not stamped, and the difference is the point.** The band needs a stamp because it
cannot be recomputed: fitting it takes a judgment set, ~20 scored queries and a captioner. Temporal
density needs none of that — it is the frames' own timestamps, already loaded, and re-deriving it
costs one pass over `timestamp_of`. A stamp here would add a number that can disagree with the
artifact it describes, which is the failure mode this project keeps paying for, not a guard against
it. So there is nothing to backfill and nothing that can go stale.

**The corpus-level label is a summary; the per-request answer is exact.** `is_dense` exists for
`/status`, where someone wants one word about the corpus. `context.py` does not consult it — it
counts the frames the window actually returned, which is right per frame and stays right on a corpus
whose density is not uniform. A merged corpus (half nuScenes, half Hanoi) has no honest single
median, and the route must not need one.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from src.services.search.artifacts import Corpus

#: A window shorter than two gaps cannot return two frames. Tied to `context.py`'s default window
#: rather than chosen: the question "is this corpus dense" only means "dense enough for the strip
#: this product asks for", and a bare threshold in seconds would be a number with no argument
#: behind it. At 3.0 s this puts the cut at 1.5 s — nuScenes 0.50 dense, Hanoi 5.00 sparse.
DEFAULT_WINDOW_S = 3.0

#: Fewer than this and there is no strip: one frame is the anchor, i.e. the result already shown.
MIN_STRIP_FRAMES = 2


@dataclass(frozen=True)
class Density:
    """Inter-frame gaps within a scene, over the whole corpus. Gaps across scenes are not counted —
    two scenes are unrelated moments, so the interval between them is not a sampling interval."""

    median_gap_s: float
    p90_gap_s: float
    max_gap_s: float
    n_gaps: int

    @property
    def is_dense(self) -> bool:
        """Can the default window hold at least two frames at this spacing?"""
        return self.n_gaps > 0 and self.median_gap_s <= DEFAULT_WINDOW_S / MIN_STRIP_FRAMES

    def as_dict(self) -> dict:
        return {
            "median_gap_s": round(self.median_gap_s, 3),
            "p90_gap_s": round(self.p90_gap_s, 3),
            "max_gap_s": round(self.max_gap_s, 3),
            "n_gaps": self.n_gaps,
            "is_dense": self.is_dense,
            "strip_window_s": DEFAULT_WINDOW_S,
            "detail": (
                "frames are close enough that a keyframe strip shows a moment"
                if self.is_dense
                else "frames are too far apart for a strip — a window returns the anchor and little "
                "else, so the honest temporal affordance here is the source clip, not a strip"
            ),
        }


def _gaps(corpus: Corpus) -> list[float]:
    """Every within-scene interval, ascending frames within each scene."""
    by_scene: dict[str, list[float]] = {}
    for frame_id, scene in corpus.scene_of.items():
        by_scene.setdefault(scene, []).append(corpus.timestamp_of[frame_id])
    gaps: list[float] = []
    for times in by_scene.values():
        times.sort()
        gaps.extend(b - a for a, b in zip(times, times[1:], strict=False))
    return gaps


def measure(corpus: Corpus) -> Density:
    """Derive the corpus's sampling density from what is loaded. One pass, no artifact required."""
    gaps = _gaps(corpus)
    if not gaps:
        # Every scene holds one frame. Not an error — a folder of unrelated stills is a legitimate
        # corpus — but nothing about it supports a strip, so it reports as sparse rather than as a
        # zero-gap corpus, which would read as infinitely dense.
        return Density(median_gap_s=0.0, p90_gap_s=0.0, max_gap_s=0.0, n_gaps=0)
    ordered = sorted(gaps)
    return Density(
        median_gap_s=statistics.median(ordered),
        p90_gap_s=ordered[min(int(len(ordered) * 0.9), len(ordered) - 1)],
        max_gap_s=ordered[-1],
        n_gaps=len(ordered),
    )


#: One entry, because `get_corpus` is `lru_cache(maxsize=1)` and hands back the same object for the
#: life of the process. Keyed by identity rather than `lru_cache`d: `Corpus` holds dicts and numpy
#: arrays and is not hashable, and a test that builds its own corpus must rebuild rather than read
#: another corpus's answer. Retains a reference to `corpus` so CPython's pymalloc cannot free and
#: reuse the memory address for a newly allocated, different corpus while cached.
_CACHE: tuple[Corpus, Density] | None = None


def corpus_density(corpus: Corpus) -> Density:
    """The corpus's density, computed once per process for the corpus `get_corpus` hands back."""
    global _CACHE
    if _CACHE is None or _CACHE[0] is not corpus:
        _CACHE = (corpus, measure(corpus))
    return _CACHE[1]
