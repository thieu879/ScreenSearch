"""Add per-instance geometry to an already-promoted `metadata.jsonl`, in place.

**Why this is not just "re-run promote_artifacts".** That script also rebuilds thumbnails, vectors
and captions. Thumbnails are the redacted set the privacy gate certifies, and regenerating them to
pick up a metadata field would put the 08-05 privacy work back in play for no reason. This touches
one file.

**Why it needs no GPU.** `instances` is re-derived from the *cached* detections
(`artifacts/metadata/detections_frcnn.jsonl`), which already holds every box for every frame. No
detector runs; the boxes are the same boxes that produced the `relations` already on disk.

**The safety check is the point of the script.** `objects` and `relations` carry every published
number — the +0.129 → +0.323 relational lift, `detector_agreement.json`, §9.3's recall table. This
recomputes them from the same cache and refuses to write if a single frame's pair differs, so a
change to `record_from_detections` that quietly moved a measured fact cannot land as a "backfill".

**It checks every existing key, and that is a correction.** The first version named the pair above
and compared only those. On 2026-08-12 it ran, reported them bit-identical — truthfully — and wrote
rows built solely from the rebuild, dropping `scene` from all 6,858 frames. `scene` comes from
`scripts/tag_scenes.py`, a pass that runs *after* promotion, so the rebuild never produced it and
the guard never looked. The `time` filter then matched nothing and refused nothing, because
`filters.py` treats an absent tag as "passes", so a 58%-night corpus went unfiltered in silence for
two days. The invariant is now the one the script actually claims: new keys may appear, nothing
already on disk may change or disappear.

    python scripts/backfill_instances.py \
        --dataroot ../../data/nuscene/trainval --version v1.0-trainval \
        --research-root experiments/m1/runs/trainval_9_10 \
        --scenes experiments/m1/corpus/trainval_9_10.txt

Needs the nuScenes devkit for per-frame intrinsics, so it runs in the research environment
(`ssv`), not `.venv`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from promote_artifacts import M1, REPO, load_manifest, resolve_paths, select_scenes  # noqa: E402


def read_existing(path: str) -> dict[str, dict]:
    """frame_id → the record currently on disk."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                out[row["frame_id"]] = row
    return out


def rebuild(nusc, rows: list[dict], research: str) -> dict[str, dict]:
    """frame_id → freshly derived record, including `instances` and `camera`."""
    import numpy as np

    sys.path.insert(0, M1)
    from scenesearch.metadata.extract import DetectionStore, record_from_detections

    cache = os.path.join(research, "artifacts/metadata/detections_frcnn.jsonl")
    dets = DetectionStore(cache_path=cache).detections_for([r["image_path"] for r in rows])
    out = {}
    for r in rows:
        sd = nusc.get("sample_data", nusc.get("sample", r["sample_token"])["data"]["CAM_FRONT"])
        k = np.array(nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])["camera_intrinsic"])
        out[r["item_id"]] = record_from_detections(
            dets[os.path.basename(r["image_path"])], k[0, 0], k[0, 2], sd["width"], sd["height"]
        )
    return out


def merged(old_rec: dict, new_rec: dict) -> dict:
    """The row to write: everything already on disk, with the rebuilt keys layered over it.

    `new_rec` alone is not the answer. The rebuild derives exactly what `record_from_detections`
    produces — `objects`, `relations`, `instances`, `camera` — and any field written by a *later*
    pass is simply absent from it. `scene` is written by `scripts/tag_scenes.py` after promotion,
    so replacing the row wholesale silently discards the tag rather than preserving it.
    """
    return {**old_rec, **new_rec}


def drifted(old: dict[str, dict], written: dict[str, dict]) -> list[str]:
    """Frames where a key already on disk changed or vanished — which this migration must never do.

    Checked against the record that will actually be **written**, not against the rebuild, because
    the two differ precisely where the bug lived.

    Every existing key, not a named pair. The original check listed `objects` and `relations`, and
    it verified them truthfully while the write step dropped `scene` from all 6,858 frames on
    2026-08-12: the tags were produced by a different pass, so the rebuild never carried them and
    nothing compared them. A guard that names the fields it protects cannot see a field nobody
    named — so this one states the invariant the migration actually claims, that it is additive.
    New keys may appear; nothing already recorded may move.
    """
    bad = []
    for fid, old_rec in old.items():
        new_rec = written.get(fid)
        if new_rec is None:
            bad.append(f"{fid}: missing from the rebuild")
            continue
        for key, was in old_rec.items():
            if key not in new_rec:
                bad.append(f"{fid}: `{key}` dropped (was {was!r})")
            elif new_rec[key] != was:
                bad.append(f"{fid}: {key} {was!r} -> {new_rec[key]!r}")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataroot", required=True)
    ap.add_argument("--version", default="v1.0-trainval")
    ap.add_argument("--out", default=os.path.join(REPO, "data"))
    ap.add_argument("--research-root", default=M1)
    ap.add_argument("--scenes", metavar="FILE")
    ap.add_argument("--dry-run", action="store_true", help="report and write nothing")
    args = ap.parse_args()

    research = os.path.abspath(args.research_root)
    target = os.path.join(args.out, "artifacts", "metadata.jsonl")
    old = read_existing(target)
    print(f"[current] {len(old)} frames in {target}")

    from nuscenes.nuscenes import NuScenes

    nusc = NuScenes(version=args.version, dataroot=args.dataroot, verbose=False)
    rows = load_manifest(os.path.join(research, "artifacts/dataset/manifest.jsonl"))
    if args.scenes:
        rows = select_scenes(nusc, rows, args.scenes)
    resolve_paths(nusc, rows)
    print(f"[rebuild] {len(rows)} manifest frames")

    new = rebuild(nusc, rows, research)
    written = {fid: merged(old[fid], new[fid]) for fid in old if fid in new}

    if bad := drifted(old, written):
        print(f"\n[REFUSED] {len(bad)} frames would lose or change an existing key. First 5:")
        for line in bad[:5]:
            print("   ", line)
        sys.exit("This migration is additive by definition; a drift here means the derivation moved.")
    print(f"[verified] every existing key bit-identical across all {len(old)} frames")

    n_inst = sum(len(r.get("instances", [])) for r in new.values())
    print(f"[new] {n_inst} instances ({n_inst / max(len(new), 1):.1f} per frame)")
    if args.dry_run:
        print("[dry-run] nothing written")
        return

    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        # Written in the existing file's order, and from the merged record, so a diff of the two
        # really does show only added keys — which is what this line claimed before it wrote
        # `new[fid]` alone and dropped every `scene` tag.
        for fid in old:
            f.write(json.dumps({"frame_id": fid, **written[fid]}) + "\n")
    os.replace(tmp, target)
    print(f"[written] {target}  ({os.path.getsize(target) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
