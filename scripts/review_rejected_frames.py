"""Write the quality gate's rejects back out as JPEGs, so a human can see what was deleted.

`QualityGate.apply` runs *before* `write_frames`, so a rejected frame is discarded in memory and
only its scores survive, in `rejected.json`. That is enough to tune a constant and not nearly enough
to know whether the test works: the first two versions of the gate both passed a re-scoring check
and both were deleting good frames. `DETAIL_RATIO`'s docstring records what review found — two lit
tunnel interiors, a lake pagoda and a night street, none of them occluded by anything.

So this reads `rejected.json` and seeks the source video by `frame_idx` to recover the pixels.

**The output is unredacted source footage.** Faces and plates are readable. It writes outside
`data/thumbs` deliberately: anything appearing there outside `anonymise.redact` gets published.
Delete the folder when the review is done.

    python scripts/review_rejected_frames.py \
        --frames data/extracted_keyframes/clip*_hanoi \
        --videos ../data/first_release --out data/review/rejected
"""

from __future__ import annotations

import argparse
import json
import os

import cv2


def recover(rejected_json: str, videos_dir: str, out_dir: str) -> int:
    """Re-read one clip's rejected frames from its source video. Returns the number written."""
    record = json.load(open(rejected_json, encoding="utf-8"))
    rows = record.get("frames", [])
    if not rows:
        return 0

    video = os.path.join(videos_dir, record["source"])
    capture = cv2.VideoCapture(video)
    if not capture.isOpened():
        print(f"  !! cannot open {video} — skipping {record['video_id']}")
        return 0

    written = 0
    try:
        for row in rows:
            capture.set(cv2.CAP_PROP_POS_FRAMES, row["frame_idx"])
            ok, frame = capture.read()
            if not ok or frame is None:
                print(f"  !! seek failed: {record['video_id']} @{row['frame_idx']}")
                continue
            # The filename carries the whole verdict: which arm fired, the score, and the cut it
            # was measured against. Reviewing a folder of hashes teaches nothing.
            name = (
                f"{record['video_id']}_t{row['timestamp_s']:07.1f}s"
                f"_{row['rejected_for']}"
                f"_detail{row['detail']:.0f}of{row['min_detail']:.0f}"
                f"_occ{row['occlusion']:.2f}of{row['max_occlusion']:.2f}"
                f"_{row['selected_as']}.jpg"
            )
            cv2.imwrite(os.path.join(out_dir, name), frame)
            written += 1
    finally:
        capture.release()
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--frames", nargs="+", required=True, help="extracted keyframe directories, each holding a rejected.json"
    )
    ap.add_argument("--videos", required=True, help="directory holding the source videos")
    ap.add_argument("--out", default="data/review/rejected", help="destination for the JPEGs")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    total = 0
    for directory in args.frames:
        path = os.path.join(directory, "rejected.json")
        if not os.path.exists(path):
            print(f"  -- no rejected.json in {directory}")
            continue
        total += recover(path, args.videos, args.out)

    print(f"[review] {total} rejected frames -> {args.out}")
    print(
        "These are UNREDACTED source pixels. Do not publish them, and do not copy them into "
        "data/thumbs. Delete the folder when the review is done."
    )


if __name__ == "__main__":
    main()
