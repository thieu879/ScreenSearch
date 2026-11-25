"""Verify that the promoted corpus has complete, provenance-backed privacy coverage.

The directory is checked in **both** directions, and the second direction is the one that was
missing. Every corpus frame needs a thumbnail — that catches an incomplete redaction pass. But every
thumbnail also needs a corpus frame, because `thumbs_dir` is what the API serves, and anything else
that writes an image there publishes it without passing through `anonymise.redact`.

That is not hypothetical: `scripts/ingest/run_keyframing.py` writes 320 px thumbnails straight into
`data/thumbs` from raw video frames, and commit 878eafb committed two of them. A gate that only
looks for *missing* thumbnails calls that corpus clean.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def verify(artifacts: str, thumbs: str, privacy_cache: str | None = None) -> dict:
    frames_path = os.path.join(artifacts, "frames.jsonl")
    provenance_path = os.path.join(artifacts, "provenance.json")
    privacy_path = privacy_cache or os.path.join(artifacts, "privacy_detections.jsonl")
    frames = _jsonl(frames_path)
    frame_ids = [row["frame_id"] for row in frames]
    if len(frame_ids) != len(set(frame_ids)):
        raise ValueError("frames.jsonl contains duplicate frame_id values")

    thumb_ids = {
        os.path.splitext(name)[0] for name in os.listdir(thumbs) if name.lower().endswith((".jpg", ".jpeg", ".png"))
    }
    missing_thumbs = sorted(set(frame_ids) - thumb_ids)
    if missing_thumbs:
        raise ValueError(f"{len(missing_thumbs)} frame thumbnails are missing")

    # An image in the served directory that no corpus frame claims has been through no privacy
    # pass this gate can see. Named rather than counted: the fix is to find out what wrote them.
    unverified_thumbs = sorted(thumb_ids - set(frame_ids))
    if unverified_thumbs:
        shown = ", ".join(unverified_thumbs[:5])
        more = f" (and {len(unverified_thumbs) - 5} more)" if len(unverified_thumbs) > 5 else ""
        raise ValueError(
            f"{len(unverified_thumbs)} thumbnails in {thumbs} belong to no corpus frame and are "
            f"therefore unverified: {shown}{more}"
        )

    privacy_rows = _jsonl(privacy_path)
    privacy_frame_ids = {row.get("frame_id") for row in privacy_rows if row.get("frame_id")}
    if privacy_frame_ids:
        missing_privacy = [row for row in frames if row["frame_id"] not in privacy_frame_ids]
    else:
        privacy_images = {row["image"] for row in privacy_rows}
        missing_privacy = [row for row in frames if os.path.basename(row.get("image_path", "")) not in privacy_images]
    if missing_privacy:
        raise ValueError(f"privacy cache is missing {len(missing_privacy)} frames")

    provenance = json.load(open(provenance_path, encoding="utf-8"))
    anonymisation = provenance.get("anonymisation", {})
    if anonymisation.get("privacy_unverified", 1) != 0:
        raise ValueError("provenance does not certify zero privacy-unverified frames")
    if not provenance.get("privacy"):
        raise ValueError("provenance does not record the privacy detector configuration")

    # Presence is not agreement. Without this, a corpus redacted with one set of weights passes the
    # gate beside a cache regenerated with another — the thumbnails and the certificate describing
    # them would come from different models, and nothing else in the pipeline would notice.
    cache_configs = {json.dumps(row.get("privacy"), sort_keys=True) for row in privacy_rows}
    if len(cache_configs) > 1:
        raise ValueError(f"privacy cache mixes {len(cache_configs)} detector configurations")
    if cache_configs and json.dumps(provenance["privacy"], sort_keys=True) not in cache_configs:
        raise ValueError(
            "provenance records a different privacy configuration than the cache that produced these thumbnails"
        )

    return {
        "frames": len(frame_ids),
        "thumbnails": len(thumb_ids),
        "privacy_rows": len(privacy_rows),
        "privacy": provenance["privacy"],
    }


def main() -> None:  # pragma: no cover - CLI wrapper
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--thumbs", required=True)
    parser.add_argument("--privacy-cache")
    args = parser.parse_args()
    try:
        result = verify(args.artifacts, args.thumbs, args.privacy_cache)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        sys.exit(f"privacy asset verification FAILED: {exc}")
    print(json.dumps({"ok": True, **result}, indent=2))


if __name__ == "__main__":
    main()
