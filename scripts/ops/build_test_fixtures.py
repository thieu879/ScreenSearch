"""Precompute query embeddings for the fidelity test.

`tests/test_services/test_fidelity.py` checks that the promoted artifacts plus the ported query path
still reproduce experiment `40095e80`. Doing that end-to-end needs the SigLIP2 text tower, which is
a ~400 MB download and several seconds of load — acceptable locally, wasteful on every CI run for a
check whose real subject is the *index and artifacts*, not the encoder.

So the query vectors are computed once here and committed (45 x 768 floats, 138 KB). CI then pins
the artifact + index + reranker path deterministically with no model at all, and a separate test
marked `slow` re-derives the vectors to confirm the encoder itself has not drifted.

Run with the research environment, which already has open_clip:

    C:/Users/Precision/ssv/Scripts/python.exe scripts/ops/build_test_fixtures.py
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import yaml

# One level deeper than a top-level script, so the repo root counts three. `scripts/` must be
# added explicitly: running this file puts `scripts/ops/` on sys.path[0], not `scripts/`.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts"))
QUERIES = os.path.join(REPO, "experiments/m1/scenesearch/groundtruth/queries.yaml")
OUT_DIR = os.path.join(REPO, "tests/fixtures")


def main() -> None:
    sys.path.insert(0, os.path.join(REPO, "experiments/m1"))
    from scenesearch.encoders.siglip import SiglipEncoder

    with open(QUERIES, encoding="utf-8") as f:
        queries = yaml.safe_load(f)["queries"]

    encoder = SiglipEncoder()
    ids = [q["id"] for q in queries]
    vectors = np.stack([encoder.encode_text(q["text"])[0] for q in queries])

    os.makedirs(OUT_DIR, exist_ok=True)
    np.save(os.path.join(OUT_DIR, "query_vectors.npy"), vectors.astype("float32"))
    with open(os.path.join(OUT_DIR, "query_vectors.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"ids": ids, "texts": [q["text"] for q in queries], "encoder": encoder.name, "experiment": "40095e80"},
            f,
            indent=2,
        )
    print(f"wrote {vectors.shape} query vectors for {len(ids)} queries -> {OUT_DIR}")


if __name__ == "__main__":
    main()
