"""`regroup` must close the stationary-run leak without ever handing a clip more head slots.

The defect it fixes: `scene_id` is a 20-second wall-clock bucket and `diversity.py` admits 2 frames
per `scene_id`, so a stopped vehicle — whose frozen view straddles a bucket boundary — gets 2 slots
from *each* bucket it crosses. On the staged Hanoi corpus 133 of 196 near-duplicate runs cross a
boundary and four could fill an entire ten-slot page with one moment.

The fix is a union of buckets, and the direction is the whole safety argument. **Merging can only
reduce the number of groups**, so head occupancy can only fall and a corpus whose runs already sit
inside their buckets is untouched by construction. The first draft named each run as its own group
instead, which *splits* a bucket the run only partly covers: on nuScenes that cut clips into as many
as 8 groups apiece and would have given one clip 16 head slots — a regression in the live product,
produced by the change meant to improve diversity. `test_never_splits_a_bucket` is that bug, and it
fails on the split formulation.

`test_frame_list_is_untouched` pins the other half: the corpus fingerprint is
`sha256(frame_ids + encoder)`, so a relabelling must not disturb ids or their order, or a fitted
rejection band would read `corpus_mismatch` for a change that moved no frame.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
)

regroup_scenes = pytest.importorskip("regroup_scenes")


def _rows(scene_ids: list[str], video_id: str = "clip01") -> list[dict]:
    """Frames at 2 Hz carrying the clock buckets a caller assigned them."""
    return [
        {"frame_id": f"{video_id}:{i:04d}", "video_id": video_id, "timestamp_s": i * 0.5, "scene_id": sid}
        for i, sid in enumerate(scene_ids)
    ]


def _frozen(n: int, dim: int = 8) -> np.ndarray:
    """`n` identical vectors — consecutive cosine 1.0, so every pair is a near-duplicate."""
    return np.tile(np.arange(1, dim + 1, dtype="float32"), (n, 1))


def _moving(n: int, dim: int = 8) -> np.ndarray:
    """`n` mutually orthogonal-ish vectors, well below the 0.95 run threshold."""
    return np.eye(n, dim, dtype="float32")


def test_merges_a_run_that_crosses_buckets() -> None:
    """The measured defect: one frozen moment spread over three buckets becomes one group."""
    rows = _rows(["clip01#0000", "clip01#0000", "clip01#0001", "clip01#0002", "clip01#0002"])
    merged = regroup_scenes.regroup(rows, _frozen(5))
    assert merged == 2
    assert len({row["scene_id"] for row in rows}) == 1


def test_group_is_named_after_its_earliest_bucket() -> None:
    """Stable regardless of merge order, and it still points at when the moment starts."""
    rows = _rows(["clip01#0003", "clip01#0004", "clip01#0005"])
    regroup_scenes.regroup(rows, _frozen(3))
    assert {row["scene_id"] for row in rows} == {"clip01#0003"}


def test_never_splits_a_bucket() -> None:
    """A run covering part of a bucket must not break the rest of that bucket off.

    This is the nuScenes regression: there a run sits inside its clip, and naming the run as its own
    group would turn one clip into two, doubling the head slots it can take.
    """
    rows = _rows(["clip01#0000"] * 6)
    vectors = np.vstack([_frozen(3), _moving(3)])
    before = {row["scene_id"] for row in rows}
    merged = regroup_scenes.regroup(rows, vectors)
    assert merged == 0
    assert {row["scene_id"] for row in rows} == before


def test_is_a_noop_when_runs_stay_inside_their_buckets() -> None:
    """The property that makes this safe to run over an already-served corpus."""
    rows = _rows(["clip01#0000", "clip01#0000", "clip01#0001", "clip01#0001"])
    vectors = np.vstack([_frozen(2), _frozen(2)[:, ::-1]])
    before = [row["scene_id"] for row in rows]
    assert regroup_scenes.regroup(rows, vectors) == 0
    assert [row["scene_id"] for row in rows] == before


def test_runs_never_span_two_videos() -> None:
    """Identical vectors in different clips are different footage and must not be merged."""
    rows = _rows(["clip01#0000"] * 3, video_id="clip01") + _rows(["clip02#0000"] * 3, video_id="clip02")
    regroup_scenes.regroup(rows, _frozen(6))
    assert len({row["scene_id"] for row in rows}) == 2


def test_frame_list_is_untouched() -> None:
    """Ids and their order are the fingerprint; a relabelling must leave both alone."""
    rows = _rows(["clip01#0000", "clip01#0001", "clip01#0002"])
    before = [row["frame_id"] for row in rows]
    regroup_scenes.regroup(rows, _frozen(3))
    assert [row["frame_id"] for row in rows] == before


def test_refuses_misaligned_vectors() -> None:
    """A row/vector mismatch would group frames by another frame's content, silently."""
    with pytest.raises(ValueError, match="row-aligned"):
        regroup_scenes.regroup(_rows(["clip01#0000"] * 3), _frozen(2))
