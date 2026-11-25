"""Evaluation metrics and temporal ground-truth matching for keyframe extraction."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from src.services.ingest.models import ExtractedKeyframe, VideoMetadata


class TemporalEvent(BaseModel):
    """Ground truth temporal event interval annotated in a video clip."""

    event_id: str = Field(description="Unique event identifier.")
    video_id: str = Field(description="Source video identifier.")
    start_s: float = Field(description="Event start timestamp in seconds.")
    end_s: float = Field(description="Event end timestamp in seconds.")
    label: str = Field(description="Category label (e.g., 'lane_change', 'braking', 'turning').")


class EvalMatchResult(BaseModel):
    """Result of matching extracted keyframes against ground truth temporal events."""

    tp_count: int = Field(default=0, description="True positives count.")
    fp_count: int = Field(default=0, description="False positives count.")
    fn_count: int = Field(default=0, description="False negatives count.")


class VideoEvalResult(BaseModel):
    """Consolidated quantitative evaluation metrics for a single video clip."""

    video_id: str = Field(description="Unique video identifier.")
    total_frames: int = Field(description="Total video frames.")
    fps: float = Field(description="Video frame rate.")
    duration_s: float = Field(description="Duration in seconds.")
    extracted_count: int = Field(description="Number of keyframes extracted.")
    gt_event_count: int = Field(description="Number of ground truth events.")
    reduction_rate: float = Field(description="Data reduction percentage (0-100%).")
    precision: float = Field(description="Event extraction precision (0-1).")
    recall: float = Field(description="Event extraction recall (0-1).")
    f1_score: float = Field(description="Harmonic mean F1-Score (0-1).")


def is_frame_in_event_window(kf_timestamp: float, event: TemporalEvent, tolerance_s: float = 0.5) -> bool:
    """Check if a keyframe timestamp falls within an event window extended by tolerance_s."""
    return (event.start_s - tolerance_s) <= kf_timestamp <= (event.end_s + tolerance_s)


def match_temporal_events(
    keyframes: Sequence[ExtractedKeyframe],
    gt_events: Sequence[TemporalEvent],
    tolerance_s: float = 0.5,
) -> EvalMatchResult:
    """Match extracted event keyframes against ground truth events using a temporal tolerance window."""
    event_keyframes = [kf for kf in keyframes if kf.reason == "event"]
    matched_events: set[str] = set()
    matched_keyframes: set[str] = set()

    for kf in event_keyframes:
        for ev in gt_events:
            if is_frame_in_event_window(kf.timestamp_s, ev, tolerance_s=tolerance_s):
                matched_events.add(ev.event_id)
                matched_keyframes.add(kf.frame_id)

    tp = len(matched_events)
    fn = len(gt_events) - tp
    fp = len(event_keyframes) - len(matched_keyframes)

    return EvalMatchResult(tp_count=tp, fp_count=fp, fn_count=fn)


def calculate_precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """Calculate Precision, Recall, and F1-Score given TP, FP, FN counts."""
    precision = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if tp == 0 and fp == 0 else 0.0)
    recall = tp / (tp + fn) if (tp + fn) > 0 else (1.0 if tp == 0 and fn == 0 else 0.0)
    f1 = (2.0 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def compute_video_evaluation(
    meta: VideoMetadata,
    keyframes: Sequence[ExtractedKeyframe],
    gt_events: Sequence[TemporalEvent],
) -> VideoEvalResult:
    """Compute consolidated evaluation metrics for a single video ingestion run."""
    duration_s = meta.total_frames / meta.fps if meta.fps > 0 else 0.0
    match_res = match_temporal_events(keyframes, gt_events)
    precision, recall, f1 = calculate_precision_recall_f1(match_res.tp_count, match_res.fp_count, match_res.fn_count)
    reduction = (1.0 - len(keyframes) / max(1, meta.total_frames)) * 100.0

    return VideoEvalResult(
        video_id=meta.video_id,
        total_frames=meta.total_frames,
        fps=meta.fps,
        duration_s=duration_s,
        extracted_count=len(keyframes),
        gt_event_count=len(gt_events),
        reduction_rate=reduction,
        precision=precision,
        recall=recall,
        f1_score=f1,
    )
