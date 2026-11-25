"""Unit tests and Phase 1 validation for offline video ingestion pipeline (FR-01)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from src.services.ingest.keyframing import (
    compute_hsv_histogram_diff,
    extract_adaptive_keyframes,
)
from src.services.ingest.models import ExtractedKeyframe, IngestConfig
from src.services.ingest.quality import QualityGate
from src.services.ingest.reselect import BladeAvoider, _choose
from src.services.ingest.video_loader import get_video_metadata, stream_video_frames


def test_hsv_histogram_diff_same_and_different() -> None:
    """Verify HSV Bhattacharyya distance returns zero for identical arrays and >0.4 for distinct colors."""
    img_red = np.zeros((100, 100, 3), dtype=np.uint8)
    img_red[:, :, 2] = 255
    img_blue = np.zeros((100, 100, 3), dtype=np.uint8)
    img_blue[:, :, 0] = 255

    diff_same = compute_hsv_histogram_diff(img_red, img_red)
    diff_different = compute_hsv_histogram_diff(img_red, img_blue)

    assert diff_same < 1e-4
    assert diff_different > 0.40


def test_adaptive_keyframing_static_reduction_rate() -> None:
    """Validate stationary video streams achieve >=90% data reduction rate via 5s heartbeat (NFR-01.2)."""
    static_frame = np.full((64, 64, 3), 128, dtype=np.uint8)
    stream = [(i, round(i / 30.0, 3), static_frame) for i in range(300)]

    cfg = IngestConfig(max_heartbeat_s=5.0, keyframing_strategy="hsv_heartbeat")
    keyframes = extract_adaptive_keyframes(stream, cfg, video_id="static_clip")

    assert len(keyframes) == 2
    assert keyframes[0].frame_idx == 0 and keyframes[0].reason == "event"
    assert keyframes[1].frame_idx == 150 and keyframes[1].reason == "heartbeat"

    reduction_rate = (1.0 - len(keyframes) / 300.0) * 100.0
    assert reduction_rate >= 90.0


def test_adaptive_keyframing_dynamic_event_capture() -> None:
    """Validate rapid visual transitions trigger immediate event keyframes without waiting for heartbeat."""
    bg_frame = np.zeros((64, 64, 3), dtype=np.uint8)
    event_frame = np.full((64, 64, 3), 200, dtype=np.uint8)

    stream = []
    for i in range(90):
        ts = round(i / 30.0, 3)
        stream.append((i, ts, event_frame if i >= 60 else bg_frame))

    cfg = IngestConfig(hist_diff_threshold=0.35, max_heartbeat_s=5.0, keyframing_strategy="hsv_heartbeat")
    keyframes = extract_adaptive_keyframes(stream, cfg, video_id="dynamic_clip")

    assert len(keyframes) == 2
    assert keyframes[0].frame_idx == 0
    assert keyframes[1].frame_idx == 60 and keyframes[1].reason == "event"
    assert keyframes[1].timestamp_s == 2.0


def test_lmske_dual_engine_extraction() -> None:
    """Test LMSKE 3-stage keyframing strategy and Cosine redundancy removal."""
    bg_frame = np.zeros((64, 64, 3), dtype=np.uint8)
    event_frame_1 = np.full((64, 64, 3), 180, dtype=np.uint8)
    event_frame_dup = np.full((64, 64, 3), 180, dtype=np.uint8)

    stream = [
        (0, 0.0, bg_frame),
        (30, 1.0, event_frame_1),
        (60, 2.0, event_frame_dup),  # Duplicate of event_frame_1
    ]

    cfg = IngestConfig(
        hist_diff_threshold=0.35,
        keyframing_strategy="lmske",
        cosine_similarity_threshold=0.80,
    )
    keyframes = extract_adaptive_keyframes(stream, cfg, video_id="lmske_clip")

    assert len(keyframes) >= 1
    assert keyframes[0].frame_idx == 0


def test_automatic_fallback_on_exception(monkeypatch) -> None:
    """Verify automatic fail-safe fallback to hsv_heartbeat when LMSKE raises an exception."""
    from src.services.ingest import keyframing

    def mock_failing_lmske(*args, **kwargs):
        raise RuntimeError("Simulated GPU Out-Of-Memory Error")

    monkeypatch.setattr(keyframing, "_extract_lmske", mock_failing_lmske)

    bg_frame = np.zeros((64, 64, 3), dtype=np.uint8)
    stream = [(i, round(i / 30.0, 3), bg_frame) for i in range(160)]

    cfg = IngestConfig(keyframing_strategy="lmske", enable_auto_fallback=True)
    keyframes = keyframing.extract_adaptive_keyframes(stream, cfg, video_id="fallback_clip")

    assert len(keyframes) == 2
    assert keyframes[0].frame_idx == 0
    assert keyframes[1].frame_idx == 150 and keyframes[1].reason == "heartbeat"


def test_video_loader_and_streaming_interface(tmp_path: Path) -> None:
    """Verify OpenCV video loader extracts precise metadata and sequential frame timestamps."""
    vid_path = str(tmp_path / "sample.avi")
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(vid_path, fourcc, 10.0, (80, 80))

    try:
        for _ in range(15):
            writer.write(np.zeros((80, 80, 3), dtype=np.uint8))
    finally:
        writer.release()

    meta = get_video_metadata(vid_path, video_id="test_vid")
    assert meta.video_id == "test_vid"
    assert meta.total_frames == 15 and meta.width == 80 and meta.height == 80

    frames = list(stream_video_frames(vid_path, fps=10.0))
    assert len(frames) == 15
    assert frames[10][0] == 10 and frames[10][1] == 1.0


def test_sample_fps_decimates_without_moving_timestamps(tmp_path: Path) -> None:
    """`sample_fps` must skip frames, and the frames it yields must keep their SOURCE position.

    The parameter this replaces (`fps`) only relabelled timestamps, so on 60 fps footage asking for
    15 decoded everything and dated each frame four times too late. `frame_idx` is the sidecar's
    only link back to the source video, so decimation may not renumber it.
    """
    vid_path = str(tmp_path / "sampled.avi")
    writer = cv2.VideoWriter(vid_path, cv2.VideoWriter_fourcc(*"MJPG"), 20.0, (64, 64))
    try:
        for _ in range(40):
            writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    finally:
        writer.release()

    frames = list(stream_video_frames(vid_path, sample_fps=5.0))

    assert len(frames) == 10  # 20 fps / 5 fps -> every 4th frame
    assert [f[0] for f in frames[:3]] == [0, 4, 8]  # source indices, not 0,1,2
    assert frames[2][1] == 0.4  # 8 / 20 fps, the true source timestamp


def test_bottom_crop_ignores_the_car_and_not_the_road() -> None:
    """The comparison crop must hide a change confined to the bonnet band, and only that."""
    base = np.zeros((100, 100, 3), dtype=np.uint8)
    base[:, :, 2] = 255
    bonnet_changed = base.copy()
    bonnet_changed[80:, :, :] = (255, 0, 0)  # only the bottom 20% differs
    road_changed = base.copy()
    road_changed[:50, :, :] = (255, 0, 0)  # the upper half differs

    assert compute_hsv_histogram_diff(base, bonnet_changed) > 0.30
    assert compute_hsv_histogram_diff(base, bonnet_changed, bottom_crop=0.25) < 1e-4
    assert compute_hsv_histogram_diff(base, road_changed, bottom_crop=0.25) > 0.30


def _frames(images: list[np.ndarray]) -> list[ExtractedKeyframe]:
    return [
        ExtractedKeyframe(
            frame_id=f"c_f{i:05d}", video_id="c", timestamp_s=float(i), frame_idx=i, reason="event", image_array=img
        )
        for i, img in enumerate(images)
    ]


def test_quality_gate_rejects_a_blank_frame_and_stands_down_on_small_samples() -> None:
    """A frame with no detail is rejected with a reason; too few frames means no gate at all."""
    rng = np.random.default_rng(0)
    textured = [rng.integers(0, 255, (120, 160, 3), dtype=np.uint8) for _ in range(14)]
    blank = np.full((120, 160, 3), 128, dtype=np.uint8)  # uniform: no edges to find

    frames = _frames([*textured, blank])

    kept, rejected = QualityGate().apply(frames)
    assert len(rejected) == 1
    assert rejected[0]["rejected_for"] == "no_detail"
    assert len(kept) == len(frames) - 1

    # Below MIN_SAMPLE a median summarises nothing, so the gate must pass everything through.
    kept_small, rejected_small = QualityGate().apply(frames[:5])
    assert len(kept_small) == 5 and rejected_small == []


def test_occlusion_alone_never_rejects_without_the_source_video() -> None:
    """The regression that cost a re-run: dark-and-flat is not enough to delete a frame.

    A large dark region is a wiper blade *or* tree canopy, an underpass, or deep shadow — measured,
    those overlap completely (wipers 0.29-0.32, canopy 0.29-0.41, an underpass 0.42). Only the
    source video either side can tell them apart, so with no video to consult the gate must keep the
    frame. The first version rejected on the score alone and deleted a busy intersection and a
    tunnel mouth from the corpus.
    """
    kf = ExtractedKeyframe(frame_id="c_f00001", video_id="c", timestamp_s=1.0, frame_idx=60, reason="event")

    # Even a frame that is almost entirely dark and flat cannot be called a wiper unaided.
    assert QualityGate(video_path=None).is_transient(kf, occlusion=0.95, fps=60.0) is False

    # Nor when the video is known but the frame rate is not, which is the same missing evidence.
    assert QualityGate(video_path="clip.mp4").is_transient(kf, occlusion=0.95, fps=0.0) is False


def _blade_clip(tmp_path: Path, blade_at: set[int], n: int = 60) -> tuple[str, list[np.ndarray]]:
    """A synthetic 60-frame clip whose named frames carry a dark band across the scene."""
    rng = np.random.default_rng(7)
    base = rng.integers(90, 200, (120, 160, 3), dtype=np.uint8)
    frames = []
    for i in range(n):
        img = base.copy()
        img[:, :] = np.clip(base.astype(np.int16) + (i % 5), 0, 255).astype(np.uint8)
        if i in blade_at:
            img[20:70, :] = 4  # a near-black band, as a blade is
        frames.append(img)
    path = str(tmp_path / "blade.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 60.0, (160, 120))
    for img in frames:
        writer.write(img)
    writer.release()
    return path, frames


def test_blade_avoider_moves_the_selection_and_records_the_move(tmp_path: Path) -> None:
    """A frame the blade crossed is re-pointed at nearby clear footage, not deleted."""
    path, _ = _blade_clip(tmp_path, blade_at={30})
    kf = ExtractedKeyframe(frame_id="blade_f00030", video_id="blade", timestamp_s=0.5, frame_idx=30, reason="event")

    kept, swaps = BladeAvoider(video_path=path).refine([kf], fps=60.0)

    assert len(swaps) == 1, "the blade frame should have been moved"
    assert kept[0].frame_idx != 30, "the selection must actually point somewhere else"
    assert abs(kept[0].frame_idx - 30) <= 0.6 * 60, "and stay inside the window"
    # The identity travels with the index, or the sidecar names a frame that was never written.
    assert kept[0].frame_id == f"blade_f{kept[0].frame_idx:05d}"
    assert kept[0].timestamp_s == round(kept[0].frame_idx / 60.0, 3)
    assert swaps[0]["blade_after"] < swaps[0]["blade_before"]


def test_blade_avoider_leaves_clear_frames_and_needs_the_video(tmp_path: Path) -> None:
    """No blade means no swap; no video means no opinion — the frame is kept as selected."""
    path, _ = _blade_clip(tmp_path, blade_at=set())
    kf = ExtractedKeyframe(frame_id="blade_f00030", video_id="blade", timestamp_s=0.5, frame_idx=30, reason="event")

    kept, swaps = BladeAvoider(video_path=path).refine([kf], fps=60.0)
    assert swaps == [] and kept[0].frame_idx == 30

    # The regression this shares with QualityGate.is_transient: with nothing to compare against,
    # a selection must never be moved on the strength of the frame alone.
    kept_blind, swaps_blind = BladeAvoider(video_path=None).refine([kf], fps=60.0)
    assert swaps_blind == [] and kept_blind[0].frame_idx == 30

    # Nor when the video is known but the frame rate is not.
    assert BladeAvoider(video_path=path).window_scores(30, fps=0.0) == []


def test_blade_avoider_never_collapses_two_selections_onto_one_frame(tmp_path: Path) -> None:
    """Event keyframes can be a fifth of a second apart, so two can want the same replacement.

    Measured on clip09_hanoi, which selects f11832 and f11840 — 8 frames apart at 60 fps. Without
    the `taken` set both move to the same clear frame and the corpus gains a duplicate under two
    different names, which no downstream stage can detect.
    """
    path, _ = _blade_clip(tmp_path, blade_at={30, 31, 32, 33, 34})
    frames = [
        ExtractedKeyframe(
            frame_id=f"blade_f{i:05d}", video_id="blade", timestamp_s=i / 60.0, frame_idx=i, reason="event"
        )
        for i in (31, 33)
    ]

    kept, _ = BladeAvoider(video_path=path).refine(frames, fps=60.0)

    assert len({kf.frame_idx for kf in kept}) == 2
    assert len({kf.frame_id for kf in kept}) == 2


def test_blade_avoider_streaming_and_seeking_paths_agree(tmp_path: Path) -> None:
    """`refine` streams the clip once; `replacement` seeks per frame. They must not diverge.

    Two implementations of one decision exist because seeking cost 6-8 hours across the 24-clip
    corpus and streaming costs minutes, while the seeking form is still what you want to inspect a
    single selection. Two code paths that must agree are two code paths that will drift apart, so
    the agreement is asserted rather than assumed.
    """
    path, _ = _blade_clip(tmp_path, blade_at={20, 21, 40})
    wanted = {12, 20, 32, 40, 48}
    avoider = BladeAvoider(video_path=path)

    streamed = avoider.all_windows(wanted, fps=60.0)
    for idx in sorted(wanted):
        by_seek = dict(avoider.window_scores(idx, fps=60.0))
        by_stream = dict(streamed[idx])
        # Membership, not just the overlap. Comparing only shared samples hid a real difference:
        # the seeking path used to read a fixed frame *count* from a start clamped at 0, so near
        # the head of a clip its window ran forward to +1.2 s with nothing before the centre.
        assert set(by_seek) == set(by_stream), f"windows differ in membership at {idx}"
        for j in by_seek:
            assert by_seek[j] == pytest.approx(by_stream[j], abs=1e-9)

    # And the decision itself, which is what actually reaches the corpus.
    for idx in sorted(wanted):
        assert _choose(avoider.window_scores(idx, 60.0), idx, set()) == _choose(streamed[idx], idx, set())


def test_blade_avoider_window_is_centred_even_at_the_start_of_a_clip(tmp_path: Path) -> None:
    """A selection at frame 0 must not be judged against footage that is only ahead of it.

    The window is bounded by distance from the frame, so at the head of a clip it is short on one
    side rather than stretched on the other. Reading a fixed count forward from a clamped start
    gave frame 0 a window running to +1.2 s and nothing behind it.
    """
    path, _ = _blade_clip(tmp_path, blade_at=set())
    scores = BladeAvoider(video_path=path).window_scores(0, fps=60.0)

    assert scores, "a short window is still a window"
    assert max(i for i, _ in scores) <= 0 + int(0.6 * 60), "window reached past +0.6 s"


def test_blade_avoider_keeps_the_sidecar_in_source_order(tmp_path: Path) -> None:
    """Two selections closer together than the window can cross when only one of them moves.

    Measured over the 24-clip corpus before this was fixed: 9 inversions across 5 clips, each a
    single 0.067 s sample step. `ingest_folder` reads the sidecar in order, and nothing downstream
    checks that timestamps increase, so an inverted pair rides all the way into the corpus.
    """
    path, _ = _blade_clip(tmp_path, blade_at={34, 35, 36})
    # 36 can move back to ~30; 32 is already clear and stays put, so the two cross.
    frames = [
        ExtractedKeyframe(
            frame_id=f"blade_f{i:05d}", video_id="blade", timestamp_s=round(i / 60.0, 3), frame_idx=i, reason="event"
        )
        for i in (32, 36)
    ]

    kept, _ = BladeAvoider(video_path=path).refine(frames, fps=60.0)

    assert [kf.frame_idx for kf in kept] == sorted(kf.frame_idx for kf in kept)
    assert [kf.timestamp_s for kf in kept] == sorted(kf.timestamp_s for kf in kept)
