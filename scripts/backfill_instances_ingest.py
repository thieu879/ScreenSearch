"""Add per-instance geometry to a folder-ingested `metadata.jsonl`, in place — the `ingest_folder` twin
of `backfill_instances.py`.

**Why a second script rather than a flag.** `backfill_instances.py` enters through the nuScenes devkit
(`--dataroot`, `v1.0-trainval`, a manifest, `calibrated_sensor` intrinsics per frame). None of that
exists for footage ingested with `scripts/ingest_folder.py`, where the camera is a *declared* FOV and
the frame list is whatever the extractor produced. The two share the part that matters — `merged` and
`drifted`, the additive-migration guard — which are imported from it rather than copied.

**Why it exists at all.** `instances` was added on 2026-08-12; `data/staging/hanoi` was ingested on
08-11, so it carries `objects` and `relations` and **no boxes at all** — 0 of 2,211 frames. Without
them the corpus cannot answer a relation *between* two objects ("a motorbike to the right of a bus"),
because after `record_from_detections` returns, which motorbike and which bus are gone. It also cannot
be re-banded without re-detecting: the ±30° bands are inherited from nuScenes' 360° annotation space,
and on this corpus's declared 90° camera they land very differently — 41% of Hanoi's relation labels
are off-centre against 18% of nuScenes'. Re-tuning that is the 08-22 gate, and it reads the boxes.

**Why it needs no GPU.** The per-clip detector caches the ingest wrote are still on disk
(`<workdir>/<video_id>/artifacts/metadata/detections_resnet50_v2.jsonl`) and cover the staged corpus
exactly: 2,211 of 2,211 frame ids, none missing, none spare. No detector runs, and the boxes are the
same boxes that produced the `relations` already recorded.

**The frame set comes from `metadata.jsonl`, never from the image directory.** `data/extracted_keyframes`
now holds the 08-13 re-extraction, which is a *different selection* — 43 of clip01's 60 sidecar frames
are in the corpus. Walking images would silently rebuild the wrong set; walking the caches and
intersecting with what is already recorded cannot.

**The guard is the point, and it doubles as the check on the camera.** `objects` and `relations` are
recomputed from the same cache and the write is refused if a single frame's existing key moves. That
also proves the geometry inputs: `relations` is a function of `fx`, which is a function of the declared
FOV and the image width, so wrong values cannot produce identical bands. Nothing here is trusted that
the guard cannot verify.

    .venv/Scripts/python.exe scripts/backfill_instances_ingest.py \
        --artifacts data/staging/hanoi/artifacts --workdir data/staging/hanoi_work --dry-run

`.venv` is enough — `record_from_detections` is pure stdlib and no model is loaded.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "experiments", "m1"))

from backfill_instances import drifted, merged  # noqa: E402 -- one guard, not a second copy
from ingest_folder import frame_id_for  # noqa: E402 -- one id derivation, not a second copy
from scenesearch.metadata.extract import drop_ego_boxes, record_from_detections  # noqa: E402

DETECTIONS = "detections_resnet50_v2.jsonl"


def read_jsonl(path: str) -> list[dict]:
    """Read a JSONL artifact, preserving order — the rewrite depends on it."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def cache_index(workdir: str) -> dict[str, tuple[str, list[dict]]]:
    """`frame_id` → (video_id, detections), from the per-clip caches the ingest already wrote.

    Keyed through `frame_id_for` because the caches are keyed by *image basename* and every clip is
    numbered from the same starting frame — the collision `ingest_folder` gives each video its own
    workdir to avoid.
    """
    index: dict[str, tuple[str, list[dict]]] = {}
    for cache in sorted(glob.glob(os.path.join(workdir, "*", "artifacts", "metadata", DETECTIONS))):
        video_id = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(cache))))
        for row in read_jsonl(cache):
            index[frame_id_for(video_id, row["image"])] = (video_id, row["dets"])
    return index


def camera_of(provenance: dict, video_id: str) -> tuple[float, float]:
    """The declared `hfov_deg` and `bonnet_top` for one clip, from the corpus's own provenance.

    Read per video rather than once: `ingest_folder` allows a corpus to hold clips from more than one
    camera, and applying one clip's FOV to another's frames is the §10.5 failure applied to a subset.
    """
    intrinsics = provenance.get("intrinsics") or {}
    hfov = (intrinsics.get("hfov_deg") or {}).get(video_id)
    bonnet = (intrinsics.get("bonnet_top") or {}).get(video_id)
    if hfov is None or bonnet is None:
        raise KeyError(f"provenance.json records no hfov_deg/bonnet_top for {video_id!r}")
    return float(hfov), float(bonnet)


def rebuild(old: list[dict], index: dict[str, tuple[str, list[dict]]], ctx: dict) -> dict[str, dict]:
    """Recompute each frame's record from its cached boxes, at the corpus's declared geometry."""
    width, height, provenance = ctx["width"], ctx["height"], ctx["provenance"]
    out: dict[str, dict] = {}
    for row in old:
        found = index.get(row["frame_id"])
        if found is None:
            continue
        video_id, dets = found
        hfov, bonnet = camera_of(provenance, video_id)
        fx = (width / 2) / math.tan(math.radians(hfov / 2))
        out[row["frame_id"]] = record_from_detections(
            drop_ego_boxes(dets, (width, height), bonnet), fx, width / 2, width, height
        )
    return out


def parse_args() -> argparse.Namespace:
    """CLI. Defaults point at the staged Hanoi corpus, which is the one missing its boxes."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--artifacts", default=os.path.join("data", "staging", "hanoi", "artifacts"))
    parser.add_argument("--workdir", default=os.path.join("data", "staging", "hanoi_work"))
    parser.add_argument("--width", type=int, default=1440, help="keyframe width; verified by the guard")
    parser.add_argument("--height", type=int, default=1080, help="keyframe height; verified by the guard")
    parser.add_argument("--dry-run", action="store_true", help="report and write nothing")
    return parser.parse_args()


def report(old: list[dict], new: dict[str, dict], written: dict[str, dict]) -> None:
    """What changed, before anything is written. Refuses on any drift in an existing key."""
    if bad := drifted({row["frame_id"]: row for row in old}, written):
        print(f"\n[REFUSED] {len(bad)} frames would lose or change an existing key. First 5:")
        for line in bad[:5]:
            print("   ", line)
        sys.exit("This migration is additive by definition; a drift here means the geometry is wrong.")
    print(f"[verified] every existing key bit-identical across all {len(old)} frames")
    n_inst = sum(len(r.get("instances", [])) for r in new.values())
    print(f"[new] {n_inst} instances ({n_inst / max(len(new), 1):.1f} per frame)")


def main() -> None:
    """Rebuild from the cached boxes, verify nothing already recorded moves, then write."""
    args = parse_args()
    artifacts = args.artifacts if os.path.isabs(args.artifacts) else os.path.join(ROOT, args.artifacts)
    workdir = args.workdir if os.path.isabs(args.workdir) else os.path.join(ROOT, args.workdir)
    target = os.path.join(artifacts, "metadata.jsonl")

    old = read_jsonl(target)
    with open(os.path.join(artifacts, "provenance.json"), encoding="utf-8") as f:
        provenance = json.load(f)
    index = cache_index(workdir)
    print(f"[current] {len(old)} frames in {os.path.relpath(target, ROOT)}")
    print(f"[caches]  {len(index)} frames across {len(glob.glob(os.path.join(workdir, '*')))} clip workdirs")

    ctx = {"width": args.width, "height": args.height, "provenance": provenance}
    new = rebuild(old, index, ctx)
    if len(new) != len(old):
        sys.exit(f"caches cover {len(new)} of {len(old)} recorded frames; refusing a partial backfill")
    written = {fid: merged(row, new[fid]) for row in old if (fid := row["frame_id"]) in new}
    report(old, new, written)
    if args.dry_run:
        print("[dry-run] nothing written")
        return

    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for row in old:
            f.write(json.dumps(written[row["frame_id"]]) + "\n")
    os.replace(tmp, target)
    print(f"[written] {os.path.relpath(target, ROOT)}  ({os.path.getsize(target) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
