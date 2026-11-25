"""Video loading utility using OpenCV for offline data ingestion (FR-01.1)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import cv2
import numpy as np

from src.services.ingest.models import VideoMetadata


def get_video_metadata(video_path: str, video_id: str | None = None) -> VideoMetadata:
    """Open a video file and extract fundamental streaming properties."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found at path: {video_path}")
    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            raise ValueError(f"OpenCV could not decode video at: {video_path}")
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()
    clip_id = video_id or os.path.splitext(os.path.basename(video_path))[0]
    return VideoMetadata(video_id=clip_id, fps=fps, total_frames=frames, width=width, height=height)


def stream_video_frames(
    video_path: str,
    fps: float | None = None,
    sample_fps: float | None = None,
) -> Iterator[tuple[int, float, np.ndarray]]:
    """Yield frame tuples (frame_idx, timestamp_s, bgr_array) from a video file.

    `fps` overrides the *source* rate used for timestamp arithmetic, for a container that declares
    the wrong one. It has never decimated anything, and the name invited the opposite reading: on
    60 fps footage `fps=15` would decode all 60 frames a second and label each of them four times
    too late. `sample_fps` is the parameter that actually skips frames.

    **Why decimation belongs here.** The keyframer's cost is dominated by decoding — every frame is
    decoded and histogrammed whether or not it can be selected. The first-release corpus is 190
    minutes at 60 fps, which is 684,000 frames, and consecutive frames 16 ms apart are not
    distinguishable scenes. Sampling at 15 fps cuts the decode four-fold and removes no scene the
    selector could have chosen.

    `frame_idx` and `timestamp_s` always describe the **source** video, never the sampled sequence.
    That is what makes decimation safe to change between runs: the sidecar's `frame_idx` is the only
    link back to the original footage (`run_keyframing.write_sidecar`), so it has to survive a
    change in sampling rate.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found at path: {video_path}")
    cap = cv2.VideoCapture(video_path)
    try:
        source_fps = fps or float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        stride = 1 if not sample_fps else max(1, round(source_fps / sample_fps))
        frame_idx = 0
        while True:
            try:
                ret, frame = cap.read()
            except cv2.error:
                break
            if not ret or frame is None:
                break
            if frame_idx % stride == 0:
                yield frame_idx, round(frame_idx / source_fps, 3), frame
            frame_idx += 1
    finally:
        cap.release()
