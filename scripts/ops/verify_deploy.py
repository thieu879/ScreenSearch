"""Post-deploy verification against the Live URL. Run from anywhere; no box access needed.

**`/health` and `/status` are not verification.** Both were green for the forty minutes `v1.6` was
live with every spatial search answering "Search is temporarily unavailable" — neither route touches
the LLM. So the load-bearing checks here are the searches, and one of them is the exact query shape
whose ~10% parse failure this release retries.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = os.environ.get("VERIFY_BASE", "https://scenesearch.duckdns.org")

# Defaults describe the box as of 2026-08-31. They are arguments rather than constants because the
# whole failure this script exists to catch is a deploy that serves a *different* corpus than
# intended and reports itself healthy while doing it — so the expected values have to be stated by
# the person deploying, not inherited from whatever the file last said.
EXPECT_RELEASE = sys.argv[1] if len(sys.argv) > 1 else "v1.9.1"
EXPECT_FRAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 9069
EXPECT_FINGERPRINT = sys.argv[3] if len(sys.argv) > 3 else "6279d28247bb"


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=60) as r:
        return json.load(r)


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main() -> int:
    fails = []

    health = get("/health")
    ok = health.get("release") == EXPECT_RELEASE and health.get("corpus_frames") == EXPECT_FRAMES
    print(f"[{'ok' if ok else 'FAIL'}] /health  release={health.get('release')}  frames={health.get('corpus_frames')}")
    if not ok:
        fails.append("health")

    status = get("/api/v1/status")
    band = status.get("rejection_band", {})
    ok = band.get("state") == "fitted" and band.get("fitted_for") == EXPECT_FINGERPRINT
    print(f"[{'ok' if ok else 'FAIL'}] /status  band={band.get('state')}  fitted_for={band.get('fitted_for')}")
    if not ok:
        fails.append("status")

    # The checks the two routes above cannot make. The second query is the shape measured at ~10%
    # parse failure on 2026-08-31; three consecutive calls is the same evidence the v1.6.1 deploy
    # was signed off on, and it is what would have caught v1.6.
    for query, trials in (("a pedestrian on the right", 3), ("a pedestrian to the front-left", 5)):
        hits = []
        for _ in range(trials):
            try:
                r = post("/api/v1/search", {"query": query, "top_k": 10})
                hits.append(len(r.get("results", [])) if r.get("matched") else 0)
            except Exception as exc:  # noqa: BLE001
                hits.append(f"ERR:{type(exc).__name__}")
        ok = all(isinstance(h, int) and h > 0 for h in hits)
        print(f"[{'ok' if ok else 'FAIL'}] search {query!r:35} -> {hits}")
        if not ok:
            fails.append(query)

    print(f"\n{'VERIFY PASS' if not fails else 'VERIFY FAIL: ' + ', '.join(map(str, fails))}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
