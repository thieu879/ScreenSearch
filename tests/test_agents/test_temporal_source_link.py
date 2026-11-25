"""A motion query stops being a dead end on a corpus that kept its source footage.

`llm.py` sets `out_of_scope` because **one frame** cannot show motion. That claim is about the
frame and it is still true — nothing here weakens it. What changes is that a corpus with a
`videos.json` can hand the user the second of video the frame came from, so the branch retrieves
and the answer becomes "the closest moments, unconfirmed, and here is where to check" instead of
"try a different query".

**The nuScenes half is the regression guard and it comes first.** The served corpus pruned its
source blobs after extraction, so it can never carry a manifest and must keep refusing exactly as it
did. These tests fail if that behaviour is ever reached by accident.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.agents.graph import route_after_parse
from src.agents.nodes.search_nodes import (
    OUT_OF_SCOPE_REASON,
    TEMPORAL_CAVEAT,
    TEMPORAL_SOURCE_NOTE,
    respond_node,
)
from src.models.schemas import FrameHit, SourceClip
from src.services.search.videos import VideoManifest

WHY = "cutting in is motion over time, not one frame"
CUT_IN = {"objects": ["motorcycle"], "out_of_scope": WHY}
LINKABLE = VideoManifest({"clip01_hanoi": {"webpage_url": "https://www.youtube.com/watch?v=x"}})

HIT = FrameHit(
    frame_id="f1",
    scene_id="clip01_hanoi#0000",
    timestamp_s=257.4,
    score=0.1,
    thumb_url="/api/v1/frames/f1/thumb",
    source=SourceClip(url="https://www.youtube.com/watch?v=x&t=257"),
)


WHY_SENTENCE = "Cutting in is motion over time, not one frame."


class TestACorpusWithNoFootageStillRefuses:
    """The served corpus. Unchanged behaviour, asserted so a later edit cannot quietly move it."""

    def test_an_out_of_scope_query_never_reaches_retrieval(self):
        with patch("src.agents.graph.get_manifest", lambda: VideoManifest()):
            assert route_after_parse({"constraint": CUT_IN}) == "respond"

    @pytest.mark.asyncio
    async def test_the_refusal_is_the_one_it_has_always_been(self):
        with patch("src.agents.nodes.search_nodes.get_manifest", lambda: VideoManifest()):
            out = await respond_node({"constraint": CUT_IN, "matched": True, "ranked": ["f1"]})
        assert out["results"] == []
        assert out["matched"] is False
        assert out["reason"] == OUT_OF_SCOPE_REASON.format(why=WHY_SENTENCE)


class TestACorpusWithFootageAnswers:
    def test_an_out_of_scope_query_is_retrieved_for(self):
        with patch("src.agents.graph.get_manifest", lambda: LINKABLE):
            assert route_after_parse({"constraint": CUT_IN}) == "retrieve"

    def test_an_error_still_short_circuits_whatever_the_corpus_holds(self):
        """The manifest may not resurrect a request that already failed."""
        with patch("src.agents.graph.get_manifest", lambda: LINKABLE):
            assert route_after_parse({"error": "boom", "constraint": CUT_IN}) == "respond"

    @pytest.mark.asyncio
    async def test_the_results_lead_with_the_caveat_and_carry_the_links(self):
        with (
            patch("src.agents.nodes.search_nodes.get_manifest", lambda: LINKABLE),
            patch("src.services.search.service.build_hits", return_value=[HIT]),
            patch("src.services.search.service.count_distinct_scenes", return_value=1),
        ):
            out = await respond_node({"constraint": CUT_IN, "matched": True, "ranked": ["f1"], "reason": ""})
        assert out["results"] == [HIT]
        assert out["reason"] == TEMPORAL_SOURCE_NOTE.format(why=WHY_SENTENCE)
        assert "links to the source video at that second" in out["reason"]
        assert out["results"][0].source.url.endswith("&t=257")

    @pytest.mark.asyncio
    async def test_the_caveat_does_not_displace_the_low_confidence_note(self):
        """Both are true at once and the user needs both. Measured on Hanoi, motion queries land
        `low` five times in six (0.35-0.51 against `tau_confident` 0.50), so this is the usual case,
        not an edge one."""
        low = "Nothing here matches closely."
        with (
            patch("src.agents.nodes.search_nodes.get_manifest", lambda: LINKABLE),
            patch("src.services.search.service.build_hits", return_value=[HIT]),
            patch("src.services.search.service.count_distinct_scenes", return_value=1),
        ):
            out = await respond_node({"constraint": CUT_IN, "matched": True, "ranked": ["f1"], "reason": low})
        assert "cannot confirm the movement itself" in out["reason"]
        assert low in out["reason"]

    @pytest.mark.asyncio
    async def test_a_refused_motion_query_is_not_refused_as_a_missing_object(self):
        """If the caption gate does reject one, the answer must still say *why* single frames fall
        short — otherwise "the archive holds nothing like this" reads as "no motorbikes", which on
        this corpus would be flatly false. The #112 shape, arrived at from the other direction."""
        with patch("src.agents.nodes.search_nodes.get_manifest", lambda: LINKABLE):
            out = await respond_node(
                {"constraint": CUT_IN, "matched": False, "reason": "Nothing in the archive matches."}
            )
        assert out["results"] == []
        assert out["reason"].startswith(TEMPORAL_CAVEAT.format(why=WHY_SENTENCE))
        assert "Nothing in the archive matches." in out["reason"]

    @pytest.mark.asyncio
    async def test_an_ordinary_query_gains_nothing(self):
        """The caveat is attached to `out_of_scope`, not to the corpus. A static query on a linkable
        corpus reads exactly as it does today — the links ride the hits, the prose does not change."""
        with (
            patch("src.agents.nodes.search_nodes.get_manifest", lambda: LINKABLE),
            patch("src.services.search.service.build_hits", return_value=[HIT]),
            patch("src.services.search.service.count_distinct_scenes", return_value=1),
        ):
            out = await respond_node({"constraint": {"objects": ["motorcycle"]}, "matched": True, "ranked": ["f1"]})
        assert "cannot confirm the movement" not in out["reason"]
