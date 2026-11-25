"""The contradiction check — M2_DESIGN §10.8, extended to object categories 2026-08-14.

The one refusal in the system that does not go through a threshold, which is exactly why it needs
tests a threshold does not: it can refuse a query outright, so every guard that stops it firing on
incomplete evidence is load-bearing. §10.8's measurement says it removes two queries a cutoff could
never separate; a bug here removes real results instead, silently and with a confident explanation.

Synthetic corpora rather than `data/artifacts/`, because the interesting cases are corpora we do not
have: half-tagged, untagged, mixed day/night, and — for the object side — a corpus that declares no
vocabulary at all, which is every corpus promoted before 2026-08-14.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from src.services.search.artifacts import Corpus
from src.services.search.filters import declared_vocabulary, tagged_values
from src.services.search.rejection import contradicted, contradiction_reason

NIGHT = {"scene": {"time": "night"}}
DAY = {"scene": {"time": "day"}}
CONES = {"objects": ["traffic_cone"]}
# The six `COCO_TO_VOCAB` maps. Restated here rather than imported: these tests must fail if the
# serving side starts reading the research package at query time, which it must not.
SIX = ["bicycle", "bus", "car", "motorcycle", "pedestrian", "truck"]


def corpus_tagged(*times: str | None, vocabulary: list[str] | None = None) -> Corpus:
    """A corpus of len(times) frames, each tagged `time` — or, for None, not tagged at all."""
    ids = [f"f{n}" for n in range(len(times))]
    zeros = np.zeros((len(ids), 4), dtype="float32")
    provenance: dict = {"n_frames": len(ids), "n_scenes": 1}
    if vocabulary is not None:
        provenance["detector"] = {"model": "mobilenet_v3", "vocabulary": vocabulary}
    return Corpus(
        frame_ids=ids,
        vectors=zeros,
        caption_vectors=zeros,
        scene_of=dict.fromkeys(ids, "scene0"),
        timestamp_of=dict.fromkeys(ids, 0.0),
        metadata_of={
            i: {"frame_id": i, "objects": {}, "relations": {}} | ({"scene": {"time": t}} if t else {})
            for i, t in zip(ids, times, strict=True)
        },
        caption_of=dict.fromkeys(ids, "a street"),
        provenance=provenance,
    )


class TestCensus:
    def test_reports_the_values_an_axis_takes(self):
        assert tagged_values(corpus_tagged("day", "day", "night").metadata_of) == {"time": {"day", "night"}}

    def test_omits_an_axis_some_frames_lack(self):
        """Partial coverage is not evidence of absence — the untagged frames were never examined."""
        assert tagged_values(corpus_tagged("day", "day", None).metadata_of) == {}

    def test_omits_an_axis_no_frame_carries(self):
        """A corpus promoted before tagging existed must degrade to the caption check, not to refusals."""
        assert tagged_values(corpus_tagged(None, None).metadata_of) == {}

    def test_empty_corpus_is_not_a_census(self):
        assert tagged_values({}) == {}


class TestContradicted:
    def test_night_query_on_an_all_day_corpus(self):
        """§10.8's case: `a street at night` scored 0.559 and no cutpoint could have caught it."""
        assert contradicted(corpus_tagged("day", "day"), NIGHT) == ["scene:time=night"]

    def test_day_query_on_an_all_day_corpus_is_fine(self):
        assert contradicted(corpus_tagged("day", "day"), DAY) == []

    def test_one_night_frame_is_enough_to_answer(self):
        """The check is about existence, not prevalence. Selectivity is §11.3a's metric, not this one."""
        assert contradicted(corpus_tagged("day", "day", "night"), NIGHT) == []

    def test_half_tagged_corpus_refuses_nothing(self):
        """The guard that matters most: untagged frames may hold the answer, so nobody may be refused."""
        assert contradicted(corpus_tagged("day", "day", None), NIGHT) == []

    def test_untagged_corpus_refuses_nothing(self):
        assert contradicted(corpus_tagged(None, None), NIGHT) == []

    @pytest.mark.parametrize("constraint", [None, {}, {"objects": ["car"]}, {"scene": {}}])
    def test_a_query_naming_no_scene_condition_is_never_contradicted(self, constraint):
        assert contradicted(corpus_tagged("day"), constraint) == []

    def test_weather_falls_through_to_the_embedding(self):
        """`weather` measured 76.3% and is deliberately not in TAGGED_AXES (§11.3).

        A rain query must reach the caption check rather than be refused from a field ingest chose
        not to write — the same reasoning `metadata_constraint` uses to drop it from the filter.
        """
        assert contradicted(corpus_tagged("day", "day"), {"scene": {"weather": "rain"}}) == []


class TestVocabulary:
    def test_reports_the_declared_categories(self):
        assert declared_vocabulary({"detector": {"vocabulary": SIX}}) == set(SIX)

    @pytest.mark.parametrize(
        "provenance",
        [
            None,
            {},
            {"detector": None},
            {"detector": {}},
            {"detector": {"model": "mobilenet_v3"}},
        ],
    )
    def test_undeclared_is_empty_not_an_error(self, provenance):
        """Every corpus promoted before 2026-08-14 looks like this, including the one being served."""
        assert declared_vocabulary(provenance) == set()

    def test_a_non_list_is_ignored_rather_than_trusted(self):
        """A hand-edited provenance must not license a refusal from a string's characters."""
        assert declared_vocabulary({"detector": {"vocabulary": "car"}}) == set()


class TestContradictedObjects:
    def test_a_category_the_detector_cannot_emit(self):
        """`traffic cones on the road` scores 0.753 on the served corpus — above any usable cutoff."""
        assert contradicted(corpus_tagged("day", vocabulary=SIX), CONES) == ["object:traffic_cone"]

    def test_a_category_in_the_vocabulary_is_never_refused(self):
        """Even at zero frames: absence of a *detection* is not absence from the archive."""
        assert contradicted(corpus_tagged("day", vocabulary=SIX), {"objects": ["bicycle"]}) == []

    def test_an_undeclared_corpus_refuses_nothing(self):
        """The guard that matters most, and the default: no vocabulary, no object refusals."""
        assert contradicted(corpus_tagged("day", "day"), CONES) == []

    def test_only_the_unreachable_categories_are_named(self):
        constraint = {"objects": ["car", "traffic_cone", "barrier"]}
        assert contradicted(corpus_tagged("day", vocabulary=SIX), constraint) == [
            "object:traffic_cone",
            "object:barrier",
        ]

    def test_scene_and_object_contradictions_compose(self):
        corpus = corpus_tagged("day", "day", vocabulary=SIX)
        assert contradicted(corpus, {**CONES, **NIGHT}) == ["scene:time=night", "object:traffic_cone"]

    @pytest.mark.parametrize("constraint", [None, {}, {"objects": []}, {"scene": {"time": "day"}}])
    def test_a_query_naming_no_category_is_never_contradicted(self, constraint):
        assert contradicted(corpus_tagged("day", vocabulary=SIX), constraint) == []


class TestReason:
    def test_states_the_archives_own_record(self):
        text = contradiction_reason(corpus_tagged("day", "day"), ["scene:time=night"])
        assert "time=night" in text
        assert "all 2 are tagged time=day" in text

    def test_does_not_offer_a_rephrase_that_cannot_work(self):
        """`rejection_reason` suggests describing the scene more simply; here that is a loop with no exit."""
        text = contradiction_reason(corpus_tagged("day"), ["scene:time=night"]).lower()
        assert "try describing" not in text
        assert "there is none to find" in text

    def test_an_object_refusal_names_the_vocabulary_not_a_frame_count(self):
        """ "we found none" invites the reader to assume the detector looked and missed."""
        text = contradiction_reason(corpus_tagged("day", vocabulary=SIX), ["object:traffic_cone"])
        assert "traffic_cone" in text
        assert "can only label" in text
        assert "bicycle/bus/car/motorcycle/pedestrian/truck" in text

    def test_both_kinds_of_condition_appear_in_one_message(self):
        text = contradiction_reason(
            corpus_tagged("day", "day", vocabulary=SIX), ["scene:time=night", "object:traffic_cone"]
        )
        assert "time=night" in text
        assert "traffic_cone" in text


class TestVerifyShortCircuits:
    def test_contradiction_refuses_before_any_captioning(self, monkeypatch):
        """Free and first, so a deferred corpus never pays ~5 s/frame to learn what the tags already say."""
        from src.services.search import service

        deferred = replace(
            corpus_tagged("day", "day"), provenance={"n_frames": 2, "n_scenes": 1, "captions": {"deferred": True}}
        )
        monkeypatch.setattr(service, "get_corpus", lambda: deferred)
        monkeypatch.setattr(service, "get_caption_encoder", _explode)
        monkeypatch.setattr(service, "verify_match", _explode)

        verdict, score, _ = service.verify("a street at night", ["f0", "f1"], NIGHT)
        assert (verdict, score) == ("no_match", 0.0)

    def test_without_a_constraint_it_degrades_to_the_caption_check(self, monkeypatch):
        """A caller with no parse must get the old behaviour, not a refusal built on a missing field."""
        from src.services.search import service

        monkeypatch.setattr(service, "get_corpus", lambda: corpus_tagged("day", "day"))
        monkeypatch.setattr(service, "get_caption_encoder", lambda: _StubEncoder())
        monkeypatch.setattr(service, "verify_match", lambda *a, **k: (True, 0.9))
        assert service.verify("a street at night", ["f0"])[0] == "high"


class _StubEncoder:
    def encode(self, text: str) -> np.ndarray:
        return np.zeros(4, dtype="float32")


def _explode(*args, **kwargs):
    raise AssertionError("the contradiction check did not short-circuit — captioning ran")
