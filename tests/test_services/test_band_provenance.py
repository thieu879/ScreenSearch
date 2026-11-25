"""The corpus/band mismatch check — `src/services/search/band.py`.

M2_DESIGN §10.3 is the whole reason this exists: caption-similarity scores are a property of the
corpus, so a band fitted on one archive and served on another is wrong in both directions at once
and produces no symptom. Every assertion below is about a state that must be *visible*, because the
failure mode being guarded is precisely the one where everything else looks healthy.

No corpus fixture here on purpose. These build a `Corpus` from four frames so they run in CI, where
`data/artifacts/vectors.npy` does not exist and the corpus-dependent tests are skipped.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.services.search.artifacts import Corpus, fingerprint_of
from src.services.search.band import RECORD_KEY, band_record, band_status, build_record

SHIPPED = (0.30, 0.50)
IDS = ["f0", "f1", "f2", "f3"]
ENCODER = "openclip:ViT-B-16-SigLIP2:webli"


def make_corpus(provenance: dict | None = None, ids: list[str] | None = None) -> Corpus:
    """A four-frame corpus. Only `frame_ids` and `provenance` matter to this module."""
    ids = IDS if ids is None else ids
    n = len(ids)
    return Corpus(
        frame_ids=ids,
        vectors=np.zeros((n, 8), dtype="float32"),
        caption_vectors=np.zeros((n, 4), dtype="float32"),
        scene_of={i: "s0" for i in ids},
        timestamp_of={i: 0.0 for i in ids},
        metadata_of={i: {} for i in ids},
        caption_of={i: "" for i in ids},
        provenance={"encoder": ENCODER, **(provenance or {})},
    )


def record_for(corpus: Corpus, reviewed: tuple[float, float] = SHIPPED) -> dict:
    """A stamp that matches `corpus`, reviewed against `reviewed`."""
    return {
        "corpus": corpus.fingerprint,
        "n_frames": corpus.n_frames,
        "fitted": {"tau_reject": 0.30, "tau_confident": 0.57},
        "reviewed": {"tau_reject": reviewed[0], "tau_confident": reviewed[1]},
    }


# --- the fingerprint: what counts as "the same corpus" ---


def test_fingerprint_is_stable_for_the_same_frames():
    assert make_corpus().fingerprint == make_corpus().fingerprint


def test_fingerprint_moves_when_the_frames_do():
    """The `--merge` work will append frames to a live corpus. Its band must stop reporting clean."""
    grown = make_corpus(ids=[*IDS, "f4"])
    assert grown.fingerprint != make_corpus().fingerprint


def test_fingerprint_moves_when_the_encoder_does():
    """Same frames, different vector space — every option-B score shifts, so the band is not this one."""
    other = make_corpus({"encoder": "openclip:ViT-L-14:laion2b"})
    assert other.fingerprint != make_corpus().fingerprint


def test_fingerprint_ignores_captions():
    """A caption-deferred corpus fills `caption_of` at query time; a fingerprint that moved with it
    would report drift every few searches and be ignored within a day."""
    warm = make_corpus()
    cached = Corpus(**{**warm.__dict__, "caption_of": {i: "a road at night" for i in IDS}})
    assert cached.fingerprint == warm.fingerprint


# --- the four states ---


def test_unfitted_when_the_corpus_carries_no_record():
    """The pre-2026-08-18 condition, and the one every freshly ingested corpus starts in."""
    status = band_status(make_corpus(), SHIPPED)
    assert status["state"] == "unfitted"
    assert status["ok"] is False
    assert "inherited" in status["detail"]


def test_fitted_when_the_record_matches_the_corpus_and_config():
    corpus = make_corpus()
    status = band_status(make_corpus({RECORD_KEY: record_for(corpus)}), SHIPPED)
    assert status["state"] == "fitted"
    assert status["ok"] is True


def test_corpus_mismatch_when_the_record_names_other_footage():
    """§10.3's Tokyo failure: the band is nuScenes', the frames are not."""
    stale = {**record_for(make_corpus()), "corpus": fingerprint_of(["x"], ENCODER)}
    status = band_status(make_corpus({RECORD_KEY: stale}), SHIPPED)
    assert status["state"] == "corpus_mismatch"
    assert status["fitted_for"] != status["corpus"]


def test_corpus_mismatch_outranks_config_drift():
    """Both wrong at once must report the one that invalidates the other: a band measured on other
    footage is wrong whether or not the numbers have since been edited."""
    stale = {**record_for(make_corpus(), reviewed=(0.35, 0.60)), "corpus": fingerprint_of(["x"], ENCODER)}
    assert band_status(make_corpus({RECORD_KEY: stale}), SHIPPED)["state"] == "corpus_mismatch"


def test_config_drift_when_the_band_moved_after_the_fit():
    corpus = make_corpus()
    status = band_status(make_corpus({RECORD_KEY: record_for(corpus)}), (0.30, 0.575))
    assert status["state"] == "config_drift"
    assert status["shipped"]["tau_confident"] == 0.575
    assert status["reviewed"]["tau_confident"] == 0.50


def test_a_deliberately_unmoved_band_is_not_drift():
    """The live case, and the one that decides whether anyone keeps reading this field. The sweep
    prefers 0.575 and `config.py` ships 0.50 on purpose — reporting that as drift would make the
    check noise on the only corpus it currently runs against."""
    corpus = make_corpus()
    status = band_status(make_corpus({RECORD_KEY: record_for(corpus)}), SHIPPED)
    assert status["ok"] is True
    assert status["fitted"]["tau_confident"] != status["shipped"]["tau_confident"]


@pytest.mark.parametrize("junk", ["rejection_ablation.json", 0.3, [], None])
def test_a_non_record_value_reads_as_unfitted(junk):
    """`provenance.json` already carries a *string* under `rejection_ablation`. A neighbouring key of
    the wrong type must not crash /status, and must not read as a fit either."""
    corpus = make_corpus({RECORD_KEY: junk})
    assert band_record(corpus) is None
    assert band_status(corpus, SHIPPED)["state"] == "unfitted"


# --- what gets written ---


def test_build_record_keeps_fitted_and_reviewed_apart():
    """The two must never be conflated: one is what the sweep preferred, the other is what a human
    signed off. Collapsing them is how a band nobody chose becomes the recorded baseline."""
    results = {
        "corpus": "nuscenes",
        "n_frames": 6858,
        "verify_top_k": 5,
        "contradiction_checked": True,
        "fitted": {"tau_reject": 0.30, "tau_confident": 0.57, "weakest_real": 0.33, "margin": 0.035, "n_real": 16},
        "shipped": {"tau_reject": 0.30, "tau_confident": 0.50},
        "contradiction": {"fitted": {"tau_reject": 0.30, "tau_confident": 0.57}},
    }
    record = build_record(results, ("abc123", 6858), "eval/results/rejection_band_nuscenes.json")
    assert record["fitted"]["tau_confident"] == 0.57
    assert record["reviewed"]["tau_confident"] == 0.50
    assert record["corpus"] == "abc123"
    assert record["report"].endswith("rejection_band_nuscenes.json")


def test_build_record_carries_no_second_fit_when_the_parse_was_skipped():
    """`--skip-parse` produces no contradiction pass, and a null must say so rather than repeating
    the first fit under a name that claims it survived the corpus record."""
    results = {"fitted": {"tau_reject": 0.30, "tau_confident": 0.57}, "contradiction": None}
    assert build_record(results, ("abc123", 4), "r.json")["fitted_after_contradiction"] is None
