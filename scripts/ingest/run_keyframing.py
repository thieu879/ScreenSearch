"""CLI entry point for running the adaptive keyframe extraction pipeline (FR-01.2)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

# Calculate repository root directory dynamically (2 levels up from scripts/ingest/)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
# `scripts/` holds the helpers shared with the ingest side, which cannot live under `src/`: they are
# imported by `ingest_folder.py`, which runs in an environment with no pydantic. See scripts/_fov.py.
if os.path.join(REPO_ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import cv2  # noqa: E402
from _console import use_utf8  # noqa: E402, F401 -- console encoding; imported for effect
from _fov import check_fov  # noqa: E402

from src.services.ingest.keyframing import extract_adaptive_keyframes  # noqa: E402
from src.services.ingest.models import ExtractedKeyframe, IngestConfig, VideoMetadata  # noqa: E402
from src.services.ingest.quality import QualityGate  # noqa: E402
from src.services.ingest.reselect import BladeAvoider  # noqa: E402
from src.services.ingest.video_loader import get_video_metadata, stream_video_frames  # noqa: E402

# The Module 1 -> Module 2 handoff filename. `ingest_folder.SIDECAR` is the same string on the
# reading side; the two are asserted equal in tests/test_services/test_keyframe_sidecar.py, because
# each module naming it independently is the only way this pairing breaks.
SIDECAR = "frames.json"


def _out_dir(video_id: str, strategy: str) -> str:
    """Where one run's frames and sidecar go. Benchmark strategies never overwrite production."""
    folder_name = video_id if strategy == "lmske" else f"{video_id}_{strategy}"
    return os.path.join("data", "extracted_keyframes", folder_name)


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for the keyframe extraction CLI."""
    parser = argparse.ArgumentParser(description="Run adaptive keyframe extraction on a raw video file.")
    parser.add_argument(
        "--video",
        default=os.path.join("data", "raw_videos", "busy_urban_traffic.mp4"),
        help="Path to the target input video file.",
    )
    parser.add_argument("--threshold", type=float, default=0.40, help="HSV histogram difference threshold.")
    parser.add_argument("--heartbeat", type=float, default=5.0, help="Maximum heartbeat interval in seconds.")
    parser.add_argument(
        "--strategy",
        choices=["lmske", "hsv_heartbeat"],
        default="lmske",
        help="Keyframing engine strategy ('lmske' or 'hsv_heartbeat').",
    )
    parser.add_argument(
        "--fov",
        type=float,
        required=True,
        help="Camera horizontal FOV in degrees. Required: it decides every spatial relation "
        "downstream and cannot be recovered from the frames (M2_DESIGN 10.5). Values at or "
        "below 60 are refused. Most dashcams are 100-140.",
    )
    parser.add_argument(
        "--sample-fps",
        type=float,
        default=None,
        help="Decode only this many frames per second of source. Cost is dominated by decoding "
        "every frame, and on 60 fps footage consecutive frames are 16 ms apart -- not "
        "distinguishable scenes. Timestamps and frame indices still refer to the source.",
    )
    parser.add_argument(
        "--bottom-crop",
        type=float,
        default=0.0,
        help="Fraction of frame height to ignore at the bottom when COMPARING frames, for footage "
        "where the car's own bonnet fills the lower frame (0.25 on the first-release corpus). "
        "Saved frames are never cropped.",
    )
    parser.add_argument(
        "--quality-gate",
        action="store_true",
        help="Drop selected frames the camera could not see through -- heavy spray, wiper blade. "
        "Rejects are written to rejected.json beside the sidecar, never discarded silently.",
    )
    parser.add_argument(
        "--avoid-wiper",
        action="store_true",
        help="Move a selection the wiper crossed onto clear footage within 0.6 s, instead of "
        "dropping it. The quality gate cannot do this -- its occlusion floor is unreachable "
        "for a blade -- and rejecting is the wrong answer anyway, because the same test fires "
        "on footbridges and tunnels. Swaps are written to swaps.json beside the sidecar.",
    )
    return parser.parse_args(args)


def save_keyframe_images(keyframes: list[ExtractedKeyframe], video_id: str, strategy: str = "lmske") -> tuple[str, int]:
    """Save extracted keyframes at full resolution. Writes no thumbnails, deliberately.

    Folder output is separated by strategy: default LMSKE uses `video_id` directly while benchmark
    strategies append a `_{strategy}` suffix, so a comparison run cannot overwrite production frames.

    **Nothing here may write into `data/thumbs`.** This function used to also write a 320 px copy
    straight there — `settings.thumbs_dir`, *the directory the API serves to the browser*. That write
    bypassed `anonymise.redact()` entirely, so those images carried no face or licence-plate
    redaction and no anonymisation provenance; running the script published unredacted faces and
    plates. It already happened once, in commit 878eafb.

    Thumbnails come from exactly one place — `promote_artifacts.write_thumbnails` /
    `scripts/anonymise.py` — both of which mosaic faces, plates and person head bands at source
    resolution *before* downscaling. Extraction writes full-resolution frames here; the Module 2
    ingest generates the redacted thumbnails when it ingests this folder.

    See `docs/handover/keyframe-handoff-contract.md` §3 and `scripts/ingest/README.md` §7 invariant 4.
    """
    out_dir = _out_dir(video_id, strategy)
    os.makedirs(out_dir, exist_ok=True)

    written = set()
    for kf in keyframes:
        name = f"{kf.frame_id}.jpg"
        cv2.imwrite(os.path.join(out_dir, name), kf.image_array)
        written.add(name)

    # Remove images from an earlier run that this one did not produce. Re-extraction used to be
    # idempotent by accident -- the same selection yielded the same filenames, so a re-run simply
    # overwrote them. `--avoid-wiper` breaks that: it *moves* frame indices, and the filename is
    # built from the index, so every swapped frame lands under a new name and leaves the old one
    # behind. Measured on the first clip re-run: 76 JPEGs on disk for 60 keyframes.
    #
    # Orphans are not inert. This folder is the Module 1 -> Module 2 handoff, and `ingest_folder`
    # falls back to lexical order at a fixed rate when it cannot read the sidecar -- at which point
    # the orphans ingest too, carrying invented timestamps and the very blades this run removed.
    for stale in os.listdir(out_dir):
        if stale.endswith(".jpg") and stale not in written:
            os.remove(os.path.join(out_dir, stale))

    return out_dir, len(keyframes)


def write_sidecar(keyframes: list[ExtractedKeyframe], meta: VideoMetadata, args: argparse.Namespace) -> str:
    """Write `frames.json` — the Module 1 → Module 2 contract that `ingest_folder.py` reads.

    **Adaptive extraction makes this mandatory rather than merely useful.** Without the sidecar,
    `ingest_folder` falls back to lexical order at a fixed `--fps` and assigns evenly spaced
    timestamps. That was a tolerable approximation for the old 2 Hz extractor, whose frames really
    were evenly spaced. LMSKE selects on shot boundaries and redundancy, so its output is
    deliberately *un*evenly spaced — every timestamp the fallback invents would be wrong, and wrong
    silently: the corpus ingests, searches, and returns frames whose reported position in the source
    video does not exist. `docs/handover/keyframe-handoff-contract.md` §1 is the same argument at length.

    `hfov_deg` rides along for the same reason it is declared at all — it is not recoverable from
    the pixels, and it decides every left/right relation downstream (§10.5).

    `frame_idx` and `reason` ride along for the same reason again: the selector computes both and
    nothing downstream can recompute either. `frame_idx` is the only link back to the source frame,
    so without it a selection decision cannot be reconstructed and no policy can be traced to the
    footage it came from. `reason` records whether the frame was chosen as an `event` or emitted by
    the 5 s `heartbeat` — the near-duplicate experiment in `docs/reference/keyframe-storage-design.md` §4 (E1)
    turns on exactly that distinction and cannot be evaluated without it. Both are written **before**
    the first real corpus is extracted deliberately: §5.3 makes re-selection a *new* corpus, so
    backfilling them later would mean re-running the privacy certification too.
    """
    entries = [
        {
            "file": f"{kf.frame_id}.jpg",
            "timestamp_s": kf.timestamp_s,
            "frame_idx": kf.frame_idx,
            "reason": kf.reason,
        }
        for kf in keyframes
    ]
    payload = {
        "video_id": meta.video_id,
        "fps": meta.fps,
        "hfov_deg": args.fov,
        "source": os.path.basename(args.video),
        "extractor": args.strategy,
        # How the selection was made, beside what it selected. §5.3 makes re-selection a *new*
        # corpus, so a run whose sampling rate or comparison crop is unrecorded cannot be told
        # apart from one that differs only in those — and the frame lists would not match.
        "sample_fps": args.sample_fps,
        "compare_bottom_crop": args.bottom_crop,
        "quality_gate": bool(args.quality_gate),
        # Same reason as the three above: this one *moves* frame_idx and timestamp_s, so a run with
        # it on and a run with it off produce different frames under the same name. A sidecar that
        # did not record it would make those two corpora indistinguishable.
        "avoid_wiper": bool(args.avoid_wiper),
        # Where the car's own bodywork starts, for `ingest_folder`'s ego-box filter. Derived from
        # `--bottom-crop` rather than declared twice: they are the same line on the same camera, and
        # two fields that must agree are two fields that will eventually disagree.
        "bonnet_top": round(1.0 - args.bottom_crop, 4) if args.bottom_crop > 0 else 1.0,
        "frames": entries,
    }
    out_dir = _out_dir(meta.video_id, args.strategy)
    os.makedirs(out_dir, exist_ok=True)  # not dependent on save_keyframe_images having run first
    path = os.path.join(out_dir, SIDECAR)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def write_rejects(rejected: list[dict], meta: VideoMetadata, args: argparse.Namespace) -> str:
    """Write `rejected.json` — what the quality gate threw away, and on what numbers.

    Not a log. The gate's cut points are derived from each clip's own distribution and were fitted
    on one city's footage, so the first question anyone asks on the next corpus is whether it is
    discarding the right frames. A gate that deletes silently cannot answer that, and a corpus whose
    absences are unexplained is one nobody can defend at review.
    """
    payload = {
        "video_id": meta.video_id,
        "source": os.path.basename(args.video),
        "rejected": len(rejected),
        "frames": rejected,
    }
    out_dir = _out_dir(meta.video_id, args.strategy)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "rejected.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def write_swaps(swaps: list[dict], meta: VideoMetadata, args: argparse.Namespace) -> str:
    """Write `swaps.json` — which selections the wiper moved, how far, and on what numbers.

    The same argument as `write_rejects`, one step stronger. A rejected frame is visibly absent; a
    *moved* frame is present under a new name and looks like an ordinary selection, so without this
    record there is nothing to show that the selector's own choice was overridden. The constants
    were fitted on one city's rain, and the test is known to fire on footbridges and tunnel mouths
    as well as blades — `shift_s` is what makes those visible, because a swap that moved a frame the
    full 0.6 s is the one worth opening.
    """
    payload = {
        "video_id": meta.video_id,
        "source": os.path.basename(args.video),
        "swapped": len(swaps),
        "frames": swaps,
    }
    out_dir = _out_dir(meta.video_id, args.strategy)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "swaps.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def report_results(meta: VideoMetadata, keyframes: list[ExtractedKeyframe], out_dir: str) -> None:
    """Print structured execution summary and data reduction performance metrics."""
    reduction = (1.0 - len(keyframes) / meta.total_frames) * 100.0
    print("\n=======================================================")
    print("        KEYFRAME EXTRACTION WORKFLOW COMPLETE          ")
    print("=======================================================")
    print(f"Input Video  : {meta.video_id} ({meta.width}x{meta.height} @ {meta.fps:.2f}fps)")
    print(f"Total Frames : {meta.total_frames}")
    print(f"Keyframes    : {len(keyframes)}")
    print(f"Reduction    : {reduction:.2f}% data saved")
    print(f"Output Path  : {os.path.abspath(out_dir)}")
    print("-------------------------------------------------------")
    for kf in keyframes:
        print(f"  Frame {kf.frame_idx:04d} | t={kf.timestamp_s:6.2f}s | reason={kf.reason:9s}")
    print("=======================================================\n")


def main() -> None:
    """Execute the end-to-end keyframe extraction workflow from CLI arguments."""
    args = parse_args()

    # Before the file check, not after: this is argument validation and needs no disk. Refused here
    # as well as at ingest so a bad value costs one decode rather than a whole pipeline.
    check_fov(args.fov)

    if not os.path.exists(args.video):
        sys.exit(f"Error: Video file not found at path: {args.video}")

    meta = get_video_metadata(args.video)
    config = IngestConfig(
        hist_diff_threshold=args.threshold,
        max_heartbeat_s=args.heartbeat,
        keyframing_strategy=args.strategy,
        compare_bottom_crop=args.bottom_crop,
    )

    print(f"[1/3] Reading video stream: {args.video}")
    stream = stream_video_frames(args.video, sample_fps=args.sample_fps)

    print("[2/3] Executing adaptive keyframing algorithm...")
    keyframes = extract_adaptive_keyframes(stream, config, video_id=meta.video_id)

    swaps: list[dict] = []
    if args.avoid_wiper:
        # Before the gate, not after: the gate scores the pixels a frame ends up with, and its cut
        # points are that clip's own medians -- both of which move once selections are re-pointed.
        avoider = BladeAvoider(bottom_crop=args.bottom_crop, video_path=args.video)
        keyframes, swaps = avoider.refine(keyframes, meta.fps)
        print(f"[wiper] {len(swaps)} of {len(keyframes)} selections moved onto clearer footage")

    rejected: list[dict] = []
    if args.quality_gate:
        # The video, not just the frames: deciding whether an occlusion is a passing blade or the
        # inside of an underpass needs the footage either side, which the selected keyframes --
        # seconds apart -- cannot supply.
        gate = QualityGate(bottom_crop=args.bottom_crop, video_path=args.video)
        keyframes, rejected = gate.apply(keyframes, meta.fps)
        print(f"[gate]  {len(rejected)} of {len(keyframes) + len(rejected)} selected frames rejected")

    print(f"[3/3] Saving {len(keyframes)} keyframes to disk...")
    out_dir, count = save_keyframe_images(keyframes, meta.video_id, strategy=args.strategy)
    sidecar = write_sidecar(keyframes, meta, args)
    if args.quality_gate:
        write_rejects(rejected, meta, args)
    if args.avoid_wiper:
        write_swaps(swaps, meta, args)

    report_results(meta, keyframes, out_dir)
    print(f"[sidecar] {sidecar} — {count} frames, hfov {args.fov} deg, timestamps from the decoder")
    print(f"NEXT: python scripts/ingest_folder.py --frames {out_dir} --workdir <workdir> --out <out>")


if __name__ == "__main__":
    main()
