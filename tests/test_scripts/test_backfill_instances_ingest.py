"""The folder-ingest backfill must key boxes by frame id, and read the camera per clip.

Both are the same class of bug: something that is correct for a one-video corpus and silently wrong
for a many-video one, which is the only kind `ingest_folder` produces.

**Basename collision.** The detector caches are keyed by *image basename* and `extract_keyframes.py`
numbers every clip from the same starting frame, so `clip01` and `clip02` both contain
`..._f00000.jpg`. `ingest_folder` gives each video its own workdir precisely so one cache cannot
serve another's boxes; a backfill that flattened the caches into one basename-keyed dict would
re-introduce that collision and report a completely successful migration.

**Per-clip camera.** A corpus may hold clips from different cameras, and `fx` comes from the declared
FOV. Reading one clip's FOV and applying it to another's frames is M2_DESIGN §10.5's failure applied
to a subset — harder to notice than getting it wrong everywhere, because most frames stay right.

The additive-migration guard itself is not re-tested here: `merged` and `drifted` are imported from
`backfill_instances.py` and covered by `test_backfill_preserves_existing_keys.py`, which is the point
of importing them rather than copying them.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
)

backfill = pytest.importorskip("backfill_instances_ingest")


def _cache(workdir: str, video_id: str, image: str) -> None:
    """Write one clip's detector cache where `cache_index` expects to find it."""
    folder = os.path.join(workdir, video_id, "artifacts", "metadata")
    os.makedirs(folder, exist_ok=True)
    row = {"image": image, "dets": [{"label": "car", "score": 0.9, "box": [10.0, 10.0, 60.0, 60.0]}]}
    with open(os.path.join(folder, backfill.DETECTIONS), "w", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def test_same_basename_in_two_clips_does_not_collide(tmp_path) -> None:
    """The collision the per-video workdir exists to prevent, at the point a backfill could undo it."""
    workdir = str(tmp_path)
    _cache(workdir, "clip01_hanoi", "frame_f00000.jpg")
    _cache(workdir, "clip02_hanoi", "frame_f00000.jpg")
    index = backfill.cache_index(workdir)
    assert len(index) == 2
    assert {video for video, _ in index.values()} == {"clip01_hanoi", "clip02_hanoi"}


def test_index_is_keyed_by_frame_id_not_basename(tmp_path) -> None:
    """Keys must be what `metadata.jsonl` records, or the intersection silently finds nothing."""
    workdir = str(tmp_path)
    _cache(workdir, "clip01_hanoi", "frame_f00000.jpg")
    index = backfill.cache_index(workdir)
    expected = backfill.frame_id_for("clip01_hanoi", "frame_f00000.jpg")
    assert list(index) == [expected]


def test_camera_is_read_per_clip() -> None:
    """Two clips, two cameras — each must get its own declared FOV."""
    provenance = {
        "intrinsics": {
            "hfov_deg": {"clip01_hanoi": 90.0, "clip02_hanoi": 120.0},
            "bonnet_top": {"clip01_hanoi": 0.75, "clip02_hanoi": 1.0},
        }
    }
    assert backfill.camera_of(provenance, "clip01_hanoi") == (90.0, 0.75)
    assert backfill.camera_of(provenance, "clip02_hanoi") == (120.0, 1.0)


def test_missing_camera_raises_rather_than_defaulting() -> None:
    """A default FOV would put wrong bands on real frames and still write a plausible corpus."""
    with pytest.raises(KeyError, match="clip99_hanoi"):
        backfill.camera_of({"intrinsics": {"hfov_deg": {}, "bonnet_top": {}}}, "clip99_hanoi")


def test_rebuild_skips_frames_the_caches_do_not_cover(tmp_path) -> None:
    """Coverage is checked by the caller; `rebuild` must not invent a record it has no boxes for."""
    workdir = str(tmp_path)
    _cache(workdir, "clip01_hanoi", "frame_f00000.jpg")
    covered = backfill.frame_id_for("clip01_hanoi", "frame_f00000.jpg")
    old = [{"frame_id": covered}, {"frame_id": "deadbeef" * 4 + "_CAM_FRONT"}]
    ctx = {
        "width": 1440,
        "height": 1080,
        "provenance": {"intrinsics": {"hfov_deg": {"clip01_hanoi": 90.0}, "bonnet_top": {"clip01_hanoi": 0.75}}},
    }
    out = backfill.rebuild(old, backfill.cache_index(workdir), ctx)
    assert list(out) == [covered]
    assert "instances" in out[covered]
