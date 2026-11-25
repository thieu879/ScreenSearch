"""Per-instance geometry in `metadata.jsonl`, and the caveat for a clause that cannot be filtered.

Both come from one discard. `record_from_detections` used to reduce a frame's boxes to a count per
category plus a *union* of relations, and two product failures follow from that single line:

  · "a pedestrian on the right" matched frames a reviewer calls obviously wrong, because the union
    says only that *some* pedestrian is at the right edge — never which, never how prominent, and
    never how many others dominate the opposite side.
  · "a motorbike to the right of a bus" was inexpressible, because after the reduction there is no
    motorbike and no bus, only the counts 1 and 1.

The first is fixed by keeping the boxes. The second cannot be fixed by data alone — the vocabulary
has no pairwise term — so it is *said* instead, which is the second half of these tests.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "experiments", "m1"))
from scenesearch.metadata.extract import (  # noqa: E402
    horizontal_fov,
    record_from_detections,
)
from scenesearch.spatial import box_offset, offset_to_relation  # noqa: E402

from src.agents.nodes.search_nodes import object_relative_note, respond_node  # noqa: E402
from src.services.llm import _CategoryCondition, _ParsedQuery  # noqa: E402

# Two boxes on a 1000x500 frame: a wide one left of centre, a small one at the right edge.
LEFT = {"label": "person", "score": 0.9, "box": [100.0, 200.0, 300.0, 460.0]}
RIGHT_EDGE = {"label": "person", "score": 0.6, "box": [950.0, 240.0, 990.0, 300.0]}
FX, CX, W, H = 500.0, 500.0, 1000, 500


def _no_corpus():
    """Assemble a response without loading artifacts — these tests are about wording, not ranking.

    `respond_node` builds hits through the corpus on the matched path, and a fresh clone has no
    `data/artifacts/`. Patching keeps them running in CI rather than skipping there, which for a
    caveat the user is meant to see is the wrong test to lose.
    """
    return patch.multiple(
        "src.agents.nodes.search_nodes.service",
        build_hits=lambda *a, **k: [],
        count_distinct_scenes=lambda *a, **k: 0,
    )


class TestInstanceGeometry:
    def test_objects_and_relations_are_untouched_when_height_is_omitted(self):
        """Every published number reads these two keys. The migration is additive or it is wrong."""
        without = record_from_detections([LEFT, RIGHT_EDGE], FX, CX, W)
        with_h = record_from_detections([LEFT, RIGHT_EDGE], FX, CX, W, H)
        assert without["objects"] == with_h["objects"]
        assert without["relations"] == with_h["relations"]
        assert "instances" not in without  # measurement callers get exactly what they got before

    def test_boxes_are_normalised_so_they_mean_the_same_on_any_frame_size(self):
        rec = record_from_detections([LEFT], FX, CX, W, H)
        assert rec["instances"][0]["box"] == [0.1, 0.4, 0.3, 0.92]
        assert rec["instances"][0]["cat"] == "pedestrian"

    def test_instances_are_ordered_by_prominence(self):
        """Head-of-list is the largest box, so "the pedestrian" is a lookup rather than a re-derivation.
        This is what separates "a pedestrian on the right" from "a frame with someone at the edge"."""
        rec = record_from_detections([RIGHT_EDGE, LEFT], FX, CX, W, H)
        first, second = rec["instances"]
        assert first["box"] == [0.1, 0.4, 0.3, 0.92]  # the wide left box, despite being passed second
        assert second["box"][0] > first["box"][0]

    def test_relations_are_reproducible_from_the_instances_alone(self):
        """A consumer must be able to rebuild the shipped fact exactly, not approximate it.

        **The route changed on 2026-08-20 and this test changed with it.** It used to rebuild from
        `angle` through `angle_to_relation`, because the band was cut in bearing. The band is now cut
        on image offset, so the box is what reproduces it — and `angle` would still have passed this
        assertion on these two fixtures by coincidence, which is why the route is pinned explicitly
        rather than left to whichever field happens to agree.

        The box is normalised, so it is denormalised with the record's own `camera.width`: the
        clipped-box tolerance is 4 *pixels* and means nothing in 0..1 units.
        """
        rec = record_from_detections([LEFT, RIGHT_EDGE], FX, CX, W, H)
        width = rec["camera"]["width"]
        rebuilt = {
            offset_to_relation(box_offset([v * width for v in i["box"]], width))
            for i in rec["instances"]
            if i["cat"] == "pedestrian"
        }
        assert rebuilt == set(rec["relations"]["pedestrian"])

    def test_the_camera_block_records_an_off_centre_principal_point(self):
        """nuScenes `cx` spans 786.7-826.6 against an 800.0 centre, and trainval carries three
        distinct CAM_FRONT intrinsics. Without this per frame the boxes cannot be turned back into
        angles, and the half-angles are not equal so the symmetric FOV formula is wrong."""
        rec = record_from_detections([LEFT], 500.0, 400.0, 1000, 500)
        assert rec["camera"]["cx"] == 400.0
        assert rec["camera"]["width"] == 1000
        # 400/500 and 600/500 are different half-angles; 2*atan(500/500) = 90 would be the wrong answer
        assert rec["camera"]["hfov_deg"] == pytest.approx(horizontal_fov(500.0, 400.0, 1000), abs=0.05)
        assert rec["camera"]["hfov_deg"] != pytest.approx(90.0, abs=0.05)


class TestUnsupportedRelationIsReported:
    def test_the_dropped_phrase_survives_onto_the_constraint(self):
        parsed = _ParsedQuery(
            conditions=[_CategoryCondition(category="motorcycle"), _CategoryCondition(category="bus")],
            unsupported_relation="to the right of a bus",
        )
        assert parsed.to_constraint().unsupported_relation == "to the right of a bus"

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_nothing_dropped_normalises_to_none(self, raw):
        assert _ParsedQuery(unsupported_relation=raw).to_constraint().unsupported_relation is None

    def test_no_note_when_the_query_named_no_object_relative_phrase(self):
        assert object_relative_note({"objects": ["car"]}) == ""

    @pytest.mark.asyncio
    async def test_a_hit_admits_the_clause_it_could_not_search_for(self):
        state = {
            "matched": True,
            "constraint": {"objects": ["motorcycle", "bus"], "unsupported_relation": "to the right of a bus"},
            "ranked": [],
            "scores": {},
            "top_k": 10,
        }
        with _no_corpus():
            out = await respond_node(state)
        assert "to the right of a bus" in out["reason"]
        assert "in any arrangement" in out["reason"]

    @pytest.mark.asyncio
    async def test_a_refusal_admits_it_too(self):
        """More important here, not less: the user is about to conclude the archive holds nothing,
        when in fact half their question was never asked."""
        out = await respond_node(
            {
                "matched": False,
                "reason": "Nothing in this archive appears to match that.",
                "constraint": {"objects": ["motorcycle"], "unsupported_relation": "behind the truck"},
            }
        )
        assert "Nothing in this archive" in out["reason"]  # the original refusal is not overwritten
        assert "behind the truck" in out["reason"]

    @pytest.mark.asyncio
    async def test_it_stacks_with_the_widening_caveat_rather_than_replacing_it(self):
        """Three caveats can be true at once and each answers a different question about the
        results; one silently winning would be the bug this whole field exists to remove."""
        state = {
            "matched": True,
            "reason": "These results may not be what you asked for.",
            "relaxations": ["ignored the position, which the detector reads least reliably"],
            "constraint": {"objects": ["motorcycle", "bus"], "unsupported_relation": "next to a bus"},
            "ranked": [],
            "scores": {},
            "top_k": 10,
        }
        with _no_corpus():
            out = await respond_node(state)
        assert "may not be what you asked for" in out["reason"]
        assert "widened" in out["reason"]
        assert "next to a bus" in out["reason"]
