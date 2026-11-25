"""Face and plate redaction — Brief §Bảo mật.

`scripts/anonymise.py` is ingest code, but the geometry and the mosaic are the parts that can be
quietly wrong, and "quietly wrong" for a privacy control means shipping an identifiable face. So
they are pure functions and they are tested here with the rest of the suite.

What is *not* testable here, and is stated in the module docstring instead: recall. These assert
that a detected person's head is covered, never that every person was detected.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
)

from anonymise import (  # noqa: E402
    HEAD_FRACTION,
    MOSAIC_SAMPLES,
    head_region,
    load_detections,
    redact,
    regions_for,
)

FACE = {"label": "face", "score": 0.9, "box": [100.0, 200.0, 140.0, 240.0]}
PLATE = {"label": "license_plate", "score": 0.99, "box": [200.0, 400.0, 240.0, 420.0]}
TRUCK = {"label": "truck", "score": 0.99, "box": [200.0, 200.0, 1200.0, 700.0]}
PERSON = {"label": "person", "score": 0.9, "box": [100.0, 200.0, 140.0, 320.0]}


def pixels(image) -> list:
    """Flat pixel list. `getdata()` is deprecated in Pillow 12 and removed in 14; this keeps the
    suite warning-free on both without pinning a Pillow version the project does not declare
    (it arrives transitively with the pinned `torchvision`)."""
    reader = getattr(image, "get_flattened_data", None) or image.getdata
    return list(reader())


class TestRegionGeometry:
    def test_face_detection_gets_a_small_expanded_region(self):
        assert regions_for([FACE]) == [(97.0, 197.0, 143.0, 243.0)]

    def test_plate_detection_gets_a_small_expanded_region(self):
        assert regions_for([PLATE]) == [(198.0, 398.0, 242.0, 422.0)]

    def test_a_face_and_a_plate_each_produce_a_region(self):
        assert regions_for([FACE])
        assert regions_for([PLATE])

    def test_generic_vehicle_box_never_becomes_a_privacy_region(self):
        """The regression this rewrite exists for: masking a proportional band of a `truck` box
        destroyed the wheels and flank of a semi-truck while locating no plate at all."""
        assert regions_for([TRUCK]) == []

    def test_the_head_region_is_the_top_of_a_person_box(self):
        x1, y1, x2, y2 = head_region(PERSON["box"])
        assert (x1, x2) == (100.0, 140.0), "full width — a turned head is still a head"
        assert y1 == 200.0
        assert y2 == pytest.approx(200.0 + 120.0 * HEAD_FRACTION)

    def test_the_head_region_covers_more_than_an_anatomical_head(self):
        """Deliberate over-blur: a seated or occluded person's box is torso-up, so a tight
        one-eighth band would sit above their actual head."""
        assert HEAD_FRACTION > 1 / 8

    def test_labels_with_nothing_identifying_are_left_alone(self):
        """Blurring every detection would smear the scene for no privacy gain."""
        assert regions_for([{"label": "traffic light", "box": [0.0, 0.0, 10.0, 10.0]}]) == []
        assert regions_for([{"label": "bicycle", "box": [0.0, 0.0, 10.0, 10.0]}]) == []

    def test_every_privacy_label_is_covered(self):
        for label in ("face", "license_plate"):
            assert regions_for([{"label": label, "box": [0.0, 0.0, 10.0, 10.0]}]), label

    def test_a_distant_box_is_still_redacted(self):
        """No minimum size: 'too small to identify' is not this code's judgement to make."""
        assert regions_for([{"label": "face", "box": [10.0, 10.0, 13.0, 18.0]}])


class TestRedact:
    @staticmethod
    def _noise(width: int = 60, height: int = 60):
        """An image where every pixel differs, so any averaging is detectable."""
        from PIL import Image

        img = Image.new("RGB", (width, height))
        img.putdata([((x * 7) % 256, (y * 11) % 256, (x * y) % 256) for y in range(height) for x in range(width)])
        return img

    def test_pixels_inside_the_region_are_destroyed(self):
        image = self._noise()
        before = pixels(image.crop((10, 10, 40, 40)))
        redact(image, [(10.0, 10.0, 40.0, 40.0)])
        assert pixels(image.crop((10, 10, 40, 40))) != before

    def test_pixels_outside_the_region_are_untouched(self):
        image = self._noise()
        before = pixels(image.crop((45, 45, 60, 60)))
        redact(image, [(10.0, 10.0, 40.0, 40.0)])
        assert pixels(image.crop((45, 45, 60, 60))) == before

    def test_the_region_is_reduced_to_at_most_the_documented_sample_count(self):
        """The privacy claim itself: a mosaic destroys information, it does not smooth it.

        A 30 px region holding at most `MOSAIC_SAMPLES`² distinct colours is what makes the result
        irreversible, unlike a Gaussian, which is a convolution and partially invertible.
        """
        image = self._noise()
        redact(image, [(10.0, 10.0, 40.0, 40.0)])
        distinct = len(set(pixels(image.crop((10, 10, 40, 40)))))
        assert distinct <= (MOSAIC_SAMPLES + 1) ** 2

    def test_a_region_running_past_the_edge_is_clipped_not_an_error(self):
        """Detector boxes routinely touch the frame border."""
        image = self._noise()
        redact(image, [(50.0, 50.0, 200.0, 200.0)])
        assert image.size == (60, 60)

    def test_a_degenerate_region_is_skipped(self):
        image = self._noise()
        before = pixels(image)
        redact(image, [(10.0, 10.0, 10.0, 10.0), (-5.0, -5.0, -1.0, -1.0)])
        assert pixels(image) == before

    def test_a_frame_with_nothing_detected_is_returned_unchanged(self):
        image = self._noise()
        before = pixels(image)
        assert pixels(redact(image, [])) == before


class TestTheUnionOfBothDetectionSources:
    """Measured on 834 Tokyo frames: the face detector found 8 faces where the retrieval detector
    found 337 people, so 153 of 157 person-frames would have shipped with nothing redacted. Each
    signal alone under-blurs in a way the other covers, and over-blur is the chosen direction."""

    def test_a_person_the_face_detector_missed_is_still_covered(self):
        """The whole reason the head band came back: in driving footage people are overwhelmingly
        turned away or in profile, and a face detector must see a face."""
        assert regions_for([PERSON]) == [head_region(PERSON["box"])]

    def test_a_face_and_the_person_containing_it_both_produce_a_region(self):
        """Overlap is not deduplicated. Mosaicking the same pixels twice is idempotent; picking one
        of the two signals is how a pedestrian goes out unredacted."""
        assert len(regions_for([FACE, PERSON])) == 2

    def test_the_union_covers_all_three_labels_at_once(self):
        assert len(regions_for([FACE, PLATE, PERSON])) == 3

    def test_a_vehicle_in_the_union_still_contributes_nothing(self):
        """The union restores person boxes only. Reinstating vehicle boxes would bring the
        semi-truck regression back with it."""
        assert regions_for([TRUCK, PERSON]) == [head_region(PERSON["box"])]


class TestPrivacyCacheIsNotInterchangeableWithTheRetrievalCache:
    """The two caches share a schema, so the wrong file parses cleanly and redacts nothing.

    That failure is silent all the way to publication: no `face` or `license_plate` label means no
    region, every frame still counts as privacy-verified, and provenance certifies a corpus whose
    thumbnails were never touched. It is 2026-08-03 reached by a different route, so it is refused
    at load time.
    """

    @staticmethod
    def _cache(tmp_path, rows):
        path = tmp_path / "cache.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return str(path)

    def test_a_retrieval_cache_is_refused_where_a_privacy_cache_belongs(self, tmp_path):
        path = self._cache(tmp_path, [{"image": "0001.jpg", "dets": [TRUCK]}])
        with pytest.raises(ValueError, match="no privacy provenance"):
            load_detections(path, require_privacy=True)

    def test_the_same_cache_still_loads_as_retrieval_metadata(self, tmp_path):
        """`ingest_folder` reads the retrieval cache through this function too — the check is
        opt-in for the redaction path, not a blanket rule."""
        path = self._cache(tmp_path, [{"image": "0001.jpg", "dets": [TRUCK]}])
        assert load_detections(path) == {"0001.jpg": [TRUCK]}

    def test_a_real_privacy_cache_loads(self, tmp_path):
        path = self._cache(
            tmp_path,
            [
                {"image": "0001.jpg", "dets": [FACE], "privacy": {"backend": "ultralytics"}},
            ],
        )
        assert load_detections(path, require_privacy=True) == {"0001.jpg": [FACE]}
