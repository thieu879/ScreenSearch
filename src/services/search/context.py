"""The frames immediately preceding a hit, as a strip showing the moment it belongs to.

A result is one keyframe, but the thing a user is judging is a *moment* — whether a pedestrian was
walking into the road or standing still is invisible in a single still. The preceding frames are
already in the served corpus: nuScenes keyframes sit ~0.5 s apart (2 Hz) within a scene, and
`Corpus` already carries `scene_of` and `timestamp_of`. So this reads what is loaded rather than
publishing anything new, which is what keeps it clear of the privacy gate — every frame it returns
is one the corpus already serves, redacted and certified.

**Never cross a scene boundary.** `scene_id` is the diversity grouping key and two adjacent scenes
are unrelated moments, often a different street on a different day. Splicing them would produce a
preview that looks like continuous footage and is not.
"""

from __future__ import annotations

from collections import defaultdict

from src.services.search.artifacts import Corpus

# Frames sit ~0.5 s apart, so a request is satisfied by a handful of rows. Bounded anyway: the
# window is caller-supplied and an unbounded one would let a single request return a whole scene.
MAX_WINDOW_S = 10.0

# One entry, because `get_corpus` is `lru_cache(maxsize=1)` and therefore hands back the same object
# for the life of the process. Keyed by identity so a test that builds its own corpus rebuilds the
# index instead of silently reading another corpus's.
_INDEX: tuple[int, dict[str, list[tuple[float, str]]]] | None = None


def _scene_index(corpus: Corpus) -> dict[str, list[tuple[float, str]]]:
    """scene_id -> its frames as (timestamp_s, frame_id), ascending. Built once per corpus."""
    global _INDEX
    if _INDEX is None or _INDEX[0] != id(corpus):
        index: dict[str, list[tuple[float, str]]] = defaultdict(list)
        for frame_id in corpus.frame_ids:
            index[corpus.scene_of[frame_id]].append((corpus.timestamp_of[frame_id], frame_id))
        for frames in index.values():
            frames.sort()
        _INDEX = (id(corpus), dict(index))
    return _INDEX[1]


def preceding_frames(corpus: Corpus, frame_id: str, before_s: float) -> list[tuple[float, str]]:
    """The frames from `before_s` earlier up to and including `frame_id`, ascending by timestamp.

    The anchor is included so the caller renders one continuous strip rather than stitching the hit
    onto its own context. Returns `[]` for an unknown id, which the route turns into a 404.
    """
    if frame_id not in corpus.scene_of:
        return []
    anchor = corpus.timestamp_of[frame_id]
    window = min(max(before_s, 0.0), MAX_WINDOW_S)
    # A small tolerance, because the gaps are ~0.5 s but not exactly: 0.45 and 0.55 both occur, so
    # a strict `>= anchor - 3.0` drops the sixth frame of a 3 s window on about half the corpus.
    earliest = anchor - window - 0.05
    return [(t, f) for t, f in _scene_index(corpus)[corpus.scene_of[frame_id]] if earliest <= t <= anchor]
