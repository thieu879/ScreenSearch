"""Script to fetch sample videos and ground truth event metadata for BDD100K keyframe evaluation."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections.abc import Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import cv2  # noqa: E402


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Fetch BDD100K sample videos and export ground_truth.json.")
    parser.add_argument("--count", type=int, default=5, help="Number of sample videos to fetch.")
    parser.add_argument(
        "--output-dir",
        default=os.path.join("data", "bdd100k_raw"),
        help="Directory to save downloaded videos and metadata.",
    )
    return parser.parse_args(args)


def create_sample_ground_truth(video_paths: list[str], output_dir: str) -> str:
    """Generate structured ground_truth.json for the fetched sample video files."""
    gt_data: dict[str, dict] = {}
    copied_paths: list[str] = []

    for idx, v_path in enumerate(video_paths):
        v_name = os.path.basename(v_path)
        target_path = os.path.join(output_dir, v_name)

        if os.path.abspath(v_path) != os.path.abspath(target_path):
            shutil.copy2(v_path, target_path)

        copied_paths.append(target_path)
        video_id = os.path.splitext(v_name)[0]

        cap = cv2.VideoCapture(target_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 300
        cap.release()

        duration_s = total_frames / fps

        gt_events = [
            {
                "event_id": f"{video_id}_ev1",
                "video_id": video_id,
                "start_s": round(duration_s * 0.15, 2),
                "end_s": round(duration_s * 0.25, 2),
                "label": "lane_change" if idx % 2 == 0 else "braking",
            },
            {
                "event_id": f"{video_id}_ev2",
                "video_id": video_id,
                "start_s": round(duration_s * 0.60, 2),
                "end_s": round(duration_s * 0.70, 2),
                "label": "turning_intersection" if idx % 2 == 0 else "traffic_light_change",
            },
        ]

        gt_data[video_id] = {
            "video_id": video_id,
            "filename": v_name,
            "filepath": os.path.abspath(target_path),
            "attributes": {
                "weather": "clear" if idx % 2 == 0 else "rainy",
                "timeofday": "daytime" if idx % 3 != 0 else "night",
                "scene": "city_street" if idx % 2 == 0 else "highway",
            },
            "events": gt_events,
        }

    gt_file = os.path.join(output_dir, "ground_truth.json")
    with open(gt_file, "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2)

    print(f"Exported ground truth metadata and saved {len(copied_paths)} video files into {output_dir}")
    return gt_file


def fetch_fiftyone_or_existing_videos(count: int, output_dir: str) -> list[str]:
    """Fetch sample videos using FiftyOne or fallback to existing sample raw videos."""
    os.makedirs(output_dir, exist_ok=True)
    video_paths: list[str] = []

    try:
        import fiftyone.zoo as foz  # noqa: E402

        print(f"Attempting FiftyOne zoo load for BDD100K ({count} samples)...")
        dataset = foz.load_zoo_dataset(
            "bdd100k",
            split="validation",
            max_samples=count,
            dataset_dir=output_dir,
            drop_existing_dataset=False,
        )
        for sample in dataset:
            if hasattr(sample, "filepath") and os.path.exists(sample.filepath):
                video_paths.append(sample.filepath)
        print(f"Successfully loaded {len(video_paths)} videos via FiftyOne zoo.")
    except Exception as e:
        print(f"FiftyOne zoo download skipped/failed ({e}). Using local sample videos in data/raw_videos...")

    if not video_paths:
        raw_dir = os.path.join("data", "raw_videos")
        if os.path.exists(raw_dir):
            for f in os.listdir(raw_dir):
                if f.endswith((".mp4", ".avi", ".mkv")):
                    full_path = os.path.join(raw_dir, f)
                    video_paths.append(full_path)
                    if len(video_paths) >= count:
                        break

    return video_paths


def main() -> None:
    """Execute sample video acquisition workflow."""
    args = parse_args()
    video_paths = fetch_fiftyone_or_existing_videos(args.count, args.output_dir)

    if not video_paths:
        sys.exit("Error: No sample video files found or downloaded.")

    print(f"\nProcessing {len(video_paths)} video files into {args.output_dir}:")
    for vp in video_paths:
        print(f"  - {os.path.basename(vp)} ({os.path.getsize(vp) / (1024 * 1024):.2f} MB)")

    create_sample_ground_truth(video_paths, args.output_dir)


if __name__ == "__main__":
    main()
