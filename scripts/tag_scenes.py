"""Tag every frame's scene conditions from pixels, at ingest — M2_DESIGN §11.2.

SigLIP2 uses **100%** of its headroom on `driving at night` and **1%** on `a wet road at night with
a pedestrian`. A CLIP-family model encodes a bag of concepts and dilutes the rest, so the fix is to
stop asking the embedding to *compose* scene conditions and promote them to structured fields —
exactly what §9 did for spatial relations. `a cyclist at night` then becomes `filter(time=night)`
AND `embedding("a cyclist")`: the night half exact, the embedding half undiluted.

Cost is a matmul. Every image vector already sits in `vectors.npy`, so tagging is a dot product
against two text prompts — no new model, no new ingest pass over the pixels, no new dependency.

**Only `time` is written, and that is a measured decision, not a simplification.**
`scripts/measure/measure_scene_tagger.py` scored both axes against the annotation-derived gold on all 6,858
frames:

    time     99.9%  (P 100.0 / R 99.8, AP 1.000)   -> tagged here
    weather  76.3%  (P  48.2 / R 87.2, AP 0.742)   -> left to the embedding

§11.3 called that asymmetry in advance and said to ship the tag per class rather than as a pair.
Rain is not merely below the 95% bar — its *ranking* is poor too (AP 0.742, best-possible-threshold
accuracy 87.3%), so no cutoff rescues it. The failure is concentrated: 94% of its false positives
are night frames, where wet asphalt and dark asphalt look alike. Split by the time tag, daytime rain
scores 97.0% (AP 0.999) and night rain 61.3% (AP 0.303) — which makes a day-conditioned rain tag the
obvious next thing to try, on frames that are not these ones. It is not shipped here because it was
found by reading the failure, and §11.4 is explicit that scoring a choice on the corpus that
suggested it proves nothing.

**The tag comes from pixels, never from `scene.description`.** That is the same line
`write_metadata()` holds for the detector, and it is what makes the measurement above mean
something: the gold derives from that free text, so a tag sharing its source would score beautifully
and prove nothing (§11.4). It is also the product requirement — a customer's archive has keyframes
and no labels, and this needs none.

Idempotent, and safe to run in either environment: it reads `vectors.npy` rather than images, so it
needs neither the devkit nor a dataroot.

    python scripts/tag_scenes.py                # tag data/artifacts in place
    python scripts/tag_scenes.py --dry-run      # report the distribution, write nothing
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from _console import use_utf8  # noqa: E402, F401 -- console encoding; imported for effect

from src.services.search.encoder import SiglipTextEncoder  # noqa: E402

# The four prompts of §11.2, one symmetric pair per axis. `measure_scene_tagger.py` imports this
# constant rather than keeping its own copy: the measurement has to score the prompts that actually
# ship, or its accuracy describes a tagger nobody runs.
#
# First key of each pair is the positive class. Fixed before any number was looked at — see
# `--sweep` in the measurement script for how much the wording moves (time: barely; weather: a lot,
# and never far enough to matter).
PROMPTS: dict[str, dict[str, str]] = {
    "time": {
        "night": "a photo of a road at night",
        "day": "a photo of a road during the day",
    },
    "weather": {
        "rain": "a photo of a road in the rain",
        "clear": "a photo of a road in clear weather",
    },
}

# Which axes get written. Keep this in step with the measurement: an axis belongs here only once it
# has cleared SHIP_ACCURACY on a corpus it was not tuned on.
TAGGED_AXES: tuple[str, ...] = ("time",)

# §11.3's bar. A structured tag is consumed as if it were a fact, so it has to be nearly one — the
# embedding it replaces is at least visibly fuzzy, whereas a wrong tag is confidently wrong.
SHIP_ACCURACY = 0.95

# The encoder that produced `vectors.npy`, per data/artifacts/provenance.json. Hardcoded rather than
# read from settings so this runs in the research environment too; `main` checks it against
# provenance and refuses to write if they disagree, which is the failure that would matter — text
# and image vectors from different models share a shape and nothing else.
ENCODER = ("ViT-B-16-SigLIP2", "webli")


def tag_axis(vectors: np.ndarray, axis: str) -> list[str]:
    """Classify every frame on one axis, by argmax over that axis's prompt pair.

    A signed margin (cosine to positive minus cosine to negative) rather than a tuned threshold:
    argmax fits nothing to this corpus, so the accuracy measured here is the accuracy a customer's
    archive gets. Both sides are L2-normalised, so the dot product is already a cosine.
    """
    positive, negative = list(PROMPTS[axis])
    encoder = SiglipTextEncoder(*ENCODER)
    direction = encoder.encode(PROMPTS[axis][positive]) - encoder.encode(PROMPTS[axis][negative])
    return [positive if m > 0 else negative for m in vectors @ direction]


def scene_tags(vectors: np.ndarray) -> list[dict[str, str]]:
    """One `{axis: class}` dict per frame, in `vectors` row order, over every shipped axis."""
    tagged = {axis: tag_axis(vectors, axis) for axis in TAGGED_AXES}
    return [{axis: values[i] for axis, values in tagged.items()} for i in range(vectors.shape[0])]


def merge_tags(rows: list[dict], tags: list[dict[str, str]]) -> list[dict]:
    """Attach each frame's tags under `scene`, leaving `objects` and `relations` untouched.

    Replaces `scene` outright rather than merging into it, so re-running after an axis is dropped
    from `TAGGED_AXES` clears the stale tag instead of leaving a value nothing will refresh.
    """
    if len(rows) != len(tags):
        raise ValueError(f"{len(rows)} metadata rows vs {len(tags)} tagged frames")
    return [{**row, "scene": tag} for row, tag in zip(rows, tags)]


def read_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def write_scene_tags(artifacts_dir: str, dry_run: bool = False) -> list[dict[str, str]]:
    """Tag `metadata.jsonl` in place from `vectors.npy`. Returns the per-frame tags.

    Called by `promote_artifacts.py` at the end of a full ingest, and runnable on its own against
    already-promoted artifacts. One implementation either way: a second copy is how the shipped tags
    and the measured ones drift apart.
    """
    vectors = np.load(os.path.join(artifacts_dir, "vectors.npy"), allow_pickle=False).astype("float32")
    meta_path = os.path.join(artifacts_dir, "metadata.jsonl")
    rows = read_jsonl(meta_path)
    tags = scene_tags(vectors)
    tagged = merge_tags(rows, tags)
    if not dry_run:
        write_jsonl(meta_path, tagged)
        stamp_provenance(artifacts_dir)
    return tags


def stamp_provenance(artifacts_dir: str) -> None:
    """Record which prompts and model produced the tags, beside the data they describe.

    Without this, `metadata.jsonl` carries `time` with no way to tell whether it came from these
    prompts, an earlier set, or an annotation file — and §11.4's whole argument rests on being able
    to answer that.
    """
    path = os.path.join(artifacts_dir, "provenance.json")
    with open(path, encoding="utf-8") as f:
        prov = json.load(f)
    prov["scene_tags"] = {
        "axes": list(TAGGED_AXES),
        "encoder": f"openclip:{ENCODER[0]}:{ENCODER[1]}",
        "prompts": {axis: PROMPTS[axis] for axis in TAGGED_AXES},
        "source": "pixels (SigLIP2 zero-shot over vectors.npy), never scene.description",
        "measurement": "eval/results/scene_tagger.json",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prov, f, indent=2)


def check_encoder(artifacts_dir: str) -> None:
    """Refuse to tag vectors this script's text tower does not share a space with."""
    with open(os.path.join(artifacts_dir, "provenance.json"), encoding="utf-8") as f:
        stored = json.load(f).get("encoder")
    expected = f"openclip:{ENCODER[0]}:{ENCODER[1]}"
    if stored and stored != expected:
        sys.exit(f"vectors.npy was built with {stored}, this tagger encodes text with {expected}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifacts", default=os.path.join(ROOT, "data", "artifacts"))
    ap.add_argument("--dry-run", action="store_true", help="report the distribution, write nothing")
    args = ap.parse_args()

    check_encoder(args.artifacts)
    tags = write_scene_tags(args.artifacts, dry_run=args.dry_run)
    print(
        f"{len(tags)} frames tagged on {list(TAGGED_AXES)}" + ("  [dry run — nothing written]" if args.dry_run else "")
    )
    for axis in TAGGED_AXES:
        counts: dict[str, int] = {}
        for tag in tags:
            counts[tag[axis]] = counts.get(tag[axis], 0) + 1
        spread = "  ".join(f"{k} {v} ({v / len(tags):.1%})" for k, v in sorted(counts.items()))
        print(f"  {axis:<8} {spread}")
    if not args.dry_run:
        print(f"\nwritten -> {os.path.relpath(os.path.join(args.artifacts, 'metadata.jsonl'), ROOT)}")


if __name__ == "__main__":
    main()
