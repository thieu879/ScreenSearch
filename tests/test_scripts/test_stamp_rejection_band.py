"""`stamp_rejection_band.py` writes a claim, so its refusals are the part worth testing.

The record it puts on a corpus is what `/status` will treat as evidence that the shipped band was
measured against the footage in memory. A wrong stamp is worse than no stamp: `unfitted` tells the
truth loudly, while a stamp copied off another corpus's report reads as clean forever.

The pure parts only, following `test_rejection_band_fit.py` — nothing here loads vectors or a model.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
)

from band.stamp_rejection_band import check, corpus_identity, write_record  # noqa: E402

SHIPPED = (0.30, 0.50)
REPORT = {"n_frames": 4, "shipped": {"tau_reject": 0.30, "tau_confident": 0.50}}


def artifacts(tmp_path, ids=("f0", "f1", "f2", "f3"), provenance=None):
    """A corpus directory with only the two files the identity is derived from."""
    with open(tmp_path / "frames.jsonl", "w", encoding="utf-8") as f:
        for i in ids:
            f.write(json.dumps({"frame_id": i, "scene_id": "s0", "timestamp_s": 0.0}) + "\n")
    with open(tmp_path / "provenance.json", "w", encoding="utf-8") as f:
        json.dump(provenance or {"encoder": "openclip:ViT-B-16-SigLIP2:webli", "n_frames": len(ids)}, f)
    return str(tmp_path)


def test_identity_reads_frames_without_loading_vectors(tmp_path):
    """Stamping twelve characters must not require the 40 MB of `.npy` the fit already paid for —
    and on a fresh clone those files are not there at all."""
    fingerprint, n_frames = corpus_identity(artifacts(tmp_path))
    assert n_frames == 4
    assert len(fingerprint) == 12


def test_refuses_a_report_for_a_different_corpus(tmp_path):
    """The failure the whole mechanism exists to surface, arriving as an operator error instead."""
    with pytest.raises(SystemExit) as exit_info:
        check({**REPORT, "n_frames": 6858}, corpus_identity(artifacts(tmp_path))[1], SHIPPED)
    assert "REFUSED" in str(exit_info.value)


def test_a_moved_config_is_reported_not_refused():
    """Moving the band to a value the sweep preferred is the legitimate end of the workflow, so this
    returns True for the caller to demand `--accept-shipped` rather than exiting on it."""
    assert check(REPORT, 4, (0.30, 0.575)) is True


def test_an_unmoved_config_needs_no_acknowledgement():
    assert check(REPORT, 4, SHIPPED) is False


def test_write_preserves_every_other_provenance_key(tmp_path):
    """The 2026-08-12 lesson from `backfill_instances.py`, applied before it can happen again: a
    writer that rebuilds a record instead of merging into it silently drops what it did not produce
    — there, every scene tag on 6,858 frames."""
    directory = artifacts(tmp_path, provenance={"encoder": "e", "detector": {"vocabulary": ["car"]}, "n_frames": 4})
    write_record(directory, {"corpus": "abc123"})
    with open(os.path.join(directory, "provenance.json"), encoding="utf-8") as f:
        written = json.load(f)
    assert written["detector"]["vocabulary"] == ["car"]
    assert written["rejection_band"]["corpus"] == "abc123"
