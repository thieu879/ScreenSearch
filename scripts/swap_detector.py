"""Re-derive `metadata.jsonl` from a different detector's cached boxes, and record exactly what moved.

Step 2 of the spatial re-band plan. `resnet50_v2` is measured better on the fact the whole plan came
from — `pedestrian front_right` precision 0.438 -> 0.617 — and its cache already covers all 6,858
frames, so this is a re-derivation and not a detection run.

**Why this needs its own tool rather than `backfill_instances.py`.** That script's guard refuses to
write when `objects` or `relations` move, which is correct for a migration that claims to be
additive. Here the movement *is* the change. The guard's job therefore inverts: instead of blocking
the write it has to describe it, because that description is the evidence the step is measured by.
Nothing is silently overwritten either way — `--write` is required, and without it this reports.

**`--control` is what makes the rest trustworthy.** Run with the detector the corpus already carries
and every record must come back bit-identical. If it does, the derivation here — per-frame `fx`/`cx`
read back from the corpus's own `camera` key, no ego filter, same `record_from_detections` — is
provably the one that produced what is on disk, and a diff against another detector is attributable
to the detector alone. If it does not, the diff would be measuring this script.

**Two details that are easy to get wrong, both learned from `promote_artifacts.write_metadata`:**

- **Intrinsics are per frame, not per dataset.** trainval carries three distinct CAM_FRONT matrices
  with `cx` from 786.7 to 826.6. Applying one frame's camera to another silently misplaces the
  relation bands, which is M2_DESIGN §10.5's failure.
- **The nuScenes path applies no `drop_ego_boxes`.** That is the folder ingest's ego filter, driven
  by a declared `bonnet_top`; nuScenes never used it. Adding it here would look like a detector
  effect and would not be one.

**This changes what gets redacted, and that is not optional follow-up.** The `person` boxes this
swaps are the same boxes `anonymise.py` turns into head bands. Re-run it with the same
`--retrieval-cache`, re-verify, and treat the thumbnails as part of this change rather than after it;
`eval/results/redaction_gap_nuscenes.json` measures which direction that moves.

    .venv/Scripts/python.exe scripts/swap_detector.py --control
    .venv/Scripts/python.exe scripts/swap_detector.py --detector resnet50_v2
    .venv/Scripts/python.exe scripts/swap_detector.py --detector resnet50_v2 --write
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "experiments", "m1"))

from scenesearch.metadata.extract import DETECTORS, SCORE_THRESHOLD, record_from_detections  # noqa: E402

RUN = os.path.join(ROOT, "experiments", "m1", "runs", "trainval_9_10", "artifacts")
CACHES = {"mobilenet_v3": "detections_frcnn.jsonl", "resnet50_v2": "detections_resnet50_v2.jsonl"}
DERIVED = ("objects", "relations", "instances", "camera")


def read_jsonl(path: str) -> list[dict]:
    """A JSONL artifact as a list, order preserved — the rewrite depends on it."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def detections_by_frame(run: str, detector: str) -> dict[str, list[dict]]:
    """`frame_id` → boxes, joining the image-keyed cache through the manifest."""
    key = {}
    for row in read_jsonl(os.path.join(run, "dataset", "manifest.jsonl")):
        key[os.path.basename(row["image_path"].replace("\\", "/"))] = row["item_id"]
    out = {}
    for row in read_jsonl(os.path.join(run, "metadata", CACHES[detector])):
        if row["image"] in key:
            out[key[row["image"]]] = row["dets"]
    return out


def exact_cameras(run: str, dataroot: str, version: str) -> dict[str, dict]:
    """`frame_id` → unrounded intrinsics, straight from `calibrated_sensor`.

    The corpus's own `camera` key rounds `fx`/`cx` to one decimal, which is right for a record a
    human reads and wrong as an input: re-deriving from it shifts `instance.angle` by 0.1 deg on 317
    frames. That is far too small to move a 30 deg band — `relations` reproduces either way — but it
    would land in the detector diff and be read as a detector effect. Bands are unaffected; the
    stored angle is not, so take the exact value where the devkit is available.
    """
    from nuscenes.nuscenes import NuScenes

    nusc = NuScenes(version=version, dataroot=dataroot, verbose=False)
    out = {}
    for row in read_jsonl(os.path.join(run, "dataset", "manifest.jsonl")):
        sd = nusc.get("sample_data", nusc.get("sample", row["sample_token"])["data"]["CAM_FRONT"])
        k = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])["camera_intrinsic"]
        out[row["item_id"]] = {"fx": k[0][0], "cx": k[0][2], "width": sd["width"], "height": sd["height"]}
    return out


def rebuild_row(row: dict, dets: list[dict], cam: dict | None = None) -> dict:
    """One record, at that frame's own camera and with no ego filter."""
    cam = cam or row.get("camera")
    if not cam:
        raise KeyError(f"{row['frame_id']} has no `camera` key; run backfill_instances.py first")
    return record_from_detections(dets, cam["fx"], cam["cx"], cam["width"], cam["height"])


def diff_counts(old: dict, new: dict) -> dict[str, int]:
    """How many frames moved, per derived key — the description that replaces the refusal."""
    moved = dict.fromkeys(DERIVED, 0)
    for key in DERIVED:
        moved[key] = sum(1 for fid, rec in new.items() if old[fid].get(key) != rec.get(key))
    return moved


def presence_census(records: dict[str, dict]) -> dict[str, int]:
    """Frames containing each category — what a category query can actually reach.

    The retrieval-relevant number, and not the same as the box count: `bicycle` was 64 frames of
    6,858, which is unsearchable however good the ranker is.
    """
    census: dict[str, int] = {}
    for rec in records.values():
        for cat in rec.get("objects") or {}:
            census[cat] = census.get(cat, 0) + 1
    return dict(sorted(census.items()))


def relation_census(records: dict[str, dict]) -> dict[str, int]:
    """Relation labels by band, which is the number the re-band will later move again."""
    census: dict[str, int] = {}
    for rec in records.values():
        for bands in (rec.get("relations") or {}).values():
            for band in bands:
                census[band] = census.get(band, 0) + 1
    return dict(sorted(census.items()))


def parse_args() -> argparse.Namespace:
    """CLI. Reporting is the default; writing is opt-in and control is a separate assertion."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--artifacts", default=os.path.join(ROOT, "data", "artifacts"))
    parser.add_argument("--run", default=RUN)
    parser.add_argument("--detector", default="resnet50_v2", choices=sorted(CACHES))
    parser.add_argument("--control", action="store_true", help="re-derive the shipped detector; demand no drift")
    parser.add_argument("--dataroot", default=os.path.join(ROOT, "..", "data", "nuscene", "trainval"))
    parser.add_argument("--version", default="v1.0-trainval")
    parser.add_argument("--stored-camera", action="store_true", help="skip the devkit; angles drift 0.1 deg")
    parser.add_argument("--write", action="store_true", help="rewrite metadata.jsonl in place")
    parser.add_argument("--out", default=os.path.join(ROOT, "eval", "results", "detector_swap_nuscenes.json"))
    return parser.parse_args()


def report(old: dict, new: dict, args: argparse.Namespace) -> dict[str, Any]:
    """Print and return what moved; in control mode a single moved frame is fatal."""
    moved = diff_counts(old, new)
    before, after = relation_census(old), relation_census(new)
    print(f"[frames]   {len(new)} re-derived with {args.detector}")
    print("[moved]    " + "  ".join(f"{k}={v}" for k, v in moved.items()))
    print(f"[relations] before {before}")
    print(f"[relations] after  {after}")
    if args.control:
        if any(moved.values()):
            sys.exit("[REFUSED] control run must reproduce the corpus exactly; the derivation is wrong")
        print("[control]  every record bit-identical - the derivation is the one that built this corpus")
    return {
        "detector": args.detector,
        "frames": len(new),
        "frames_moved": moved,
        "relations_before": before,
        "relations_after": after,
        "frames_with_category_before": presence_census(old),
        "frames_with_category_after": presence_census(new),
    }


def stamp_detector(artifacts: str, detector: str) -> None:
    """Record which detector produced this corpus, beside the corpus.

    It did not say. `promote_artifacts` wrote a `model` field, then `backfill_detector_vocab.py`
    replaced the whole `detector` block with a vocabulary on 2026-08-14 and the model went with it —
    so between then and now the only way to tell what emitted these boxes was to know which script
    had last been run. `anonymisation.source` names its cache and `scene_tags` names its encoder;
    this is the same claim for the boxes, and the band-stamp lesson from PR #117 is that a corpus
    which cannot describe itself gets described from memory instead.

    Merged rather than replaced, because `vocabulary` is a separate true statement about the same
    detector and re-deriving it is not this script's job.
    """
    path = os.path.join(artifacts, "provenance.json")
    with open(path, encoding="utf-8") as f:
        prov = json.load(f)
    prov["detector"] = {
        **(prov.get("detector") or {}),
        "model": detector,
        "builder": DETECTORS[detector][0],
        "score_threshold": SCORE_THRESHOLD,
        "swapped_by": "scripts/swap_detector.py",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prov, f, indent=2)


def main() -> None:
    """Re-derive, describe the movement, and write only when asked."""
    args = parse_args()
    target = os.path.join(args.artifacts, "metadata.jsonl")
    rows = read_jsonl(target)
    dets = detections_by_frame(args.run, args.detector)
    missing = [r["frame_id"] for r in rows if r["frame_id"] not in dets]
    if missing:
        sys.exit(f"{len(missing)} frames have no boxes in the {args.detector} cache (first: {missing[0]})")

    cams: dict[str, dict] = {}
    if not args.stored_camera:
        print(f"[devkit]   reading exact intrinsics from {os.path.relpath(args.dataroot, ROOT)} ...")
        cams = exact_cameras(args.run, args.dataroot, args.version)

    old = {r["frame_id"]: r for r in rows}
    new = {r["frame_id"]: rebuild_row(r, dets[r["frame_id"]], cams.get(r["frame_id"])) for r in rows}
    record = report(old, new, args)

    if not args.write:
        print("[dry-run]  nothing written - pass --write to apply")
        return
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps({**row, **new[row["frame_id"]]}) + "\n")
    os.replace(tmp, target)
    stamp_detector(args.artifacts, args.detector)
    # A second `--write` against an already-swapped corpus moves nothing, and writing *that* over the
    # record replaces the evidence of the swap with a description of a no-op — which is how a change
    # comes to look like it never happened. Observed immediately: the run that added the provenance
    # stamp flattened `relations_before` onto `relations_after`. The corpus is still rewritten, since
    # that is idempotent; only the record is protected.
    if not any(record["frames_moved"].values()) and os.path.exists(args.out):
        print(f"[kept]     nothing moved; left {os.path.relpath(args.out, ROOT)} as the record of the real swap")
        return
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    print(f"[written]  {os.path.relpath(target, ROOT)} and {os.path.relpath(args.out, ROOT)}")


if __name__ == "__main__":
    main()
