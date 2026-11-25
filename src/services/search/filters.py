"""Metadata filter — promote frames whose *detected* content satisfies the query's constraint.

Promoted from `experiments/m1/scenesearch/metadata/filter.py`; validated under experiment `026ab3a6`,
which took relational mAP-lift from **+0.129 to +0.323**. The case that argument rests on is q15,
"a car to the front-left": cars appear in 395 of 404 frames, so the query carries no object signal
and reduces to pure position, which every embedding gets wrong. It moves from below chance (−0.015)
to +0.352 here, because a structured filter does not care how common the object is.

**The facts come from pixels.** `data/artifacts/metadata.jsonl` is detector output plus camera
intrinsics, never nuScenes annotations — see `scripts/promote_artifacts.py`. In the experiment that
separation is what stops the filter grading itself; in the product it is what lets this work on an
archive that has no annotations at all, which is the entire premise.

**Applied as a rerank, not a hard filter.** Detector recall is weak for bus (0.41), bicycle (0.38)
and motorcycle (0.19), so dropping non-matching frames would permanently lose real results on a
miss. Promoting instead means a miss costs rank, not existence.

**Scene conditions joined the filter on 2026-08-02 (M2_DESIGN §11.2).** `time` is now a tagged field
in `metadata.jsonl`, so a query like `a cyclist at night` splits into `filter(time=night)` AND
`embedding("a cyclist")` instead of asking one 768-d vector to compose both — the tier where SigLIP2
used 1% of its headroom. The tag is SigLIP2 run as a zero-shot classifier over the pixels, measured
at 99.9% (`scripts/measure/measure_scene_tagger.py`); like everything else here it comes from the image and
not from any annotation. `weather` is deliberately *not* tagged — it scored 76.3% — so a rain
condition still falls through to the embedding, which is `ANNOTATED_AXES`' whole job.
"""

from __future__ import annotations

# Scene axes `metadata.jsonl` actually carries, kept in step with `scripts/tag_scenes.py:TAGGED_AXES`.
# Constraints on any other axis are ignored rather than failed: `weather` reaches this module from a
# correct parse of a real query, and treating "we never measured it" as "the frame does not have it"
# would demote every genuinely rainy frame in the corpus.
TAGGED_AXES = ("time",)


def tagged_values(metadata_of: dict[str, dict]) -> dict[str, set[str]]:
    """Which values each tagged axis actually takes across the whole corpus.

    A corpus-level census rather than a per-frame lookup, because it answers a question no single
    frame can: *does this archive contain any `night` frame at all*. `rejection.contradicted` is its
    only consumer (M2_DESIGN §10.8).

    An axis that some frames lack is omitted entirely rather than reported from the frames that have
    it. The same rule `satisfies` applies per frame — untagged is unknown, not non-matching — has to
    hold for the census, or a half-tagged corpus would refuse a query on the strength of its tagged
    half while the untagged half went unexamined.
    """
    if not metadata_of:
        return {}
    census = {}
    for axis in TAGGED_AXES:
        values = {(meta.get("scene") or {}).get(axis) for meta in metadata_of.values()}
        if None not in values:
            census[axis] = values
    return census


def declared_vocabulary(provenance: dict | None) -> set[str]:
    """The object categories the detector that built this corpus can emit **at all**.

    The object-side counterpart of `tagged_values`, and it reads `provenance.json` rather than
    counting `metadata.jsonl` deliberately. A census over the metadata answers "which categories did
    this run happen to find", and on the object side that is not evidence of absence: recall is 0.41
    for bus, 0.38 for bicycle, 0.19 for motorcycle, and `bicycle` is 64 frames of 6,858 — a slightly
    different threshold or corpus finds none, and a count-based rule would then tell a user *as a
    fact* that the archive holds no bicycles. That is the invisible-and-final error the whole band
    exists to avoid, stated in the one voice the product uses for certainty.

    The vocabulary answers a different question — which categories this corpus could express — and
    that is a property of the pipeline, not of sampling luck.

    ~~`COCO_TO_VOCAB` maps six classes, so `construction_vehicle`, `traffic_cone` and `barrier` are
    unreachable by construction, and zero frames of them really does mean none.~~ **That last clause
    was false and is the whole of issue #112.** Unreachable by the *pipeline* is not absent from the
    *footage*: all three are plainly present in the served corpus — 241 of 6,858 captions name
    traffic cones, and thumbnails show cones, a row of barriers and a forklift. Zero frames meant the
    detector could not represent them, and the product said the archive did not hold them. The
    parser's vocabulary was cut to these six on 2026-08-18 so no query can reach that inference.

    The function is unchanged and still sound for what it actually claims — *this corpus's detector
    cannot emit that category* — which is a fact about the pipeline. Only the reading of it as
    evidence of absence was wrong.

    Empty when undeclared, which makes every caller silent. A corpus ingested before the field
    existed must degrade to the caption check rather than to refusals — the same rule `tagged_values`
    applies to a half-tagged axis.
    """
    vocabulary = ((provenance or {}).get("detector") or {}).get("vocabulary")
    return set(vocabulary) if isinstance(vocabulary, list) else set()


def satisfies(meta: dict, constraint: dict) -> bool:
    """Does one frame's detected metadata satisfy the constraint?"""
    for cat in constraint.get("objects", []) or []:
        if meta.get("objects", {}).get(cat, 0) < 1:
            return False
    for cat, rels in (constraint.get("relations") or {}).items():
        have = set(meta.get("relations", {}).get(cat, []))
        if not set(rels) <= have:
            return False
    for key, val in (constraint.get("scene") or {}).items():
        # An untagged frame is unknown, not non-matching. Only frames tagged with a *different*
        # value fail, so a corpus promoted before tagging existed degrades to the old behaviour
        # instead of demoting every frame in it.
        if key in TAGGED_AXES and meta.get("scene", {}).get(key, val) != val:
            return False
    return True


def metadata_constraint(constraint: dict | None) -> dict | None:
    """Reduce a parsed constraint to the part `metadata.jsonl` can actually check.

    Returns None when nothing checkable was asked, which makes the filter a no-op — that is why
    single- and multi-condition queries were bit-identical with and without it in `026ab3a6`. The
    filter stays surgical by construction, not by tuning.

    Scene keys survive only for tagged axes. Passing `weather` through would produce a constraint
    that no frame satisfies, which `service.py:count_satisfying` reads as "the archive lacks this"
    and answers by relaxing — a confident wrong answer built out of a field we chose not to write.
    """
    if not constraint:
        return None
    scene = {k: v for k, v in (constraint.get("scene") or {}).items() if k in TAGGED_AXES}
    if not constraint.get("relations") and not scene:
        return None
    return {"objects": constraint.get("objects", []), "relations": constraint.get("relations") or {}, "scene": scene}


def satisfied_conditions(meta: dict | None, constraint: dict | None) -> list[str]:
    """Which conditions this frame meets, as labels for the UI (`rel:pedestrian:front_left`).

    Per-frame evidence, so a user can see *why* a result was returned rather than trusting a score.
    Labels match `groundtruth/predicates.py`, so UI evidence and eval conditions read alike.
    """
    if not meta or not constraint:
        return []
    out = [f"object:{c}" for c in constraint.get("objects", []) or [] if meta.get("objects", {}).get(c, 0) >= 1]
    for cat, rels in (constraint.get("relations") or {}).items():
        have = set(meta.get("relations", {}).get(cat, []))
        out.extend(f"rel:{cat}:{r}" for r in rels if r in have)
    out.extend(
        f"scene:{k}={v}" for k, v in (constraint.get("scene") or {}).items() if meta.get("scene", {}).get(k) == v
    )
    return out


class MetadataFilterReranker:
    """Moves frames satisfying `constraint` ahead of those that do not, order kept within groups."""

    name = "metadata-filter"

    def __init__(self, meta_of: dict[str, dict], constraint: dict | None):
        self.meta_of = meta_of
        self.constraint = constraint

    def rank(self, ranked: list[str], scores: dict[str, float]) -> list[str]:
        if not self.constraint:
            return ranked
        match, rest = [], []
        for item in ranked:
            meta = self.meta_of.get(item)
            (match if meta and satisfies(meta, self.constraint) else rest).append(item)
        return match + rest
