"""Temporal sampling density: whether a corpus's frames are close enough to make a strip.

**Why this is derived and not stamped**, which is what most of these tests are really asserting: the
number is the frames' own timestamps, so it cannot disagree with the corpus underneath it. The
rejection band needs a stamp because a fit cannot be recomputed at startup; this can, in one pass.

The threshold is not a magic constant either — it is `DEFAULT_WINDOW_S / MIN_STRIP_FRAMES`, i.e.
"can the window this product asks for hold two frames at this spacing". Asserted against that
expression rather than against `1.5`, so moving the window moves the tests with it.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from src.services.search.artifacts import Corpus
from src.services.search.density import (
    DEFAULT_WINDOW_S,
    MIN_STRIP_FRAMES,
    Density,
    corpus_density,
    measure,
)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HANOI = os.path.join(REPO, "data/staging/hanoi/artifacts")
CUT_S = DEFAULT_WINDOW_S / MIN_STRIP_FRAMES


def corpus_of(scenes: dict[str, list[float]]) -> Corpus:
    """A corpus of `scene_id -> timestamps`. Only the two fields density reads are meaningful."""
    scene_of, timestamp_of = {}, {}
    for scene, times in scenes.items():
        for n, t in enumerate(times):
            scene_of[f"{scene}_f{n}"] = scene
            timestamp_of[f"{scene}_f{n}"] = t
    ids = list(scene_of)
    zeros = np.zeros((len(ids), 4), dtype="float32")
    return Corpus(
        frame_ids=ids,
        vectors=zeros,
        caption_vectors=zeros,
        scene_of=scene_of,
        timestamp_of=timestamp_of,
        metadata_of={},
        caption_of={},
        provenance={},
    )


class TestGaps:
    def test_it_measures_intervals_within_a_scene(self):
        d = measure(corpus_of({"s0": [0.0, 0.5, 1.0, 1.5]}))
        assert d.n_gaps == 3
        assert d.median_gap_s == pytest.approx(0.5)

    def test_it_never_counts_the_interval_between_two_scenes(self):
        """Two scenes are unrelated moments, often a different street on a different day, so the
        time between them is not a sampling interval. Counting it would make any corpus look sparse
        in proportion to how many scenes it has."""
        d = measure(corpus_of({"s0": [0.0, 0.5], "s1": [900.0, 900.5]}))
        assert d.n_gaps == 2, "one gap per scene, and nothing spanning the 899 s between them"
        assert d.max_gap_s == pytest.approx(0.5)

    def test_it_does_not_depend_on_the_order_frames_are_listed_in(self):
        assert measure(corpus_of({"s0": [1.5, 0.0, 1.0, 0.5]})).median_gap_s == pytest.approx(0.5)

    def test_a_single_frame_scene_contributes_no_gap(self):
        assert measure(corpus_of({"s0": [0.0], "s1": [0.0, 0.5]})).n_gaps == 1


class TestTheDenseSparseCut:
    def test_a_corpus_sampled_faster_than_half_the_window_is_dense(self):
        assert measure(corpus_of({"s0": [0.0, CUT_S - 0.01]})).is_dense

    def test_a_corpus_sampled_slower_is_not(self):
        assert not measure(corpus_of({"s0": [0.0, CUT_S + 0.01]})).is_dense

    def test_exactly_two_frames_per_window_still_counts_as_dense(self):
        """The boundary is inclusive because `MIN_STRIP_FRAMES` frames is a strip, not a near miss."""
        assert measure(corpus_of({"s0": [0.0, CUT_S]})).is_dense

    def test_a_corpus_of_unrelated_stills_reports_sparse_not_infinitely_dense(self):
        """No gaps at all is a legitimate corpus — a folder of stills — but nothing in it supports a
        strip. A zero median would otherwise sail past the threshold and report `dense`."""
        d = measure(corpus_of({"s0": [0.0], "s1": [0.0]}))
        assert d.n_gaps == 0
        assert not d.is_dense
        assert Density(0.0, 0.0, 0.0, 0).as_dict()["is_dense"] is False


class TestTheCache:
    def test_a_second_corpus_is_not_answered_from_the_first(self):
        """`get_corpus` is process-wide, so the cache is keyed by identity. A test that builds its
        own corpus must not read the served one's density — that would pass for the wrong reason."""
        c_dense = corpus_of({"s0": [0.0, 0.5, 1.0]})
        c_sparse = corpus_of({"s0": [0.0, 9.0, 18.0]})
        dense = corpus_density(c_dense)
        sparse = corpus_density(c_sparse)
        assert dense.is_dense and not sparse.is_dense


@pytest.mark.skipif(not os.path.exists(HANOI), reason="data/staging/hanoi not ingested")
def test_the_two_real_corpora_land_on_opposite_sides():
    """The measurement the whole guard exists for, against both corpora as they sit on disk.

    These are the numbers the plan was argued from and they are asserted loosely — a range, not an
    equality — because a re-ingest may legitimately move them a little, and a test that fails on a
    corpus that got slightly denser would be noise. What must not change is which side of the cut
    each corpus falls on.
    """
    served = corpus_density(Corpus.load(os.path.join(REPO, "data/artifacts")))
    hanoi = corpus_density(Corpus.load(HANOI))
    assert served.median_gap_s == pytest.approx(0.5, abs=0.05) and served.is_dense
    assert hanoi.median_gap_s > 4.0 and not hanoi.is_dense
