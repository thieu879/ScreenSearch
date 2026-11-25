"""Dual-engine adaptive keyframe extraction algorithm (LMSKE SOTA AI + HSV/Heartbeat Fallback)."""

from __future__ import annotations

import logging
from collections.abc import Iterable

import cv2
import numpy as np

from src.services.ingest.models import ExtractedKeyframe, IngestConfig

logger = logging.getLogger(__name__)


def scene_region(frame: np.ndarray, bottom_crop: float = 0.0) -> np.ndarray:
    """The part of the frame that shows the road rather than the car showing it.

    A view from inside a vehicle contains a band of the vehicle itself — bonnet, windscreen cowl,
    bonnet ornament — that is identical in every frame of the clip. Measured on the first-release
    corpus it is the bottom 25%: per-row temporal variation steps down sharply at y = 0.75 and stays
    down (`scripts/measure/probe_hanoi_frames.py`, `static_band`).

    Including it in a comparison is not neutral. It contributes the same mass to both histograms, so
    every distance between two frames is pulled toward zero and real scene changes stop clearing
    `hist_diff_threshold`; in stage 3 the same constant pushes cosine similarity *up*, so more
    candidates are judged redundant. Both errors discard frames.

    A crop, not a mask, and applied to comparison only — `save_keyframe_images` writes the full
    frame, because the detector and the thumbnail need what the camera saw.
    """
    if bottom_crop <= 0.0:
        return frame
    keep = max(1, int(round(frame.shape[0] * (1.0 - bottom_crop))))
    return frame[:keep]


def _hsv_histogram(frame: np.ndarray, target_width: int | None = 64, bottom_crop: float = 0.0) -> np.ndarray:
    """Normalised 8x8x8 HSV histogram of a frame's scene region.

    `target_width=None` skips the downsample, for stage 3, which has always histogrammed at source
    resolution. Normalising is safe for both callers: Bhattacharyya needs it, and cosine similarity
    is invariant to it.
    """
    img = scene_region(frame, bottom_crop)
    if target_width is not None:
        img = cv2.resize(img, (target_width, target_width), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 8, 8], [0, 180, 0, 256, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def compute_hsv_histogram_diff(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    target_width: int = 64,
    bottom_crop: float = 0.0,
) -> float:
    """Calculate Bhattacharyya distance between HSV color histograms of two frames."""
    hist_a = _hsv_histogram(frame_a, target_width, bottom_crop)
    hist_b = _hsv_histogram(frame_b, target_width, bottom_crop)
    return float(cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_BHATTACHARYYA))


def compute_cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Calculate cosine similarity between two feature vectors."""
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


def _extract_hsv_heartbeat(
    frames_stream: Iterable[tuple[int, float, np.ndarray]],
    config: IngestConfig,
    video_id: str = "video",
) -> list[ExtractedKeyframe]:
    """Fast HSV histogram difference & heartbeat fallback extraction engine."""
    keyframes: list[ExtractedKeyframe] = []
    last_bgr: np.ndarray | None = None
    last_timestamp: float = -1.0

    for idx, timestamp_s, frame in frames_stream:
        if last_bgr is None:
            fid = f"{video_id}_f{idx:05d}"
            kf = ExtractedKeyframe(
                frame_id=fid,
                video_id=video_id,
                timestamp_s=timestamp_s,
                frame_idx=idx,
                reason="event",
                image_array=frame,
            )
            keyframes.append(kf)
            last_bgr, last_timestamp = frame, timestamp_s
            continue

        time_delta = timestamp_s - last_timestamp
        diff = compute_hsv_histogram_diff(frame, last_bgr, config.target_width, config.compare_bottom_crop)

        reason = None
        if time_delta >= config.max_heartbeat_s:
            reason = "heartbeat"
        elif diff >= config.hist_diff_threshold:
            reason = "event"

        if reason:
            fid = f"{video_id}_f{idx:05d}"
            kf = ExtractedKeyframe(
                frame_id=fid,
                video_id=video_id,
                timestamp_s=timestamp_s,
                frame_idx=idx,
                reason=reason,
                image_array=frame,
            )
            keyframes.append(kf)
            last_bgr, last_timestamp = frame, timestamp_s

    return keyframes


def _eliminate_lmske_redundancy(
    candidates: list[ExtractedKeyframe],
    threshold: float = 0.80,
    bottom_crop: float = 0.0,
) -> list[ExtractedKeyframe]:
    """LMSKE Stage 3: Eliminate redundant candidate keyframes using Cosine similarity.

    Each accepted frame's histogram is computed **once, on accept**, and kept beside it. It used to
    be recomputed for every accepted frame on every candidate — at full source resolution, inside
    the inner loop — which made the pass O(n^2) in `cvtColor` + `calcHist` over 1440x1080 images
    rather than O(n^2) in cheap dot products. On a clip yielding ~190 keyframes that is ~18,000
    full-resolution histograms where 190 suffice. The selection is unchanged: the same frames are
    compared against the same frames, in the same order.
    """
    if len(candidates) <= 1:
        return candidates

    def descriptor(kf: ExtractedKeyframe) -> np.ndarray | None:
        if kf.image_array is None:
            return None
        return _hsv_histogram(kf.image_array, None, bottom_crop).flatten()

    filtered: list[ExtractedKeyframe] = [candidates[0]]
    accepted_hists: list[np.ndarray | None] = [descriptor(candidates[0])]

    for cand in candidates[1:]:
        if cand.reason == "heartbeat":
            filtered.append(cand)
            accepted_hists.append(descriptor(cand))
            continue

        cand_hist = descriptor(cand)
        is_redundant = False
        if cand_hist is not None:
            for acc_hist in accepted_hists:
                if acc_hist is not None and compute_cosine_similarity(cand_hist, acc_hist) >= threshold:
                    is_redundant = True
                    break

        if not is_redundant:
            filtered.append(cand)
            accepted_hists.append(cand_hist)

    return filtered


def _extract_lmske(
    frames_stream: Iterable[tuple[int, float, np.ndarray]],
    config: IngestConfig,
    video_id: str = "video",
) -> list[ExtractedKeyframe]:
    """LMSKE 3-stage sequential keyframe extraction engine."""
    # Stage 1 & 2: Candidate Keyframe Generation via Shot Boundaries & Adaptive Thresholding
    candidates = _extract_hsv_heartbeat(frames_stream, config, video_id=video_id)

    # Stage 3: Redundancy Elimination via Cosine similarity
    final_keyframes = _eliminate_lmske_redundancy(
        candidates,
        threshold=config.cosine_similarity_threshold,
        bottom_crop=config.compare_bottom_crop,
    )
    return final_keyframes


def extract_adaptive_keyframes(
    frames_stream: Iterable[tuple[int, float, np.ndarray]],
    config: IngestConfig,
    video_id: str = "video",
) -> list[ExtractedKeyframe]:
    """Dispatch keyframe extraction to LMSKE engine or HSV/Heartbeat fallback engine."""
    strategy = getattr(config, "keyframing_strategy", "lmske")

    if strategy == "lmske":
        try:
            return _extract_lmske(frames_stream, config, video_id=video_id)
        except Exception as err:
            if getattr(config, "enable_auto_fallback", True):
                logger.warning(
                    "[WARNING] LMSKE keyframing engine failed (%s). Triggering automatic fallback to hsv_heartbeat.",
                    err,
                )
                return _extract_hsv_heartbeat(frames_stream, config, video_id=video_id)
            raise err

    # Default / Fallback Mode
    return _extract_hsv_heartbeat(frames_stream, config, video_id=video_id)
