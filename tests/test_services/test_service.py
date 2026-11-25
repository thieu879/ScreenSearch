"""Stage functions against the real corpus.

These need `data/artifacts/` but no model, so they run fast and exercise the actual promoted data
rather than fixtures — which is the point: they would catch a corpus that loaded but was wrong.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from src.services.search import service
from src.services.search.rejection import rejection_reason, verify_match

PEDESTRIAN_FRONT_LEFT = {"objects": ["pedestrian"], "relations": {"pedestrian": ["front_left"]}}


class TestCorpusIntegrity:
    def test_artifacts_describe_one_consistent_corpus(self, corpus):
        """Six artifacts, one row count — and provenance has to agree with the other five.

        The count comes from provenance rather than a literal. `provenance.json` is written from the
        promoted rows while the matrices come from the research embedding cache, so this still
        cross-checks two independently produced things. Hardcoding 404 checked the same property
        while the corpus never changed, and turned the first legitimate expansion into a red test
        whose obvious fix was to edit the number — which is how a consistency check becomes a
        formality. The dimensions stay literal: those are properties of SigLIP2 and MiniLM, not of
        the corpus, and they should fail loudly if an encoder is ever swapped underneath.
        """
        n = corpus.provenance["n_frames"]
        assert corpus.n_frames == n
        assert corpus.vectors.shape == (n, 768)
        assert corpus.caption_vectors.shape == (n, 384)
        assert len(corpus.scene_of) == len(corpus.metadata_of) == len(corpus.caption_of) == n

    def test_vectors_are_l2_normalised(self, corpus):
        """The index computes cosine similarity as a dot product, which is only correct if they are."""
        for matrix in (corpus.vectors, corpus.caption_vectors):
            np.testing.assert_allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-5)

    def test_corpus_spans_the_scenes_provenance_claims(self, corpus):
        """Scene count is load-bearing: `distinct@10` and the diversity cap are both measured in it."""
        assert len(set(corpus.scene_of.values())) == corpus.provenance["n_scenes"]

    def test_timestamps_are_offsets_not_epochs(self, corpus):
        """M2_DESIGN §4 asks for offset into the source video; epoch microseconds are useless to a UI."""
        assert min(corpus.timestamp_of.values()) == 0.0
        assert max(corpus.timestamp_of.values()) < 60.0


class TestRerankAndReport:
    def test_diversity_cap_widens_the_head(self, corpus):
        ranked = list(corpus.frame_ids)
        scores = {f: 1.0 - i / 404 for i, f in enumerate(ranked)}
        plain = service.count_distinct_scenes(corpus, ranked, 10)
        capped = service.count_distinct_scenes(corpus, service.rerank_candidates(ranked, scores, None, 10), 10)
        assert capped > plain

    def test_metadata_filter_promotes_satisfying_frames(self, corpus):
        ranked = list(corpus.frame_ids)
        scores = {f: 1.0 - i / 404 for i, f in enumerate(ranked)}
        out = service.rerank_candidates(ranked, scores, PEDESTRIAN_FRONT_LEFT, 10)
        assert service.count_satisfying(out, PEDESTRIAN_FRONT_LEFT, 10) > 0

    def test_count_satisfying_is_vacuously_full_without_a_checkable_constraint(self, corpus):
        """Nothing structured was asked, so nothing can be unsatisfied — and no relaxation triggers.

        `weather` counts as nothing structured: it is parsed correctly but never tagged (76.3%), so
        treating it as a condition would report 0 satisfied and relax a query needlessly.
        """
        assert service.count_satisfying(corpus.frame_ids, {"objects": ["car"]}, 10) == 10
        assert service.count_satisfying(corpus.frame_ids, {"scene": {"weather": "rain"}}, 10) == 10
        assert service.count_satisfying(corpus.frame_ids, None, 10) == 10

    def test_build_hits_carries_evidence_and_a_thumb_url(self, corpus):
        ranked = list(corpus.frame_ids)
        scores = {f: 0.3 for f in ranked}
        hits = service.build_hits(ranked, scores, PEDESTRIAN_FRONT_LEFT, 5)
        assert len(hits) == 5
        assert all(h.thumb_url == f"/api/v1/frames/{h.frame_id}/thumb" for h in hits)
        assert all(h.scene_id for h in hits)

    def test_build_hits_carries_each_frames_own_caption(self, corpus):
        """The evidence the rejection verdict was formed from, which the UI never received.

        `verify` already scores the query against exactly these captions, so withholding them left
        every card asserting one generic sentence while the system held something specific.
        """
        ranked = list(corpus.frame_ids)
        hits = service.build_hits(ranked, {f: 0.3 for f in ranked}, None, 5)
        assert all(h.caption == corpus.caption_of[h.frame_id] for h in hits)
        assert len({h.caption for h in hits}) > 1, "a per-frame field that is constant is not evidence"

    def test_a_frame_without_a_caption_yields_none_rather_than_a_substitute(self, corpus):
        """Caption-deferred corpora caption at query time, so an unverified frame legitimately
        has none. Null lets the UI omit the block; a stand-in sentence is what this replaced."""
        from dataclasses import replace

        bare = replace(corpus, caption_of={})
        with patch.object(service, "get_corpus", lambda: bare):
            hits = service.build_hits(list(bare.frame_ids), {}, None, 3)
        assert [h.caption for h in hits] == [None, None, None]


class TestRejection:
    def test_empty_ranking_cannot_match(self, corpus):
        assert verify_match(corpus, np.zeros(384, dtype="float32"), []) == (False, 0.0)

    def test_unknown_ids_cannot_match(self, corpus):
        assert verify_match(corpus, np.zeros(384, dtype="float32"), ["nope"]) == (False, 0.0)

    def test_score_is_the_best_of_the_head(self, corpus):
        """max over k, which is exactly why a larger k makes rejection worse — see §6.1."""
        vec = corpus.caption_vectors[0]
        ok, score = verify_match(corpus, vec, corpus.frame_ids[:5], top_k=5)
        assert ok and score == pytest.approx(1.0, abs=1e-5)  # a caption matched against itself

    def test_reason_describes_the_archive_not_a_number(self, corpus):
        """The size must come from provenance. Asserting the literal is what let this message go on
        promising "404 keyframes from 10 driving clips" for a corpus of 6,858 from 170 — the test
        pinned the stale number instead of catching it, and only a human reading the live response
        noticed."""
        reason = rejection_reason({"objects": ["bus"]}, 0.42, 0.457)
        assert f"{corpus.provenance['n_frames']:,} keyframes" in reason
        assert f"{corpus.provenance['n_scenes']} driving clips" in reason
        assert corpus.provenance["corpus_description"] in reason

    def test_reason_never_borrows_another_corpus_description(self):
        """A corpus that does not describe itself gets a shorter sentence, never someone else's.

        The same defect as the counts above, one clause to the right, and it survived the fix that
        caught them: the place and date stayed literals, so pointing a local run at
        `data/staging/hanoi` on 2026-08-25 told the user its 2,211 Hanoi keyframes were "recorded in
        Boston and Singapore between July and November 2018". Asserting the absence is the whole
        test — silence about the footage is safe, a confident falsehood about it is not.
        """
        bare = SimpleNamespace(provenance={"n_frames": 11, "n_scenes": 2})
        with patch("src.services.search.rejection.get_corpus", return_value=bare):
            reason = rejection_reason({"objects": ["bus"]}, 0.42, 0.457)
        assert "11 keyframes from 2 driving clips." in reason
        assert "Boston" not in reason and "recorded" not in reason

    def test_reason_never_blames_an_individual_object(self):
        """It once opened "No frames with pedestrian in this archive", which is flatly false —
        pedestrians are the second most common category here. The rejection is about the whole
        query, and a message that blames one noun teaches the user something untrue."""
        for cat in ("pedestrian", "car", "bus"):
            assert cat not in rejection_reason({"objects": [cat]}, 0.42, 0.457)

    def test_reason_works_without_a_constraint(self, corpus):
        assert f"{corpus.provenance['n_frames']:,} keyframes" in rejection_reason(None, 0.1, 0.457)
