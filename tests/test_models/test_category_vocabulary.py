"""The parser may only name categories the detector can emit — issue #112.

This is the gate for an invariant that was violated silently for four days. `schemas.Category` let
the parser emit nine categories while `COCO_TO_VOCAB` mapped six, and `rejection.contradicted` read
that gap as *proof the corpus lacks them*. It does not: an unemittable class means the pipeline
cannot check, not that the footage is empty. All three orphans — `traffic_cone`, `barrier`,
`construction_vehicle` — are plainly present in the served corpus, and the product refused
`traffic cones on the road` as certainly impossible while retrieval had a photograph of a cone at
rank 1.

A comment cannot hold that invariant, because the failure it produces is invisible: adding a
category to the Literal breaks nothing, passes every other test, and starts telling users the
archive lacks footage it holds. So it is asserted here, against the mapping itself rather than
against a copied list — a second hand-written list would drift the same way the first one did.
"""

from __future__ import annotations

import os
import sys
import typing

# `COCO_TO_VOCAB` lives in the research package, which is on the path at runtime rather than
# installed — the same insert `scripts/ingest_folder.py` makes for the same reason.
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "experiments", "m1")
)

from scenesearch.metadata.extract import COCO_TO_VOCAB  # noqa: E402

from src.models.schemas import Category  # noqa: E402

PARSER = set(typing.get_args(Category))
DETECTOR = set(COCO_TO_VOCAB.values())


class TestParserCannotOutrunTheDetector:
    def test_every_parseable_category_is_emittable(self):
        """The invariant. A category the parser can name but the detector cannot emit is exactly
        what `contradicted` mistook for evidence of absence."""
        assert PARSER <= DETECTOR, (
            f"parser can name {sorted(PARSER - DETECTOR)}, which the detector cannot emit — "
            "see issue #112 before adding a category here"
        )

    def test_the_two_vocabularies_are_the_same_six(self):
        """Equality, not just containment. A detector class the parser cannot name is a capability
        nobody can reach — the mirror of #112 and the reason `traffic light` (present in 40% of
        frames, and discarded by the mapping) is worth revisiting deliberately rather than by
        accident."""
        assert PARSER == DETECTOR

    def test_the_three_orphans_are_gone(self):
        """Named explicitly so re-adding one fails loudly here rather than in a user's refusal.

        COCO has no equivalent for any of them, so no weights swap makes them emittable — both
        entries in `DETECTORS` are Faster R-CNN over the same 91 COCO classes. Re-adding one
        requires a detector that can actually see it.
        """
        assert not PARSER & {"traffic_cone", "barrier", "construction_vehicle"}
