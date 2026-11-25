"""Which corpus a frame came from — and, more importantly, when we refuse to say.

The frame detail's "Data Source" row was a hardcoded `nuScenes (Production)` printed on every
result, which became false for 2,211 of 9,069 frames the moment the corpora were merged. It was
blanked rather than corrected, because the API sent no corpus name and a wrong name is worse than
none. `Corpus.source_names` is what lets it be filled, so the tests that matter here are the ones
holding the line the old constant crossed: **it must return nothing rather than a plausible guess.**

Built on bare dicts rather than a loaded corpus: this reads `provenance` and `video_of` and nothing
else, and a test that needed 9,069 frames on disk to check a dictionary lookup would only be able to
run on a machine that already has them.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.services.search.artifacts import Corpus


def corpus_with(provenance: dict, video_of: dict[str, str] | None = None) -> Corpus:
    """A Corpus carrying only what `source_names` reads. One frame, so the shapes agree."""
    return Corpus(
        frame_ids=["f1"],
        vectors=np.zeros((1, 4), dtype=np.float32),
        caption_vectors=np.zeros((1, 4), dtype=np.float32),
        scene_of={"f1": "s1"},
        timestamp_of={"f1": 0.0},
        metadata_of={},
        caption_of={},
        provenance=provenance,
        video_of=video_of or {},
    )


class TestNamesWeCanEstablish:
    def test_a_part_that_recorded_its_name_and_clips_is_used_directly(self):
        """What `merge_corpora.py` writes from now on: the merge knows, so the merge records it."""
        corpus = corpus_with(
            {
                "merged_from": [
                    {"path": "data/artifacts", "name": None, "video_ids": []},
                    {"path": "data/staging/hanoi/artifacts", "name": "hanoi", "video_ids": ["clip01_hanoi"]},
                ]
            }
        )
        assert corpus.source_names == {"clip01_hanoi": "hanoi"}

    def test_a_name_is_derived_from_the_path_when_the_merge_recorded_none(self):
        """The corpus deployed today was merged before names were recorded.

        Without this the box shows no source for any frame until a re-merge, which is a real cost
        for a fallback that reads a path the merge did record.
        """
        corpus = corpus_with(
            {
                "merged_from": [
                    {"path": "data/artifacts", "video_ids": []},
                    {"path": "data/staging/hanoi/artifacts", "video_ids": ["clip01_hanoi"]},
                ]
            }
        )
        assert corpus.source_names == {"clip01_hanoi": "hanoi"}

    def test_the_top_level_clip_list_is_used_when_only_one_part_can_be_named(self):
        """The exact shape on the box: `merge_provenance` unioned the clip lists into one.

        Only the folder-ingested part contributed any, and only it has a nameable path, so the union
        is unambiguously that part's.
        """
        corpus = corpus_with(
            {
                "merged_from": [
                    {"path": "data/artifacts", "n_frames": 6858, "source": None},
                    {"path": "data/staging/hanoi/artifacts", "n_frames": 2211, "source": "folder ingest"},
                ],
                "video_ids": ["clip01_hanoi", "clip02_hanoi"],
            }
        )
        assert corpus.source_names == {"clip01_hanoi": "hanoi", "clip02_hanoi": "hanoi"}


class TestNamesWeRefuseToInvent:
    def test_an_unmerged_corpus_attributes_nothing(self):
        """There is no corpus name in provenance to report, so the row stays empty."""
        assert corpus_with({"n_frames": 6858, "video_ids": ["clip01"]}).source_names == {}

    def test_a_generic_path_yields_no_name(self):
        """`data/artifacts` is where every promoted corpus lives — it names a location, not a corpus.

        Deriving `artifacts` from it, or worse `nuScenes`, is precisely the constant this replaced.
        """
        corpus = corpus_with({"merged_from": [{"path": "data/artifacts", "video_ids": ["clipA"]}]})
        assert corpus.source_names == {}

    def test_two_nameable_parts_with_a_pooled_clip_list_refuse_rather_than_split_it(self):
        """The guard that keeps the fallback honest.

        A union of clip lists cannot say which of two folder-ingested corpora a clip came from, and
        attributing all of them to one would be wrong for roughly half. Nothing is the right answer.
        """
        corpus = corpus_with(
            {
                "merged_from": [
                    {"path": "data/staging/hanoi/artifacts"},
                    {"path": "data/staging/tokyo/artifacts"},
                ],
                "video_ids": ["clip01_hanoi", "clip01_tokyo"],
            }
        )
        assert corpus.source_names == {}

    def test_per_part_lists_win_over_the_pooled_fallback(self):
        """Two nameable parts are fine once each says which clips are its own."""
        corpus = corpus_with(
            {
                "merged_from": [
                    {"path": "data/staging/hanoi/artifacts", "video_ids": ["clip01_hanoi"]},
                    {"path": "data/staging/tokyo/artifacts", "video_ids": ["clip01_tokyo"]},
                ],
                "video_ids": ["clip01_hanoi", "clip01_tokyo"],
            }
        )
        assert corpus.source_names == {"clip01_hanoi": "hanoi", "clip01_tokyo": "tokyo"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("data/staging/hanoi/artifacts", "hanoi"),
        ("data/staging/hanoi", "hanoi"),
        ("data/artifacts", None),
        ("data/merged/artifacts", None),
        ("", None),
    ],
)
def test_path_naming(path, expected):
    corpus = corpus_with({"merged_from": [{"path": path, "video_ids": ["c"]}]})
    assert corpus.source_names.get("c") == expected
