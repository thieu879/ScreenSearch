"""The left/right band: one definition, cut at the outer thirds, agreeing across both sides.

`scenesearch/spatial.py` exists because this rule used to live twice — once for detector boxes in
`metadata/extract.py`, once for 3D annotations in `groundtruth/annotations.py` — with a docstring in
each asking the reader to keep them in step. That is the failure the re-band was opened to fix: edit
both and they agree with each other again while the product stays wrong, and the measurement
reproduces either way. These tests fail if a second copy appears, if the cut moves without the
evidence moving, or if the two sides stop meeting in the middle.

The cut is fitted, not chosen: `eval/review/band_sample.csv`, recorded in
`eval/results/spatial_band_nuscenes.json`.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "experiments", "m1"))
from scenesearch.groundtruth.annotations import _relation  # noqa: E402
from scenesearch.metadata.extract import record_from_detections  # noqa: E402
from scenesearch.spatial import THIRDS, box_offset, offset_to_relation, point_offset  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
# nuScenes CAM_FRONT, the corpus this was fitted on.
FX, CX, W, H = 1266.4, 816.0, 1600, 900


class TestTheCut:
    def test_the_band_is_the_outer_thirds(self):
        assert THIRDS == pytest.approx(1 / 6)

    @pytest.mark.parametrize(
        ("offset", "expected"),
        [
            (-0.50, "front_left"),
            (-1 / 6, "front_left"),  # the boundary belongs to the side, not to the centre
            (-0.16, "front"),
            (0.0, "front"),
            (0.16, "front"),
            (1 / 6, "front_right"),
            (0.50, "front_right"),
            (2.0, "front_right"),  # a partly-visible object whose centre is off-frame is still right
        ],
    )
    def test_offsets_band_where_the_sample_says_they_should(self, offset, expected):
        assert offset_to_relation(offset) == expected

    def test_a_clipped_box_is_read_at_its_outer_edge(self):
        """Ground truth bands a 3D centre that sits outside the image for a half-visible object; the
        detector sees only the visible part and reads inward. The edge is a lower bound on the true
        eccentricity, which is why it is used instead of the visible centre."""
        clipped = box_offset([0.0, 0.0, 900.0, 100.0], W)  # touches the left border
        whole = box_offset([0.0 + 5, 0.0, 900.0, 100.0], W)  # 5 px clear of it
        assert clipped == pytest.approx(-0.5)
        assert whole > clipped
        assert offset_to_relation(clipped) == "front_left"


class TestBothSidesShareOneDefinition:
    def test_a_3d_point_and_the_box_it_projects_to_get_the_same_relation(self):
        """The two halves of every spatial measurement meet here: gold projects, predictions measure
        pixels, and if they disagree the number produced is about the disagreement."""
        for x, z in [(5.0, 10.0), (1.0, 30.0), (-8.0, 12.0), (0.0, 20.0), (-1.0, 40.0)]:
            offset = point_offset((x, 0.0, z), FX / W, CX / W)
            u = (offset + 0.5) * W
            box = [u - 20, 400.0, u + 20, 600.0]  # a box centred where the point lands
            gold = _relation((x, 0.0, z), FX / W, CX / W)
            assert gold == offset_to_relation(box_offset(box, W)) == offset_to_relation(offset)

    def test_a_point_behind_the_camera_has_no_relation(self):
        assert _relation((5.0, 0.0, -1.0), FX / W, CX / W) is None
        assert point_offset((5.0, 0.0, 0.0), FX / W, CX / W) is None

    def test_the_detector_path_bands_the_thirds_and_not_the_lens(self):
        """The same box under a wide and a narrow lens is on the same side of the picture."""
        det = [{"label": "person", "score": 0.9, "box": [1100.0, 400.0, 1160.0, 600.0]}]
        wide = record_from_detections(det, 600.0, CX, W, H)
        narrow = record_from_detections(det, 2000.0, CX, W, H)
        assert wide["relations"] == narrow["relations"] == {"pedestrian": ["front_right"]}


class TestTheCutMatchesItsEvidence:
    def test_the_shipped_cut_is_the_one_the_review_was_fitted_to(self):
        """A threshold and its evidence drifting apart is the failure M2_DESIGN 10.3 measured on the
        rejection band. Here it is cheap to prevent: the fit is committed."""
        path = os.path.join(ROOT, "eval", "results", "spatial_band_nuscenes.json")
        if not os.path.exists(path):
            pytest.skip("the fit record is not in this checkout")
        with open(path, encoding="utf-8") as f:
            fitted = json.load(f)
        assert fitted["chosen_cut"] == pytest.approx(THIRDS)
        assert fitted["offset"]["auc"] > fitted["angle_deg"]["auc"], (
            "the band is cut on image offset because offset separated the answers better — "
            "if that stops being true, the choice of space needs re-making, not preserving"
        )
