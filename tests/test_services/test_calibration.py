"""The retrieval score as it reaches a user.

A raw SigLIP2 cosine is not a percentage and was being rendered as one: measured on this corpus,
the best frame of 6,858 for "pedestrian in the rain" scores 0.164 — the 99.985th percentile — and
displayed as "16.4%" it reads like a near-miss. These tests pin the conversion that fixes it and,
more importantly, pin the property that makes it safe to ship: it cannot reorder results.

No model is loaded here. The two constants are the ones read from the shipped checkpoint
(`ViT-B-16-SigLIP2:webli`), so the arithmetic is exercised without several hundred MB of weights.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.services.search.encoder import calibrated_match_probability, sigmoid_probability

# Read off the shipped checkpoint 2026-08-05.
LOGIT_SCALE = 112.66889953613281
LOGIT_BIAS = -16.771724700927734


def calibrate(cosine: float) -> float:
    return sigmoid_probability(cosine, LOGIT_SCALE, LOGIT_BIAS)


class TestSigmoidCalibration:
    @pytest.mark.parametrize(
        ("cosine", "expected", "what"),
        [
            (0.1707, 0.921, "a wet road at night — top-1, the strongest query measured"),
            (0.1642, 0.850, "pedestrian in the rain — top-1 of 6,858"),
            (0.1341, 0.159, "a submarine at the intersection — absent, correctly refused"),
            (0.0905, 0.001, "meaningless input, which still scores 0.09 raw"),
        ],
    )
    def test_maps_measured_cosines_onto_a_scale_a_reader_can_use(self, cosine, expected, what):
        """The raw range 0.09–0.17 becomes 0.001–0.92, which is the entire point."""
        assert calibrate(cosine) == pytest.approx(expected, abs=0.002), what

    def test_the_raw_cosine_would_have_understated_all_of_them(self):
        """Every measured score renders under 18% raw, including a perfect match."""
        for cosine in (0.1707, 0.1642, 0.1503):
            assert cosine * 100 < 18
            assert calibrate(cosine) * 100 > 50

    def test_is_strictly_monotonic_so_ranking_cannot_change(self):
        """The safety property. A display transform that reorders results is a retrieval change."""
        cosines = [0.0093, 0.0665, 0.0905, 0.1215, 0.1341, 0.1503, 0.1642, 0.1707]
        probabilities = [calibrate(c) for c in cosines]
        assert probabilities == sorted(probabilities)
        assert sorted(cosines, key=calibrate, reverse=True) == sorted(cosines, reverse=True)

    def test_stays_inside_the_unit_interval_at_the_extremes(self):
        """Cosine is bounded [-1, 1]; the transform must not overflow or escape 0–1."""
        for cosine in (-1.0, 0.0, 1.0):
            assert 0.0 <= calibrate(cosine) <= 1.0


class TestUncalibratedFallback:
    def test_returns_none_when_no_encoder_is_loaded(self, monkeypatch):
        """`build_hits` runs in tests that never load a model — it must not trigger the load."""
        stub = MagicMock()
        stub.cache_info.return_value = MagicMock(currsize=0)
        monkeypatch.setattr("src.services.search.encoder.get_query_encoder", stub)

        assert calibrated_match_probability(0.1642) is None
        stub.assert_not_called()

    def test_uses_the_loaded_encoders_own_parameters(self, monkeypatch):
        """The constants belong to the checkpoint, so they are read from it, never hardcoded."""
        stub = MagicMock()
        stub.cache_info.return_value = MagicMock(currsize=1)
        stub.return_value = MagicMock(logit_scale=LOGIT_SCALE, logit_bias=LOGIT_BIAS)
        monkeypatch.setattr("src.services.search.encoder.get_query_encoder", stub)

        assert calibrated_match_probability(0.1642) == pytest.approx(0.850, abs=0.002)
