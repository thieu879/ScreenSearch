"""Query-time captioning — the live-ingest path.

Florence-2 is never loaded here. `ImageCaptioner` is ~500 MB of weights and one `generate` call, and
a test that ran it would be testing transformers; what needs testing is everything around it, where
the failures are silent:

  * a deferred corpus whose flag is lost refuses **every** query, because every caption vector is
    zero and 0.0 classifies as `no_match`;
  * a normally-ingested corpus that reaches this module at all has already broken §3's split;
  * a caption that never reaches the vector array makes the next identical query pay for it again.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import numpy as np
import pytest

from src.services.search.artifacts import Corpus
from src.services.search.captions import (
    CAPTION_DIM,
    DEFERRED_CACHE,
    append_cache,
    coverage,
    embed_cached,
    ensure_captions,
    read_cache,
    thumb_path,
)

FRAMES = ["aaa_CAM_FRONT", "bbb_CAM_FRONT", "ccc_CAM_FRONT"]


def make_corpus(captions: dict[str, str] | None = None, deferred: bool = True, artifacts: str = "") -> Corpus:
    """A corpus in the shape a `--skip-captions` ingest leaves behind: blank captions, zero vectors."""
    captions = captions or {}
    return Corpus(
        frame_ids=list(FRAMES),
        vectors=np.eye(len(FRAMES), 768, dtype="float32"),
        caption_vectors=np.zeros((len(FRAMES), CAPTION_DIM), dtype="float32"),
        scene_of={f: "clip#0000" for f in FRAMES},
        timestamp_of={f: 0.0 for f in FRAMES},
        metadata_of={f: {"frame_id": f} for f in FRAMES},
        caption_of={f: captions.get(f, "") for f in FRAMES},
        provenance={"captions": {"deferred": deferred}, "artifacts_dir": artifacts},
    )


class FakeEncoder:
    """MiniLM stand-in: a deterministic non-zero vector, so "was it embedded" is observable."""

    def __init__(self):
        self.seen: list[str] = []

    def encode(self, text: str) -> np.ndarray:
        self.seen.append(text)
        vec = np.zeros(CAPTION_DIM, dtype="float32")
        vec[len(text) % CAPTION_DIM] = 1.0
        return vec


class FakeCaptioner:
    def __init__(self, by_path: dict[str, str] | None = None):
        self.by_path = by_path or {}
        self.calls: list[str] = []

    def caption(self, image_path: str) -> str:
        self.calls.append(image_path)
        return self.by_path.get(os.path.basename(image_path), "a road with cars")


@pytest.fixture
def deferred(tmp_path, monkeypatch):
    """Point artifacts and thumbs at a tmp dir, with a thumbnail present for every frame."""
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    for f in FRAMES:
        (thumbs / f"{f}.jpg").write_bytes(b"")
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("THUMBS_DIR", str(thumbs))
    from src.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


class TestTheDeferredFlag:
    def test_a_deferred_corpus_says_so(self):
        assert make_corpus(deferred=True).captions_deferred

    def test_a_normal_corpus_does_not(self):
        assert not make_corpus(deferred=False).captions_deferred

    def test_a_corpus_with_no_captions_key_is_not_deferred(self):
        """Every corpus promoted before this feature existed. Absence must not mean deferred:
        it would send a fully-captioned corpus down the captioning path on every query."""
        corpus = make_corpus()
        object.__setattr__(corpus, "provenance", {"n_frames": 3})
        assert not corpus.captions_deferred


class TestEnsureCaptions:
    def test_it_captions_only_the_frames_that_lack_one(self, deferred):
        corpus = make_corpus({"aaa_CAM_FRONT": "already described"})
        captioner, encoder = FakeCaptioner(), FakeEncoder()
        with (
            patch("src.services.search.captions.get_captioner", return_value=captioner),
            patch("src.services.search.encoder.get_caption_encoder", return_value=encoder),
        ):
            n = ensure_captions(corpus, FRAMES)
        assert n == 2
        assert [os.path.basename(p) for p in captioner.calls] == ["bbb_CAM_FRONT.jpg", "ccc_CAM_FRONT.jpg"]

    def test_the_second_identical_query_captions_nothing(self, deferred):
        """The demo is slow once, not slow always — the whole point of caching."""
        corpus = make_corpus()
        captioner, encoder = FakeCaptioner(), FakeEncoder()
        with (
            patch("src.services.search.captions.get_captioner", return_value=captioner),
            patch("src.services.search.encoder.get_caption_encoder", return_value=encoder),
        ):
            assert ensure_captions(corpus, FRAMES) == 3
            assert ensure_captions(corpus, FRAMES) == 0

    def test_a_captioned_frame_gets_a_non_zero_vector(self, deferred):
        """A caption that never reaches `caption_vectors` still scores 0.0 and still refuses."""
        corpus = make_corpus()
        with (
            patch("src.services.search.captions.get_captioner", return_value=FakeCaptioner()),
            patch("src.services.search.encoder.get_caption_encoder", return_value=FakeEncoder()),
        ):
            ensure_captions(corpus, [FRAMES[0]])
        assert corpus.caption_vectors[0].any()
        assert not corpus.caption_vectors[1].any()  # untouched frames stay zero

    def test_only_the_head_is_captioned_not_the_corpus(self, deferred):
        """O(k) per query is the entire argument for option B over option C (§6.1)."""
        corpus = make_corpus()
        captioner = FakeCaptioner()
        with (
            patch("src.services.search.captions.get_captioner", return_value=captioner),
            patch("src.services.search.encoder.get_caption_encoder", return_value=FakeEncoder()),
        ):
            ensure_captions(corpus, FRAMES[:1])
        assert len(captioner.calls) == 1

    def test_a_missing_thumbnail_leaves_the_row_zero_rather_than_asserting_a_caption(self, deferred):
        corpus = make_corpus()
        captioner = FakeCaptioner({"aaa_CAM_FRONT.jpg": ""})
        with (
            patch("src.services.search.captions.get_captioner", return_value=captioner),
            patch("src.services.search.encoder.get_caption_encoder", return_value=FakeEncoder()),
        ):
            assert ensure_captions(corpus, [FRAMES[0]]) == 0
        assert corpus.caption_of[FRAMES[0]] == ""

    def test_a_frame_from_another_corpus_is_ignored(self, deferred):
        corpus = make_corpus()
        with (
            patch("src.services.search.captions.get_captioner", return_value=FakeCaptioner()),
            patch("src.services.search.encoder.get_caption_encoder", return_value=FakeEncoder()),
        ):
            assert ensure_captions(corpus, ["not_in_this_corpus_CAM_FRONT"]) == 0


class TestTheCache:
    def test_a_caption_survives_to_disk(self, deferred):
        corpus = make_corpus()
        with (
            patch("src.services.search.captions.get_captioner", return_value=FakeCaptioner()),
            patch("src.services.search.encoder.get_caption_encoder", return_value=FakeEncoder()),
        ):
            ensure_captions(corpus, [FRAMES[0]])
        assert read_cache(str(deferred))[FRAMES[0]] == "a road with cars"

    def test_an_absent_cache_is_empty_not_an_error(self, tmp_path):
        assert read_cache(str(tmp_path)) == {}

    def test_the_cache_is_appended_so_an_interrupted_demo_keeps_what_it_paid_for(self, tmp_path):
        append_cache(str(tmp_path), "one_CAM_FRONT", "first")
        append_cache(str(tmp_path), "two_CAM_FRONT", "second")
        assert read_cache(str(tmp_path)) == {"one_CAM_FRONT": "first", "two_CAM_FRONT": "second"}

    def test_the_cache_name_matches_what_ingest_folder_announces(self):
        """`ingest_folder.py` duplicates this constant — it cannot import it (no pydantic there).

        Asserting each constant against its own literal would pass while the two modules drifted
        apart, which is the only failure this test exists to catch: `ingest_folder` writes the cache
        and `captions.py` reads it, so a rename on either side is silent until a query returns
        nothing. The point is that both sides are read here.
        """
        import sys

        sys.path.insert(
            0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
        )
        from ingest_folder import CAPTION_DIM as INGEST_DIM
        from ingest_folder import CAPTIONS_DEFERRED

        assert CAPTIONS_DEFERRED == DEFERRED_CACHE
        assert INGEST_DIM == CAPTION_DIM

    def test_cached_captions_are_merged_at_load(self, tmp_path):
        """A restart must not re-pay for captioning: `Corpus.load` reads the sidecar."""
        ids = FRAMES[:2]
        np.save(tmp_path / "vectors.npy", np.zeros((2, 768), dtype="float32"))
        np.save(tmp_path / "caption_vectors.npy", np.zeros((2, CAPTION_DIM), dtype="float32"))
        with open(tmp_path / "frames.jsonl", "w", encoding="utf-8") as f:
            for i in ids:
                f.write(json.dumps({"frame_id": i, "scene_id": "s", "timestamp_s": 0.0}) + "\n")
        for name in ("metadata.jsonl", "captions.jsonl"):
            with open(tmp_path / name, "w", encoding="utf-8") as f:
                for i in ids:
                    f.write(json.dumps({"frame_id": i, "caption": ""}) + "\n")
        with open(tmp_path / "provenance.json", "w", encoding="utf-8") as f:
            json.dump({"captions": {"deferred": True}}, f)
        append_cache(str(tmp_path), ids[0], "recovered from cache")

        corpus = Corpus.load(str(tmp_path))
        assert corpus.caption_of[ids[0]] == "recovered from cache"
        assert corpus.caption_of[ids[1]] == ""


class TestEmbedCached:
    def test_a_known_caption_with_a_zero_row_gets_embedded(self):
        """The post-restart path: text came back from the cache, the vector did not."""
        corpus = make_corpus({"aaa_CAM_FRONT": "a road at night"})
        with patch("src.services.search.encoder.get_caption_encoder", return_value=FakeEncoder()):
            assert embed_cached(corpus) == 1
        assert corpus.caption_vectors[0].any()

    def test_it_does_nothing_when_every_known_caption_is_already_embedded(self):
        corpus = make_corpus({"aaa_CAM_FRONT": "a road at night"})
        with patch("src.services.search.encoder.get_caption_encoder", return_value=FakeEncoder()):
            embed_cached(corpus)
            assert embed_cached(corpus) == 0


class TestCoverage:
    def test_it_counts_what_can_currently_be_rejection_checked(self):
        assert coverage(make_corpus({"aaa_CAM_FRONT": "x"})) == {"captioned": 1, "total": 3, "missing": 2}


class TestThumbPath:
    def test_captions_are_read_from_the_redacted_thumbnail(self, deferred):
        """Not the original: originals are absent from the deployed container, and thumbnails are
        already blurred, so no generative model ever sees an unredacted face or plate."""
        assert thumb_path(FRAMES[0]).endswith(os.path.join("thumbs", f"{FRAMES[0]}.jpg"))


class TestTheVerifyGate:
    """`service.verify` is the only caller, and the flag is the only thing that lets it in."""

    @staticmethod
    def _verify(corpus):
        from src.services.search import service

        with (
            patch.object(service, "get_corpus", return_value=corpus),
            patch.object(service, "get_caption_encoder", return_value=FakeEncoder()),
            patch("src.services.search.captions.ensure_captions") as ensure,
        ):
            service.verify("a road at night", list(FRAMES))
        return ensure

    def test_a_normally_ingested_corpus_never_loads_a_vision_model(self, deferred):
        """M2_DESIGN §3's split is absolute on the default path. This is the test that keeps it so —
        a regression here puts Florence-2 in every request and turns 76 ms into seconds."""
        assert not self._verify(make_corpus(deferred=False)).called

    def test_a_deferred_corpus_captions_its_head(self, deferred):
        assert self._verify(make_corpus(deferred=True)).called
