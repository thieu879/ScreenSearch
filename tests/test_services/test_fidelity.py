"""Pin the product query path to the measured research result.

`src/services/search/` is a promotion of `experiments/m1/scenesearch/`, and the research package
deliberately stays where it is as the evidence trail. Two copies of the same logic drift, and the
drift is silent — the service keeps answering, just not with the numbers anyone measured. This is
what makes that impossible: the ported path must still reproduce experiment **`40095e80`**, the
SigLIP2 baseline whose per-query results are committed under `experiments/m1/outputs/`.

It also covers a class of bug no unit test would catch: `scripts/promote_artifacts.py` rebuilds the
vector matrix and its id ordering. If a row were misaligned, every module here would still pass its
own tests while the service returned confident results for the wrong frames. A top-1 score computed
from the promoted artifacts and compared against the research run catches exactly that.

Query vectors are a committed fixture rather than freshly encoded, so this runs in CI without a
400 MB model download. `test_encoder_has_not_drifted` re-derives them and is marked `slow`.

**Two of these tests read a frozen corpus, not the shipped one.** `40095e80` was measured over a
specific 404 frames, and its per-query top-1 scores and distinct@10 are properties of *that* corpus.
Growing the archive changes both — a new frame can outrank the old top-1 — so pinning the live
corpus to those numbers would make every corpus expansion look like a regression, and the usual
response to a test that fails for an expected reason is to weaken it.

`tests/fixtures/corpus_40095e80/` keeps the measured corpus available forever, at 2.1 MB. The
promotion checks below deliberately stay on the *live* corpus, because their job is to catch a
misaligned row in whatever ships today.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASELINE = os.path.join(REPO, "experiments/m1/outputs/experiment_40095e80/per_query.json")
FIXTURES = os.path.join(REPO, "tests/fixtures")
# The corpus `40095e80` was measured over, kept independent of whatever `data/artifacts/` holds now.
FROZEN_CORPUS = os.path.join(FIXTURES, "corpus_40095e80")

# The research run stores float32 similarities via json.dump; agreement well below the gap between
# adjacent scores (~2e-4, see M2_DESIGN §4) is what makes a match meaningful rather than lucky.
TOLERANCE = 1e-6


@pytest.fixture(scope="module")
def query_vectors() -> tuple[list[str], np.ndarray]:
    with open(os.path.join(FIXTURES, "query_vectors.json"), encoding="utf-8") as f:
        ids = json.load(f)["ids"]
    return ids, np.load(os.path.join(FIXTURES, "query_vectors.npy"), allow_pickle=False)


@pytest.fixture(scope="module")
def baseline() -> dict[str, dict]:
    if not os.path.exists(BASELINE):
        pytest.skip("experiment 40095e80 not present; run run_eval --encoder siglip2")
    with open(BASELINE, encoding="utf-8") as f:
        return {row["id"]: row for row in json.load(f)}


@pytest.fixture(scope="module")
def frozen():
    """The 404-frame corpus `40095e80` was measured over, and its index.

    Loaded through the same `Corpus.load` the service uses, so the row-count and row-order checks
    in `artifacts.py` still run over it — the fixture is pinned data, not a pinned code path.
    """
    from src.services.search.artifacts import Corpus
    from src.services.search.index import FlatIndex

    corpus = Corpus.load(FROZEN_CORPUS)
    return corpus, FlatIndex(corpus.vectors, corpus.frame_ids)


def test_top1_scores_reproduce_experiment_40095e80(query_vectors, baseline, frozen):
    """Every query's top-1 similarity must match the research run.

    This is the whole fidelity claim in one assertion: same vectors, same ordering, same arithmetic.
    """
    _, index = frozen

    ids, vectors = query_vectors
    mismatches = []
    for qid, vec in zip(ids, vectors):
        if qid not in baseline:
            continue
        ranked, scores = index.search(vec)
        got, want = scores[ranked[0]], baseline[qid]["top1"]
        if abs(got - want) > TOLERANCE:
            mismatches.append(f"{qid}: {got:.8f} != {want:.8f}")
    assert not mismatches, "ported path diverged from 40095e80:\n" + "\n".join(mismatches)


def test_distinct_scenes_reproduce_experiment_40095e80(query_vectors, baseline, frozen):
    """Top-10 *membership* must match too, not just the best score.

    `distinct@10` is a function of which ten frames come back and which clip each belongs to, so it
    checks the promoted `scene_of` mapping and the tail of the ranking — neither of which a top-1
    comparison can see.
    """
    corpus, index = frozen
    ids, vectors = query_vectors
    for qid, vec in zip(ids, vectors):
        want = baseline.get(qid, {}).get("distinct@10")
        if want is None:
            continue  # negatives and temporal queries score no ranking metrics
        ranked, _ = index.search(vec)
        got = len({corpus.scene_of.get(f, f) for f in ranked[:10]})
        assert got == want, f"{qid}: distinct@10 {got} != {want}"


def test_promoted_vectors_match_the_research_matrix():
    """`data/artifacts/vectors.npy` must be the same matrix, in the same row order, as m1's cache.

    Reads the **live** corpus on purpose. Its job is to catch a misaligned row in whatever ships
    today, so freezing it would retire the check the moment the corpus is regenerated — which is
    exactly when a promotion bug is most likely.

    *Which* research cache to compare against comes from the artifacts themselves. This path used to
    be hardcoded to the mini run, which was correct while only one corpus existed and quietly wrong
    the moment a second appeared under `experiments/m1/runs/`: the test then compared a 6,858-frame
    corpus against a 404-frame cache and reported "promotion reordered the corpus" — a true-looking
    failure with a false cause, and the kind that gets a real check deleted.
    """
    from src.services.search.artifacts import get_corpus

    corpus = get_corpus()
    outputs = corpus.provenance.get("research_outputs", "experiments/m1/outputs")
    research = os.path.join(REPO, outputs, "emb_openclip_ViT-B-16-SigLIP2_webli.npy")
    if not os.path.exists(research):
        pytest.skip(f"research embedding cache not present at {outputs}")

    with open(research.replace(".npy", ".meta.json")) as f:
        research_ids = json.load(f)["ids"]
    assert corpus.frame_ids == research_ids, "promotion reordered the corpus"
    np.testing.assert_allclose(corpus.vectors, np.load(research, allow_pickle=False), atol=0)


@pytest.mark.slow
def test_encoder_has_not_drifted(query_vectors):
    """Re-encode the benchmark queries and check they still produce the committed fixture.

    Separate and opt-in because it downloads the model. Without it, an encoder or open_clip upgrade
    could silently change every query embedding while the fast tests above kept passing against
    stale vectors.
    """
    from src.services.search.encoder import get_query_encoder

    with open(os.path.join(FIXTURES, "query_vectors.json"), encoding="utf-8") as f:
        texts = json.load(f)["texts"]
    _, expected = query_vectors
    encoder = get_query_encoder()
    fresh = np.stack([encoder.encode(t) for t in texts])
    np.testing.assert_allclose(fresh, expected, atol=1e-5)
