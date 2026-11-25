"""Declare the detector's category vocabulary on a corpus ingested before the field existed.

**Why a backfill at all.** `rejection.contradicted` can now refuse a query naming a category the
corpus could never record — `traffic cones on the road`, which scores 0.753 on the served corpus and
is answered confidently with five frames containing no cones. It reads that vocabulary from
`provenance.json`, and is silent when the field is absent. The served corpus was promoted on
2026-08-03, before `promote_artifacts.py` wrote a `detector` block at all, so without this the fix
ships as a no-op on the one corpus it was written for.

**Why this is a backfill and not a re-ingest.** Nothing about the corpus changes. The vocabulary is
a fact about the mapping that produced `metadata.jsonl` months ago, not a new measurement, and
re-running promotion to obtain it would rebuild 6,858 thumbnails and reissue the privacy certificate
to write twelve words into a JSON file.

**The claim being made, and how it is checked.** Declaring a vocabulary licenses a *refusal* — the
one thing this product says as fact rather than as a score — so it must not rest on an assumption
about which pipeline ran. It rests on an invariant instead: every category that actually appears in
`metadata.jsonl` must fall inside the vocabulary about to be declared. If a corpus carries a
category the mapping cannot emit, it was built by something else and this script refuses rather than
declaring a vocabulary that would go on to refuse real searches. The check is the whole point; the
write is three lines.

    .venv/Scripts/python.exe scripts/backfill_detector_vocab.py            # report only
    .venv/Scripts/python.exe scripts/backfill_detector_vocab.py --write
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments", "m1"))

# The mapping `promote_artifacts.write_metadata` and `ingest_folder` both build their records
# through. Imported rather than restated for the reason in `promote_artifacts.detector_vocabulary`:
# a copied list would keep claiming six categories after a swap changed them.
from scenesearch.metadata.extract import COCO_TO_VOCAB  # noqa: E402


def observed_categories(metadata_path: str) -> set[str]:
    """Every category any frame in the corpus carries."""
    found: set[str] = set()
    with open(metadata_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                found |= set(json.loads(line).get("objects", {}))
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description="Declare the detector vocabulary on an existing corpus.")
    ap.add_argument("--artifacts", default=os.path.join(ROOT, "data", "artifacts"))
    ap.add_argument("--write", action="store_true", help="apply; without it the script only reports")
    args = ap.parse_args()

    provenance_path = os.path.join(args.artifacts, "provenance.json")
    with open(provenance_path, encoding="utf-8") as f:
        provenance = json.load(f)

    vocabulary = sorted(set(COCO_TO_VOCAB.values()))
    observed = observed_categories(os.path.join(args.artifacts, "metadata.jsonl"))
    print(f"vocabulary  {', '.join(vocabulary)}")
    print(f"observed    {', '.join(sorted(observed)) or '(none)'}")

    stray = observed - set(vocabulary)
    if stray:
        sys.exit(
            f"\nREFUSED: {', '.join(sorted(stray))} appear in metadata.jsonl but not in "
            f"COCO_TO_VOCAB, so this corpus was not built by that mapping. Declaring this "
            f"vocabulary would refuse searches the archive can answer."
        )

    declared = (provenance.get("detector") or {}).get("vocabulary")
    if declared == vocabulary:
        print("\nalready declared, and identical — nothing to do")
        return
    if declared:
        sys.exit(
            f"\nREFUSED: a different vocabulary is already declared ({', '.join(declared)}). "
            f"Resolve by hand; overwriting one refusal rule with another is not a backfill."
        )

    # The gap this closes, stated in the terms that matter: categories the *parser* will happily
    # emit from a user's query and the corpus can never hold.
    from typing import get_args

    from src.models.schemas import Category

    refusable = sorted(set(get_args(Category)) - set(vocabulary))
    print(f"\nparser accepts but corpus cannot hold: {', '.join(refusable) or '(none)'}")
    if not args.write:
        print("\nreport only — pass --write to apply")
        return

    provenance.setdefault("detector", {})["vocabulary"] = vocabulary
    provenance["detector"].setdefault(
        "note",
        "vocabulary backfilled 2026-08-14 by scripts/backfill_detector_vocab.py; the corpus "
        "itself is unchanged, and every category it carries was verified inside this list",
    )
    with open(provenance_path, "w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2)
    print(f"\nwritten -> {os.path.relpath(provenance_path, ROOT)}")


if __name__ == "__main__":
    main()
