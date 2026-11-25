"""Group near-duplicate frames by content instead of by the clock, so the diversity cap can see them.

`docs/tasks/task-stationary-runs.md` is the task; `measure_stationary_runs.py` is the measurement,
and this is the fix it argued for.

**The defect.** `diversity.py` caps the head at 2 frames per `scene_id`, and `ingest_folder.py`
builds `scene_id` as a fixed 20-second wall-clock bucket. While the camera is moving, elapsed time is
a fair proxy for changed content and the cap works. When the vehicle stops, a bucket boundary falls
in the middle of a visually frozen stretch, splitting one redundant moment across several groups —
and the cap then admits 2 from *each*. Measured on the staged Hanoi corpus: 133 of 196 near-duplicate
runs cross a bucket boundary, and four could fill all ten slots of a result page with one moment.
`clip12` is 30 near-identical frames over 7 buckets.

**Why this merges every near-duplicate run and not just the dead ones.** The task doc separates a
stopped *car* (a jam, a red light — real footage of the subjects users search for) from a stopped
*world* (nobody driving yet), and object churn tells them apart where cosine cannot. That distinction
is load-bearing for **deleting** frames and is not needed here, because grouping is not deletion: a
jam that becomes one group still has every frame in the corpus, still ranked, appearing from position
11 once the window is full. Capping it at 2 is what the cap is *for*. Merging on similarity alone
therefore needs no churn threshold in the ingest path — so there is none to drift, and no
misclassification can drop real footage. Simulated over the two corpora, merging only the dead runs
would have closed 19 of 133 leaks.

**The grouping only ever coarsens, and that is the safety property.** A run merges the buckets it
spans; a bucket is never split, even when a run covers just part of it. So the number of groups can
only fall, head occupancy for any run can only fall, and a corpus whose runs sit inside their buckets
is untouched **by construction** rather than by measurement. The first draft of this did split, and
on nuScenes it cut clips into as many as 8 groups each — handing one clip 16 head slots and making
the live product worse. Verified after the change: on nuScenes the partition is *identical* to the
clock buckets it started from (170 groups, unchanged); on Hanoi it falls 569 -> 384 and no run can
take more than 2 slots.

**The frame list is untouched**, so the corpus fingerprint — `sha256(frame_ids + encoder)`, see
`src/services/search/artifacts.py` — does not move and a fitted rejection band stays fitted. This is
a relabelling, not a re-ingest.

Standalone, against a staged corpus no service has loaded:

    .venv/Scripts/python.exe scripts/regroup_scenes.py --artifacts data/staging/hanoi/artifacts

`ingest_folder.py` calls `regroup` directly, so a fresh ingest produces grouped `scene_id`s without
this script being run at all. One implementation either way: a second copy is how the shipped
grouping and the measured one drift apart.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from measure.measure_stationary_runs import SIMILAR, find_runs  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _roots(rows: list[dict], runs: list[list[int]]) -> dict[str, str]:
    """Union-find over `same clock bucket` OR `same run`, returning each bucket's root.

    Buckets are the elements, not frames: a run unions the buckets it spans, which is why a bucket
    the run only partly covers still travels whole.
    """
    parent: dict[str, str] = {}

    def find(bucket: str) -> str:
        parent.setdefault(bucket, bucket)
        while parent[bucket] != bucket:
            parent[bucket] = parent[parent[bucket]]
            bucket = parent[bucket]
        return bucket

    for row in rows:
        find(row["scene_id"])
    for run in runs:
        spanned = [rows[i]["scene_id"] for i in run]
        for other in spanned[1:]:
            first, second = find(spanned[0]), find(other)
            if first != second:
                parent[first] = second
    return {bucket: find(bucket) for bucket in parent}


def _canonical(roots: dict[str, str]) -> dict[str, str]:
    """Name each merged group after its earliest bucket, so the id is stable and still sorts by time.

    Taking the union-find representative instead would make the name depend on merge order, and a
    group that reads `clip12_hanoi#0006` when it starts at 0.0 s misleads whoever opens the clip.
    """
    members: dict[str, list[str]] = defaultdict(list)
    for bucket, root in roots.items():
        members[root].append(bucket)
    return {bucket: min(group) for group in members.values() for bucket in group}


def regroup(rows: list[dict], vectors: np.ndarray, similar: float = SIMILAR) -> int:
    """Rewrite `scene_id` in place so each near-duplicate run is one diversity group.

    `rows` needs `video_id`, `timestamp_s` and `scene_id`; `vectors` must be row-aligned. Returns how
    many groups the merge removed — 0 means the corpus was already grouped by content, which is the
    expected result on a corpus of short clips.
    """
    if len(rows) != len(vectors):
        raise ValueError(f"{len(rows)} rows against {len(vectors)} vectors — these must be row-aligned")
    unit = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    mapping = _canonical(_roots(rows, find_runs(unit, rows, similar)))
    before = len({row["scene_id"] for row in rows})
    for row in rows:
        row["scene_id"] = mapping[row["scene_id"]]
    return before - len({row["scene_id"] for row in rows})


def _read_frames(path: str) -> list[dict]:
    """`frames.jsonl` as a list, order preserved — the fingerprint depends on it."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_frames(path: str, rows: list[dict]) -> None:
    """Rewrite `frames.jsonl` with the same keys and the same row order."""
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def stamp_provenance(artifacts_dir: str, merged: int, groups: int) -> None:
    """Record how the corpus was grouped, beside the data it describes.

    Without this a corpus carries `scene_id`s with no way to tell whether they are clock buckets or
    content groups, which is exactly the ambiguity §10.3 was written about.
    """
    path = os.path.join(artifacts_dir, "provenance.json")
    with open(path, encoding="utf-8") as f:
        prov = json.load(f)
    prov["scene_grouping"] = {
        "rule": "clock buckets, unioned across near-duplicate runs (coarsen only, never split)",
        "similarity": SIMILAR,
        "groups_merged": merged,
        "n_scenes": groups,
        "task": "docs/tasks/task-stationary-runs.md",
    }
    prov["n_scenes"] = groups
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prov, f, indent=2)


def parse_args() -> argparse.Namespace:
    """CLI. Defaults point at the staged Hanoi corpus, which is what prompted the fix."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--artifacts", default=os.path.join("data", "staging", "hanoi", "artifacts"))
    parser.add_argument("--similarity", type=float, default=SIMILAR)
    parser.add_argument("--dry-run", action="store_true", help="report the merge without writing")
    return parser.parse_args()


def main() -> None:
    """Relabel an already-promoted or staged corpus without re-ingesting it."""
    args = parse_args()
    artifacts = args.artifacts if os.path.isabs(args.artifacts) else os.path.join(ROOT, args.artifacts)
    frames_path = os.path.join(artifacts, "frames.jsonl")
    rows = _read_frames(frames_path)
    vectors = np.load(os.path.join(artifacts, "vectors.npy"), allow_pickle=False).astype("float32")
    before = len({row["scene_id"] for row in rows})

    merged = regroup(rows, vectors, args.similarity)
    groups = len({row["scene_id"] for row in rows})
    print(f"{len(rows)} frames: {before} clock buckets -> {groups} content groups ({merged} merged away)")
    if args.dry_run:
        print("dry run - nothing written")
        return
    _write_frames(frames_path, rows)
    stamp_provenance(artifacts, merged, groups)
    print(f"rewrote {os.path.relpath(frames_path, ROOT)}; frame ids untouched, so the fingerprint is unchanged")


if __name__ == "__main__":
    main()
