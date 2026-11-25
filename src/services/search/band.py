"""Is the band this process serves the band anyone measured on the corpus it loaded?

**The failure this makes visible.** `tau_reject` / `tau_confident` live in `src/config.py`; the
corpus lives in `data/artifacts/`. Nothing has ever compared the two, so a corpus can be swapped
underneath a band fitted on a different one and every check stays green — `/health` reports frames,
CI passes, the UI answers. M2_DESIGN §10.3 measured what that looks like on Tokyo: `a wet road at
night` came back high-confidence at 0.581 with no wet road in the clip, while `a bus` was flagged
low at 0.376 with a bus at rank 1. Both directions at once, and no symptom pointing at the band.

**Why a stamp and not a check.** The band cannot be recomputed at startup — fitting it needs a
judgment set, ~20 scored queries and (on a deferred corpus) a captioner. So the fit records what it
fitted and against which corpus, and this module reads that record back.
`scripts/band/stamp_rejection_band.py` writes it — from a fit that just ran, or from the report of one
that ran before the field existed. Same shape as `detector.vocabulary`, backfilled 2026-08-14: a run
condition that was always inferable and never recorded, so nothing could check it.

**What is deliberately not an alarm.** The fitted band and the shipped band differ today and that is
a decision, not drift — `tau_confident` is 0.50 where the cost sweep prefers 0.575, because raising
it flags every spatial query low-confidence (`config.py` carries the reasoning). So the drift check
compares the shipped band against `reviewed`: what `config.py` carried at the moment a human looked
at the fit. A band left deliberately un-moved reports clean; a band edited afterwards does not.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.services.search.artifacts import Corpus

#: Where the fit writes itself in `provenance.json`. Not `rejection_ablation`, which is a *filename*
#: (`"rejection_ablation.json"`) and was mistaken for the values often enough to be worth avoiding.
RECORD_KEY = "rejection_band"

_DETAIL = {
    "fitted": "the shipped band was fitted on this corpus",
    "unfitted": (
        "no fit is recorded for this corpus, so the shipped band was inherited from another one — "
        "run scripts/measure/measure_rejection_band.py against it before trusting a refusal"
    ),
    "corpus_mismatch": (
        "the recorded fit is for a different corpus than the one loaded; caption-similarity scores "
        "are a property of the corpus, so this band describes footage that is not here"
    ),
    "config_drift": (
        "config.py's band has been edited since the fit was reviewed — re-fit, or re-stamp if the change was deliberate"
    ),
}


def build_record(results: dict[str, Any], corpus: tuple[str, int], report: str) -> dict[str, Any]:
    """The stamp, from a `measure_rejection_band.py` report and the identity of the corpus it ran on.

    `corpus` is `(fingerprint, n_frames)`; `report` is the path to that report, which is where the
    judgment set and every per-query score live. A band is only as good as the judgments behind it,
    and "which 24 queries, and were they scored before or after the parser changed" is the first
    thing anyone asks of a threshold — the counts are copied here, the evidence is one hop away.

    **Three bands, and they are allowed to disagree.** `fitted` is what the cost sweep preferred over
    every query. `fitted_after_contradiction` is the re-fit over what the corpus record does not
    already refuse — the population the threshold actually faces, and null when `--skip-parse` ran.
    `reviewed` is what `config.py` carried when a human read the report; it is the drift baseline,
    not a recommendation, and it stays 0.50 on nuScenes precisely because the team declined 0.575.
    """
    fitted = results.get("fitted") or {}
    after = (results.get("contradiction") or {}).get("fitted") or {}
    return {
        "corpus": corpus[0],
        "n_frames": corpus[1],
        "fitted": {k: fitted.get(k) for k in ("tau_reject", "tau_confident", "weakest_real", "margin")},
        "fitted_after_contradiction": {k: after.get(k) for k in ("tau_reject", "tau_confident")} if after else None,
        "reviewed": results.get("shipped"),
        "contradiction_checked": results.get("contradiction_checked"),
        "n_real": fitted.get("n_real"),
        "n_empty": fitted.get("n_empty"),
        "verify_top_k": results.get("verify_top_k"),
        "corpus_name": results.get("corpus"),
        "report": report,
        "stamped_at": date.today().isoformat(),
        "source": "scripts/band/stamp_rejection_band.py",
    }


def band_record(corpus: Corpus) -> dict[str, Any] | None:
    """The fit stamped into this corpus's provenance, or None if it carries none."""
    record = corpus.provenance.get(RECORD_KEY)
    return record if isinstance(record, dict) else None


def _state(record: dict[str, Any] | None, fingerprint: str, shipped: dict[str, float]) -> str:
    """Which of the four conditions holds. Corpus identity outranks config drift: a band measured on
    other footage is wrong whether or not someone has since edited the numbers."""
    if record is None:
        return "unfitted"
    if record.get("corpus") != fingerprint:
        return "corpus_mismatch"
    reviewed = record.get("reviewed") or {}
    if any(reviewed.get(k) != v for k, v in shipped.items()):
        return "config_drift"
    return "fitted"


def band_status(corpus: Corpus, shipped: tuple[float, float]) -> dict[str, Any]:
    """Report the band the process serves against the fit recorded on the corpus it loaded.

    `shipped` is `(tau_reject, tau_confident)` as `config.py` carries them now. `reviewed` is what
    it carried when the fit was signed off, and `fitted` is what the sweep actually preferred — the
    three are allowed to differ, and saying which differ from which is the whole report.
    """
    record = band_record(corpus)
    shipped_band = {"tau_reject": shipped[0], "tau_confident": shipped[1]}
    state = _state(record, corpus.fingerprint, shipped_band)
    return {
        "state": state,
        "ok": state == "fitted",
        "corpus": corpus.fingerprint,
        "fitted_for": (record or {}).get("corpus"),
        "shipped": shipped_band,
        "reviewed": (record or {}).get("reviewed"),
        "fitted": (record or {}).get("fitted"),
        "stamped_at": (record or {}).get("stamped_at"),
        "report": (record or {}).get("report"),
        "detail": _DETAIL[state],
    }
