"""Fitting the rejection band from per-query judgments — `scripts/measure/measure_rejection_band.py`.

Only the pure parts, following `test_ingest_folder.py`: scoring a query needs SigLIP2, MiniLM and
(on a deferred corpus) Florence-2, and those are unchanged code called through `service`.

What is tested here is the arithmetic that decides a shipped threshold. M2_DESIGN §10.3 is the
reason it matters: the band does not survive a corpus change, so this script is what sets it on the
first-release corpus, and a fit that is silently wrong produces a system that refuses real searches
or answers empty ones confidently while looking entirely healthy.
"""

from __future__ import annotations

import os
import sys
import textwrap

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
)

from measure.measure_rejection_band import (  # noqa: E402
    CAVEAT_COST,
    REJECT_MARGIN,
    fit_reject,
    load_queries,
    outcomes,
    rejection_accuracy,
    sweep_confident,
)

# Six real and four empty queries, chosen so the weakest real (0.425) less the margin lands on 0.39
# exactly — the fit rounds to 2dp, and a value like 0.385 would test Python's float repr instead.
REAL = [0.425, 0.47, 0.48, 0.49, 0.60, 0.70]
EMPTY = [0.10, 0.20, 0.46, 0.50]


def rows(real: list[float] | None = None, empty: list[float] | None = None) -> list[dict]:
    """Scored rows in the shape `score_all` returns."""
    real = REAL if real is None else real
    empty = EMPTY if empty is None else empty
    return [{"id": f"r{n}", "score": s, "answerable": True, "probe": False} for n, s in enumerate(real)] + [
        {"id": f"n{n}", "score": s, "answerable": False, "probe": False, "neg_class": "absent_object"}
        for n, s in enumerate(empty)
    ]


class TestTauReject:
    def test_sits_the_margin_below_the_weakest_real_query(self):
        assert fit_reject(REAL, REJECT_MARGIN) == 0.39

    def test_is_not_the_observed_minimum(self):
        """Fitting to the weakest query seen overfits ~20 of them; the twenty-first can be weaker."""
        assert fit_reject(REAL, REJECT_MARGIN) < min(REAL)

    def test_ignores_how_the_empty_queries_scored(self):
        """`tau_reject` answers "how low can a real query go", so no negative may move it.

        The line exists to stop a real search being refused. Letting an empty query pull it *up* is
        the failure §6.2 calls invisible and final: the user is told the archive lacks footage it
        holds, and nothing in the interface suggests otherwise.
        """
        assert fit_reject(REAL, REJECT_MARGIN) == fit_reject(REAL + [0.99, 0.99], REJECT_MARGIN)


class TestSweep:
    def test_never_offers_a_cutoff_below_tau_reject(self):
        """`tau_confident < tau_reject` would inverse the band — `classify` would never say `low`."""
        assert all(r["tau_confident"] >= 0.39 for r in sweep_confident(rows(), 0.39))

    def test_every_real_query_is_either_confident_or_flagged(self):
        for row in sweep_confident(rows(), 0.39):
            assert row["real_high"] + row["real_flagged_low"] == len(REAL)

    def test_counts_an_empty_query_at_the_cutoff_as_shown_confidently(self):
        """`classify` uses `>=`, so a query landing exactly on the line is answered plainly."""
        at_050 = next(r for r in sweep_confident(rows(), 0.39) if r["tau_confident"] == 0.50)
        assert at_050["empty_shown_high"] == 1  # the 0.50 negative, counted


class TestTheAsymmetryIsPreserved:
    """§6.2's asymmetry is the entire reason the band has two lines instead of one."""

    def test_a_caveat_costs_less_than_a_confident_wrong_answer(self):
        """A wrongly-flagged real query is recoverable; a confidently-shown empty one is not.

        At 1.0 this becomes balanced accuracy with extra steps, and the band stops encoding the one
        judgment it was created to encode.
        """
        assert CAVEAT_COST < 1.0

    def test_reproduces_the_2026_08_02_decision(self):
        """`config.py` chose 0.50 over 0.467: 3 more real queries flagged to remove 2 confident
        empties. The constant has to make that trade profitable, or the fit contradicts the band it
        is fitting."""
        assert CAVEAT_COST * 3 < 2

    def test_the_cost_falls_when_a_confident_empty_is_removed(self):
        sweep = {r["tau_confident"]: r for r in sweep_confident(rows(), 0.39)}
        # 0.46 -> 0.47 flags no additional real query and drops one confident empty.
        assert sweep[0.47]["real_flagged_low"] == sweep[0.46]["real_flagged_low"]
        assert sweep[0.47]["empty_shown_high"] == sweep[0.46]["empty_shown_high"] - 1
        assert sweep[0.47]["cost"] < sweep[0.46]["cost"]


class TestProbesAreExcluded:
    def test_a_probe_cannot_drag_tau_reject_down(self):
        """§10.6's `a wet road at night` scores high on footage with no wet road, on two corpora.

        That is a property of option B — a captioner never contradicts "wet", it just omits it — and
        moving a threshold to accommodate it would trade real queries away for a failure the
        threshold cannot fix. Probes are measured and reported, never fitted.
        """
        with_probe = rows() + [{"id": "p01", "score": 0.01, "answerable": True, "probe": True}]
        assert fit_reject([r["score"] for r in with_probe if r["answerable"] and not r["probe"]], REJECT_MARGIN) == 0.39

    def test_a_probe_is_absent_from_the_sweep_counts(self):
        with_probe = rows() + [{"id": "p01", "score": 0.55, "answerable": False, "probe": True}]
        assert sweep_confident(with_probe, 0.39) == sweep_confident(rows(), 0.39)


class TestOutcomes:
    def test_the_three_verdicts_partition_each_population(self):
        split = outcomes(rows(), (0.39, 0.50))
        for group in ("real", "empty"):
            counts = split[group]
            assert counts["high"] + counts["low"] + counts["no_match"] == counts["n"]

    def test_reports_the_populations_separately(self):
        """Pooling them hides the only thing the band is judged on — which population is mis-sorted."""
        split = outcomes(rows(), (0.39, 0.50))
        assert split["real"]["n"] == len(REAL)
        assert split["empty"]["n"] == len(EMPTY)
        assert split["empty"]["no_match"] == 2  # 0.10 and 0.20 fall below tau_reject


class TestRejectionAccuracy:
    """NA-VMR's metric (WACV 2025): the percentage of negative queries correctly rejected.

    The reason this is tested rather than eyeballed is that it is a number intended for a slide, and
    the two ways to get it wrong both flatter us: counting `low` as a rejection, and letting the easy
    out-of-domain queries into the in-domain figure.
    """

    def negatives(self) -> list[dict]:
        """Four in-domain negatives spanning the band, two easy out-of-domain ones."""
        return [
            {"id": "n1", "score": 0.10, "answerable": False, "probe": False},
            {"id": "n2", "score": 0.20, "answerable": False, "probe": False},
            {"id": "n3", "score": 0.46, "answerable": False, "probe": False},  # `low` — not a rejection
            {"id": "n4", "score": 0.55, "answerable": False, "probe": False},  # answered confidently
            {"id": "o1", "score": 0.05, "answerable": False, "probe": True, "domain": "out_of_domain"},
            {"id": "o2", "score": 0.08, "answerable": False, "probe": True, "domain": "out_of_domain"},
        ]

    def test_a_caveated_answer_is_not_a_rejection(self):
        """`low` shows results with a warning attached. Counting it as a refusal would inflate the
        headline figure with queries the user was in fact given frames for."""
        report = rejection_accuracy(self.negatives(), (0.39, 0.50))
        assert report["in_domain"]["rejected"] == 2  # 0.10 and 0.20 only; 0.46 is `low`
        assert "n3" in report["in_domain"]["not_rejected"]

    def test_the_two_domains_are_never_pooled(self):
        """Out-of-domain negatives are easy by construction. Pooling them raises the number without
        anything about the system having improved — the exact inflation the split exists to prevent."""
        report = rejection_accuracy(self.negatives(), (0.39, 0.50))
        assert report["in_domain"]["n"] == 4
        assert report["out_of_domain"]["n"] == 2
        assert report["out_of_domain"]["rejection_accuracy"] == 100.0
        assert report["in_domain"]["rejection_accuracy"] == 50.0

    def test_a_query_missing_a_domain_counts_as_in_domain(self):
        """The 27 hand-written negatives predate the field and are all road-scene queries."""
        report = rejection_accuracy([{"id": "n1", "score": 0.1, "answerable": False, "probe": False}], (0.39, 0.50))
        assert report["in_domain"]["n"] == 1

    def test_the_corpus_record_rejects_what_the_band_answered(self):
        """The second refusal is not a threshold, so a query the band shows confidently can still be
        refused as a fact — `traffic cones on the road` at 0.753 is the case that motivated it."""
        rows = self.negatives()
        rows[3]["contradicted"] = ["objects"]  # n4, score 0.55, would otherwise be `high`
        report = rejection_accuracy(rows, (0.39, 0.50))
        assert report["in_domain"]["rejected"] == 3
        assert report["in_domain"]["by_corpus_record"] == 1
        assert report["in_domain"]["by_band"] == 2

    def test_a_query_rejected_by_both_paths_is_counted_once(self):
        rows = self.negatives()
        rows[0]["contradicted"] = ["scene.time"]  # n1 already below tau_reject
        report = rejection_accuracy(rows, (0.39, 0.50))
        assert report["in_domain"]["rejected"] == 2
        assert report["in_domain"]["by_both"] == 1

    def test_answerable_queries_never_enter_the_metric(self):
        """It is a rate over negatives. A real query landing in `no_match` is a different failure and
        is already reported by `outcomes`."""
        rows = self.negatives() + [{"id": "r1", "score": 0.05, "answerable": True, "probe": False}]
        assert rejection_accuracy(rows, (0.39, 0.50))["in_domain"]["n"] == 4


class TestQueryFile:
    def test_a_query_with_no_judgment_is_refused(self, tmp_path):
        """The judgment is the only input this method has; a row missing one is silently dropped
        from every count unless it stops the run."""
        path = tmp_path / "q.yaml"
        path.write_text(
            textwrap.dedent("""
            corpus: t
            artifacts: a
            thumbs: t
            queries:
              - {id: r01, text: "a car", answerable: true}
              - {id: r02, text: "a bus"}
        """),
            encoding="utf-8",
        )
        with pytest.raises(SystemExit, match="r02"):
            load_queries(str(path))

    def test_probe_defaults_to_false(self, tmp_path):
        path = tmp_path / "q.yaml"
        path.write_text('corpus: t\nqueries:\n  - {id: r01, text: "a car", answerable: true}\n', encoding="utf-8")
        _, queries = load_queries(str(path))
        assert queries[0]["probe"] is False
