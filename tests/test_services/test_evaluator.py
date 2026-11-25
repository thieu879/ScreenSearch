"""Unit tests for the keyframe extraction evaluation module (evaluator.py)."""

from __future__ import annotations

from src.services.ingest.evaluator import (
    TemporalEvent,
    calculate_precision_recall_f1,
    compute_video_evaluation,
    is_frame_in_event_window,
    match_temporal_events,
)
from src.services.ingest.models import ExtractedKeyframe, VideoMetadata


def test_is_frame_in_event_window() -> None:
    """Test boundary checks for matching keyframe timestamps to temporal events."""
    event = TemporalEvent(
        event_id="ev_01",
        video_id="video_01",
        start_s=2.0,
        end_s=4.0,
        label="lane_change",
    )

    assert is_frame_in_event_window(3.0, event, tolerance_s=0.5) is True
    assert is_frame_in_event_window(1.6, event, tolerance_s=0.5) is True
    assert is_frame_in_event_window(4.4, event, tolerance_s=0.5) is True
    assert is_frame_in_event_window(1.4, event, tolerance_s=0.5) is False
    assert is_frame_in_event_window(4.6, event, tolerance_s=0.5) is False


def test_calculate_precision_recall_f1_perfect_match() -> None:
    """Test precision, recall, and F1-score when TP=3, FP=0, FN=0."""
    p, r, f1 = calculate_precision_recall_f1(tp=3, fp=0, fn=0)
    assert p == 1.0
    assert r == 1.0
    assert f1 == 1.0


def test_calculate_precision_recall_f1_partial_match() -> None:
    """Test precision, recall, and F1-score calculation for partial matches."""
    p, r, f1 = calculate_precision_recall_f1(tp=2, fp=2, fn=1)
    assert p == 0.5
    assert r == 2.0 / 3.0
    assert round(f1, 4) == round(2 * 0.5 * (2 / 3) / (0.5 + 2 / 3), 4)


def test_match_temporal_events() -> None:
    """Test matching extracted keyframes against ground truth temporal events."""
    gt_events = [
        TemporalEvent(event_id="e1", video_id="v1", start_s=1.0, end_s=2.0, label="braking"),
        TemporalEvent(event_id="e2", video_id="v1", start_s=10.0, end_s=12.0, label="turning"),
    ]

    keyframes = [
        ExtractedKeyframe(frame_id="f1", video_id="v1", timestamp_s=1.2, frame_idx=36, reason="event"),
        ExtractedKeyframe(frame_id="f2", video_id="v1", timestamp_s=5.0, frame_idx=150, reason="heartbeat"),
        ExtractedKeyframe(frame_id="f3", video_id="v1", timestamp_s=8.0, frame_idx=240, reason="event"),
    ]

    res = match_temporal_events(keyframes, gt_events, tolerance_s=0.5)
    assert res.tp_count == 1  # e1 matched f1
    assert res.fn_count == 1  # e2 not matched
    assert res.fp_count == 1  # f3 is FP (f2 is heartbeat, so excluded from event FP)


def test_compute_video_evaluation() -> None:
    """Test end-to-end video evaluation computation."""
    meta = VideoMetadata(video_id="v1", fps=30.0, total_frames=300, width=1920, height=1080)
    gt_events = [TemporalEvent(event_id="e1", video_id="v1", start_s=1.0, end_s=2.0, label="event_1")]
    keyframes = [
        ExtractedKeyframe(frame_id="f1", video_id="v1", timestamp_s=1.1, frame_idx=33, reason="event"),
        ExtractedKeyframe(frame_id="f2", video_id="v1", timestamp_s=5.0, frame_idx=150, reason="heartbeat"),
    ]

    eval_res = compute_video_evaluation(meta, keyframes, gt_events)
    assert eval_res.video_id == "v1"
    assert eval_res.extracted_count == 2
    assert eval_res.reduction_rate == (1.0 - 2 / 300) * 100.0
    assert eval_res.precision == 1.0
    assert eval_res.recall == 1.0
    assert eval_res.f1_score == 1.0
