import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from verify_privacy_assets import verify  # noqa: E402


def _write(path, rows):
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_verify_requires_complete_privacy_coverage(tmp_path):
    artifacts = tmp_path / "artifacts"
    thumbs = tmp_path / "thumbs"
    artifacts.mkdir()
    thumbs.mkdir()
    _write(artifacts / "frames.jsonl", [{"frame_id": "f1", "image_path": "scene/0001.jpg"}])
    _write(
        artifacts / "privacy_detections.jsonl",
        [{"image": "0001.jpg", "dets": [], "privacy": {"backend": "ultralytics"}}],
    )
    (thumbs / "f1.jpg").write_bytes(b"jpg")
    (artifacts / "provenance.json").write_text(
        json.dumps(
            {
                "privacy": {"backend": "ultralytics"},
                "anonymisation": {"privacy_unverified": 0},
            }
        ),
        encoding="utf-8",
    )
    assert verify(str(artifacts), str(thumbs))["frames"] == 1


def test_verify_rejects_a_thumbnail_no_corpus_frame_claims(tmp_path):
    """`thumbs_dir` is what the API serves, so an image there that the corpus does not claim was
    published without passing through redaction. `scripts/ingest/run_keyframing.py` writes exactly
    such thumbnails straight from raw video; checking only for *missing* ones calls that clean."""
    artifacts = tmp_path / "artifacts"
    thumbs = tmp_path / "thumbs"
    artifacts.mkdir()
    thumbs.mkdir()
    _write(artifacts / "frames.jsonl", [{"frame_id": "f1", "image_path": "scene/0001.jpg"}])
    _write(
        artifacts / "privacy_detections.jsonl",
        [{"image": "0001.jpg", "dets": [], "privacy": {"backend": "ultralytics"}}],
    )
    (thumbs / "f1.jpg").write_bytes(b"jpg")
    (thumbs / "traffic_jam_f02372.jpg").write_bytes(b"jpg")  # what run_keyframing leaves behind
    (artifacts / "provenance.json").write_text(
        json.dumps(
            {
                "privacy": {"backend": "ultralytics"},
                "anonymisation": {"privacy_unverified": 0},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="traffic_jam_f02372"):
        verify(str(artifacts), str(thumbs))


def test_verify_rejects_a_certificate_from_different_weights(tmp_path):
    """Presence is not agreement: a corpus redacted with one model beside a cache regenerated with
    another would otherwise pass, and nothing else in the pipeline compares the two."""
    artifacts = tmp_path / "artifacts"
    thumbs = tmp_path / "thumbs"
    artifacts.mkdir()
    thumbs.mkdir()
    _write(artifacts / "frames.jsonl", [{"frame_id": "f1", "image_path": "scene/0001.jpg"}])
    _write(
        artifacts / "privacy_detections.jsonl",
        [{"image": "0001.jpg", "dets": [], "privacy": {"face_model": "face-b.pt"}}],
    )
    (thumbs / "f1.jpg").write_bytes(b"jpg")
    (artifacts / "provenance.json").write_text(
        json.dumps(
            {
                "privacy": {"face_model": "face-a.pt"},
                "anonymisation": {"privacy_unverified": 0},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="different privacy configuration"):
        verify(str(artifacts), str(thumbs))


def test_verify_rejects_unverified_provenance(tmp_path):
    artifacts = tmp_path / "artifacts"
    thumbs = tmp_path / "thumbs"
    artifacts.mkdir()
    thumbs.mkdir()
    _write(artifacts / "frames.jsonl", [{"frame_id": "f1", "image_path": "0001.jpg"}])
    _write(artifacts / "privacy_detections.jsonl", [{"image": "0001.jpg", "dets": [], "privacy": {}}])
    (thumbs / "f1.jpg").write_bytes(b"jpg")
    (artifacts / "provenance.json").write_text(
        json.dumps({"privacy": {}, "anonymisation": {"privacy_unverified": 1}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="privacy-unverified"):
        verify(str(artifacts), str(thumbs))


def _clean_corpus(tmp_path):
    """A minimal corpus that `verify` accepts, so a test can break exactly one thing about it."""
    artifacts = tmp_path / "artifacts"
    thumbs = tmp_path / "thumbs"
    artifacts.mkdir()
    thumbs.mkdir()
    privacy = {"backend": "ultralytics", "face_model": "face.pt", "plate_model": "plate.pt"}
    _write(artifacts / "frames.jsonl", [{"frame_id": "f1", "image_path": "scene/0001.jpg"}])
    _write(artifacts / "privacy_detections.jsonl", [{"image": "0001.jpg", "dets": [], "privacy": privacy}])
    (thumbs / "f1.jpg").write_bytes(b"jpg")
    (artifacts / "provenance.json").write_text(
        json.dumps(
            {
                "privacy": privacy,
                "anonymisation": {"privacy_unverified": 0},
            }
        ),
        encoding="utf-8",
    )
    return artifacts, thumbs


def test_publish_refuses_an_uncleared_thumbnail_directory(tmp_path):
    """The gate has to run where publication happens, not only where someone remembers to type it.

    The unredacted set currently on the Hub was uploaded by a path that never asked, so a passing
    `verify` proves only that the corpus was clean at some point before the upload.
    """
    from publish_assets import require_privacy_clearance

    artifacts, thumbs = _clean_corpus(tmp_path)
    os.remove(artifacts / "privacy_detections.jsonl")
    with pytest.raises(SystemExit) as exc:
        require_privacy_clearance(str(artifacts), str(thumbs))
    assert "REFUSING TO PUBLISH" in str(exc.value)


def test_publish_clears_a_certified_corpus(tmp_path):
    from publish_assets import require_privacy_clearance

    artifacts, thumbs = _clean_corpus(tmp_path)
    assert require_privacy_clearance(str(artifacts), str(thumbs))["frames"] == 1
