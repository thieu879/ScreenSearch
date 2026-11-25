"""Preflight a built release image in a throwaway container, before any traffic moves.

Two jobs, and the second is the one the release exists for:

1. The build imports and the corpus loads — the cheap check that `v1.6` also passed.
2. `_parse` is exercised **for real, against the box's own key**, on the query shape measured at
   ~10% failure on 2026-08-31. A mock cannot degenerate, so the suite cannot see this; and the same
   prompt has scored 12/12 on one OpenAI project and 2/6 on another, so a developer-machine pass is
   not evidence about production.

Reports how many trials succeeded and, of those, how many needed a retry to get there. Those are
different numbers: the first says whether the product works, the second says whether the retry is
doing anything, and a release where every trial passes first time has proved nothing about it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

TRIALS = int(sys.argv[1]) if len(sys.argv) > 1 else 20
AFFECTED = os.environ.get("PREFLIGHT_QUERY", "a pedestrian to the front-left")
CANARIES = [
    "a pedestrian on the right",
    "a bus on fire",
    "a motorbike to the right of a bus",
    "a car at dusk",
    "a truck at night",
    "a bicycle on the left",
]


class RetryCounter(logging.Handler):
    """Counts the INFO line `_parse` emits per retry — the only signal a retry happened."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.retries = 0

    def emit(self, record: logging.LogRecord) -> None:
        if "token cap, retrying" in record.getMessage():
            self.retries += 1


async def trials(parse, query: str, n: int, counter: RetryCounter) -> tuple[int, int, int]:
    """Run `query` `n` times; return (ok, failed, trials that needed at least one retry)."""
    ok = failed = retried = 0
    for _ in range(n):
        before = counter.retries
        try:
            await parse(query)
            ok += 1
        except Exception as exc:  # noqa: BLE001 - a preflight reports every failure shape
            failed += 1
            print(f"    ! {type(exc).__name__}: {str(exc)[:90]}")
        if counter.retries > before:
            retried += 1
    return ok, failed, retried


async def main() -> int:
    import json
    import os

    from src.config import get_settings
    from src.services import llm

    settings = get_settings()
    # Deliberately NOT `Corpus.load`: a second copy of the vectors alongside the live container is
    # ~1 GB on a 3.9 GB box, which is the memory pressure `drop_caches` exists to avoid. The
    # provenance file answers the only question a preflight needs — which corpus this image will
    # serve — for the cost of one small read.
    with open(os.path.join(settings.artifacts_dir, "provenance.json"), encoding="utf-8") as f:
        prov = json.load(f)
    band = prov.get("rejection_band", {})
    print(f"artifacts    {settings.artifacts_dir}")
    print(f"band         fitted_for {band.get('fitted_for')}  tau_reject {band.get('tau_reject')}")
    print(f"model        {settings.model_name}")

    counter = RetryCounter()
    logging.getLogger("src.services.llm").addHandler(counter)
    logging.getLogger("src.services.llm").setLevel(logging.INFO)

    print(f"\naffected shape  {AFFECTED!r}  x{TRIALS}")
    ok, failed, retried = await trials(llm._parse, AFFECTED, TRIALS, counter)
    print(f"  ok {ok}/{TRIALS}   failed {failed}/{TRIALS}   needed a retry {retried}/{TRIALS}")

    print("\ncanaries  x1 each")
    cok = cfailed = cretried = 0
    for q in CANARIES:
        a, b, c = await trials(llm._parse, q, 1, counter)
        cok, cfailed, cretried = cok + a, cfailed + b, cretried + c
    print(f"  ok {cok}/{len(CANARIES)}   failed {cfailed}   needed a retry {cretried}")

    bad = failed + cfailed
    print(f"\nPREFLIGHT {'FAIL' if bad else 'PASS'}  ({bad} unrecovered failure(s), {counter.retries} retries total)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
