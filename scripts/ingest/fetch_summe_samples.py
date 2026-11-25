"""Script to download SumMe dataset, extract selected sample videos + GT, and export parsed annotations."""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from collections.abc import Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import requests  # noqa: E402
import scipy.io  # noqa: E402


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Download SumMe samples and parse MAT to JSON.")
    parser.add_argument(
        "--output-dir",
        default=os.path.join("data", "summe_raw"),
        help="Directory to save downloaded videos and metadata.",
    )
    return parser.parse_args(args)


def download_file_with_progress(url: str, dest_path: str) -> None:
    """Download a file using requests stream to avoid MemoryError."""
    print(f"Downloading {url} to {dest_path}...")
    headers = {"User-Agent": "Mozilla/5.0"}

    response = requests.get(url, headers=headers, stream=True)
    response.raise_for_status()

    total_size = int(response.headers.get("content-length", 0))
    downloaded = 0
    block_size = 128 * 1024  # 128 KB chunks to keep memory usage minimal

    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=block_size):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    percent = (downloaded / total_size) * 100
                    print(
                        f"Progress: {percent:.2f}% ({downloaded / (1024 * 1024):.1f}/{total_size / (1024 * 1024):.1f} MB)",
                        end="\r",
                    )
    print(f"\nDownload completed successfully: {dest_path}")


def extract_specific_files(zip_path: str, output_dir: str, target_videos: list[str]) -> list[str]:
    """Extract only the specified videos and their MAT annotations from SumMe.zip."""
    extracted_paths: list[str] = []
    print(f"Extracting target videos: {target_videos} from {zip_path}...")

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            for tv in target_videos:
                # Target video
                if member.endswith(f"videos/{tv}.mp4"):
                    dest_file = os.path.join(output_dir, f"{tv}.mp4")
                    with zf.open(member) as source, open(dest_file, "wb") as target:
                        shutil_copyobj(source, target)
                    extracted_paths.append(dest_file)
                # Target ground truth mat
                elif member.endswith(f"GT/{tv}.mat"):
                    dest_file = os.path.join(output_dir, f"{tv}.mat")
                    with zf.open(member) as source, open(dest_file, "wb") as target:
                        shutil_copyobj(source, target)

    print(f"Extracted {len(extracted_paths)} videos and corresponding MAT files into {output_dir}")
    return extracted_paths


def shutil_copyobj(source, target):
    """Helper to copy file stream in chunks."""
    buffer_size = 1024 * 1024
    while True:
        buf = source.read(buffer_size)
        if not buf:
            break
        target.write(buf)


def parse_summe_mat_annotations(video_id: str, mat_path: str) -> list[dict]:
    """Parse MATLAB .mat file to extract frame scores and group them into temporal events."""
    mat_data = scipy.io.loadmat(mat_path)

    # SumMe .mat contains: 'gtScore', 'video_duration', 'FPS'
    gt_score = mat_data["gtScore"].flatten()
    fps = float(mat_data["FPS"][0][0])
    total_frames = len(gt_score)

    events: list[dict] = []
    in_event = False
    start_frame = 0

    # Group continuous frames where gt_score >= 0.3 into events
    for idx, score in enumerate(gt_score):
        if score >= 0.3:
            if not in_event:
                in_event = True
                start_frame = idx
        else:
            if in_event:
                in_event = False
                end_frame = idx - 1
                events.append(
                    {
                        "event_id": f"{video_id}_ev{len(events) + 1}",
                        "video_id": video_id,
                        "start_s": round(start_frame / fps, 2),
                        "end_s": round(end_frame / fps, 2),
                        "label": "high_importance",
                    }
                )

    # Handle event that goes till the last frame
    if in_event:
        events.append(
            {
                "event_id": f"{video_id}_ev{len(events) + 1}",
                "video_id": video_id,
                "start_s": round(start_frame / fps, 2),
                "end_s": round((total_frames - 1) / fps, 2),
                "label": "high_importance",
            }
        )

    return events


def create_summe_ground_truth(output_dir: str, target_videos: list[str]) -> str:
    """Generate consolidated ground_truth.json containing parsed SumMe metadata and events."""
    gt_data: dict[str, dict] = {}

    for tv in target_videos:
        video_path = os.path.join(output_dir, f"{tv}.mp4")
        mat_path = os.path.join(output_dir, f"{tv}.mat")

        if not os.path.exists(video_path) or not os.path.exists(mat_path):
            continue

        cap = cv2_capture(video_path)
        cap.release()

        events = parse_summe_mat_annotations(tv, mat_path)

        gt_data[tv] = {
            "video_id": tv,
            "filename": f"{tv}.mp4",
            "filepath": os.path.abspath(video_path),
            "attributes": {
                "weather": "general",
                "timeofday": "daytime",
                "scene": "dynamic_action",
            },
            "events": events,
        }

    gt_file = os.path.join(output_dir, "ground_truth.json")
    with open(gt_file, "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2)

    print(f"Exported SumMe ground truth metadata to {gt_file}")
    return gt_file


def cv2_capture(video_path: str):
    """Wrapper to lazy import cv2 and load video capture."""
    import cv2

    return cv2.VideoCapture(video_path)


def main() -> None:
    """Execute SumMe dataset download and extraction pipeline."""
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    zip_path = os.path.join(args.output_dir, "SumMe.zip")
    url = "https://data.vision.ee.ethz.ch/cvl/SumMe/SumMe.zip"

    # Only download if we don't have the target files already
    target_videos = ["cooking", "palang", "base_jumping"]
    files_exist = all(
        os.path.exists(os.path.join(args.output_dir, f"{tv}.mp4"))
        and os.path.exists(os.path.join(args.output_dir, f"{tv}.mat"))
        for tv in target_videos
    )

    if not files_exist:
        if not os.path.exists(zip_path):
            download_file_with_progress(url, zip_path)
        extract_specific_files(zip_path, args.output_dir, target_videos)
        if os.path.exists(zip_path):
            os.remove(zip_path)
            print("Removed temporary SumMe.zip file to free space.")
    else:
        print("All target SumMe sample video and annotation files already exist. Skipping download.")

    create_summe_ground_truth(args.output_dir, target_videos)


if __name__ == "__main__":
    main()
