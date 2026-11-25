"""CLI runner for keyframe extraction evaluation benchmark suite."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.services.ingest.evaluator import (  # noqa: E402
    TemporalEvent,
    VideoEvalResult,
    compute_video_evaluation,
)
from src.services.ingest.keyframing import extract_adaptive_keyframes  # noqa: E402
from src.services.ingest.models import IngestConfig  # noqa: E402
from src.services.ingest.video_loader import get_video_metadata, stream_video_frames  # noqa: E402


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run keyframe extraction evaluation benchmark suite.")
    parser.add_argument(
        "--dataset-dir",
        default=os.path.join("data", "bdd100k_raw"),
        help="Directory containing test videos and ground_truth.json.",
    )
    parser.add_argument("--threshold", type=float, default=0.40, help="HSV histogram diff threshold.")
    parser.add_argument("--heartbeat", type=float, default=5.0, help="Max heartbeat interval in seconds.")
    parser.add_argument("--tolerance", type=float, default=0.5, help="Temporal event matching tolerance in seconds.")
    return parser.parse_args(args)


def print_evaluation_scorecard(eval_results: list[tuple[VideoEvalResult, dict]]) -> None:
    """Print structured benchmark scorecard summarizing Precision, Recall, F1, and Reduction rate."""
    print("\n==========================================================================")
    print("        KEYFRAME EXTRACTION EVALUATION BENCHMARK SCORECARD                ")
    print("==========================================================================")
    header = f"{'Video ID / Name':<25} | {'Scene':<10} | {'Total':<6} | {'KF':<4} | {'Reduction':<9} | {'Precision':<9} | {'Recall':<8} | {'F1-Score':<8}"
    print(header)
    print("-" * len(header))

    total_frames = 0
    total_kf = 0
    f1_list: list[float] = []
    p_list: list[float] = []
    r_list: list[float] = []
    reduction_list: list[float] = []

    for res, attrs in eval_results:
        scene = attrs.get("scene", "general")
        print(
            f"{res.video_id[:25]:<25} | {scene[:10]:<10} | {res.total_frames:<6} | {res.extracted_count:<4} | "
            f"{res.reduction_rate:8.2f}% | {res.precision:9.2f} | {res.recall:8.2f} | {res.f1_score:8.2f}"
        )
        total_frames += res.total_frames
        total_kf += res.extracted_count
        f1_list.append(res.f1_score)
        p_list.append(res.precision)
        r_list.append(res.recall)
        reduction_list.append(res.reduction_rate)

    avg_f1 = sum(f1_list) / max(1, len(f1_list))
    avg_p = sum(p_list) / max(1, len(p_list))
    avg_r = sum(r_list) / max(1, len(r_list))
    avg_red = sum(reduction_list) / max(1, len(reduction_list))

    print("-" * len(header))
    print(
        f"{'AVERAGE / OVERALL':<25} | {'all':<10} | {total_frames:<6} | {total_kf:<4} | "
        f"{avg_red:8.2f}% | {avg_p:9.2f} | {avg_r:8.2f} | {avg_f1:8.2f}"
    )
    print("==========================================================================\n")


def main() -> None:
    """Execute evaluation benchmark suite."""
    args = parse_args()
    gt_file = os.path.join(args.dataset_dir, "ground_truth.json")

    if not os.path.exists(gt_file):
        sys.exit(f"Error: ground_truth.json not found in {args.dataset_dir}. Run fetch_bdd100k_samples.py first.")

    with open(gt_file, encoding="utf-8") as f:
        gt_data = json.load(f)

    config = IngestConfig(hist_diff_threshold=args.threshold, max_heartbeat_s=args.heartbeat)
    eval_results: list[tuple[VideoEvalResult, dict]] = []

    print(f"Executing Keyframe Evaluation Suite on {len(gt_data)} test videos...")

    for v_id, info in gt_data.items():
        v_path = info.get("filepath")
        if not v_path or not os.path.exists(v_path):
            v_path = os.path.join(args.dataset_dir, info.get("filename", ""))

        if not os.path.exists(v_path):
            print(f"Warning: Video file missing for {v_id}, skipping...")
            continue

        meta = get_video_metadata(v_path)
        stream = stream_video_frames(v_path)
        keyframes = extract_adaptive_keyframes(stream, config, video_id=meta.video_id)

        raw_events = info.get("events", [])
        gt_events = [TemporalEvent(**ev) for ev in raw_events]

        eval_res = compute_video_evaluation(meta, keyframes, gt_events)
        eval_results.append((eval_res, info.get("attributes", {})))

    if eval_results:
        print_evaluation_scorecard(eval_results)
    else:
        print("No evaluation results were computed.")


if __name__ == "__main__":
    main()
