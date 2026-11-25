"""Graph wiring: routing, the relax loop, and its bounds.

Retrieval is patched out on purpose. Whether the ranking is *correct* is settled by
`tests/test_services/test_fidelity.py` against a measured experiment. What these tests own is the
part no experiment covers: that a router never names an edge that does not exist, that the loop
terminates, and that an out-of-scope query never reaches the pipeline at all.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.graph import (
    agent,
    can_relax,
    route_after_parse,
    route_after_rerank,
    route_after_verify,
)
from src.agents.nodes.search_nodes import MAX_ITERATIONS, relax_node
from src.services.search.artifacts import get_corpus

# Every value each router may return. A router emitting a name outside its edge map raises at
# runtime, deep inside a request, so the maps are asserted here rather than trusted.
PARSE_EDGES = {"retrieve", "respond"}
VERIFY_EDGES = {"rerank", "respond"}
RERANK_EDGES = {"relax", "respond"}


class TestRouting:
    @pytest.mark.parametrize(
        "state,expected",
        [
            ({"constraint": {"objects": ["car"]}}, "retrieve"),
            ({"error": "boom"}, "respond"),
            ({"constraint": {"out_of_scope": "needs motion"}}, "respond"),
            ({}, "retrieve"),
        ],
    )
    def test_route_after_parse(self, state, expected):
        assert route_after_parse(state) == expected

    @pytest.mark.parametrize(
        "state,expected",
        [
            ({"matched": True}, "rerank"),
            ({"matched": False}, "respond"),
            ({"error": "boom", "matched": True}, "respond"),
            ({}, "respond"),
        ],
    )
    def test_route_after_verify(self, state, expected):
        """Rejection ends the request. There is nothing to arrange if nothing matched."""
        assert route_after_verify(state) == expected

    @pytest.mark.parametrize(
        "state,expected",
        [
            ({"satisfied_count": 3, "iteration": 0, "constraint": {"relations": {"car": ["front"]}}}, "respond"),
            ({"satisfied_count": 0, "iteration": 0, "constraint": {"relations": {"car": ["front"]}}}, "relax"),
            ({"satisfied_count": 0, "iteration": 0, "constraint": {"objects": ["car"]}}, "respond"),
            (
                {"satisfied_count": 0, "iteration": MAX_ITERATIONS, "constraint": {"relations": {"car": ["front"]}}},
                "respond",
            ),
            ({"error": "boom", "satisfied_count": 0}, "respond"),
        ],
    )
    def test_route_after_rerank(self, state, expected):
        """Relaxation triggers on a constraint nothing satisfies — a partial match is still useful."""
        assert route_after_rerank(state) == expected

    def test_routers_only_ever_name_mapped_edges(self):
        """The failure mode conditional edges actually have: a name with no edge behind it."""
        states = [
            {},
            {"error": "x"},
            {"matched": True},
            {"matched": False, "iteration": 0},
            {"constraint": {"out_of_scope": "y"}},
            {"constraint": {"objects": ["a", "b"]}},
            {"satisfied_count": 0, "iteration": 0},
            {"satisfied_count": 5},
            {"matched": False, "iteration": 99, "constraint": {"relations": {"c": ["front"]}}},
        ]
        assert {route_after_parse(s) for s in states} <= PARSE_EDGES
        assert {route_after_verify(s) for s in states} <= VERIFY_EDGES
        assert {route_after_rerank(s) for s in states} <= RERANK_EDGES


class TestRelaxation:
    def test_nothing_to_relax(self):
        assert can_relax(None) is False
        assert can_relax({}) is False
        assert can_relax({"objects": ["car"]}) is False

    def test_relaxable_while_a_condition_remains(self):
        assert can_relax({"relations": {"car": ["front_left"]}}) is True
        assert can_relax({"objects": ["car", "pedestrian"]}) is True

    @pytest.mark.asyncio
    async def test_position_is_given_up_before_objects(self):
        """Positions go first: edge-of-frame conditions with detector recall 0.32-0.72, against
        0.97 for car presence. The weakest evidence is surrendered first."""
        state = {"constraint": {"objects": ["car", "pedestrian"], "relations": {"car": ["front_left"]}}, "iteration": 0}
        out = await relax_node(state)
        assert out["constraint"]["relations"] == {}
        assert out["constraint"]["objects"] == ["car", "pedestrian"]
        assert out["iteration"] == 1

        out2 = await relax_node({**state, "constraint": out["constraint"], "iteration": 1})
        assert out2["constraint"]["objects"] == ["car"]

    @pytest.mark.asyncio
    async def test_relaxation_is_recorded_for_the_user(self):
        out = await relax_node({"constraint": {"relations": {"car": ["front"]}}, "iteration": 0})
        assert out["relaxations"] and "position" in out["relaxations"][0]


class TestGraphExecution:
    @pytest.mark.asyncio
    async def test_out_of_scope_query_never_reaches_retrieval(self, parsed_constraint):
        """A temporal query must be explained, not answered with ten confident frames."""
        with (
            parsed_constraint(out_of_scope="it needs motion across frames"),
            patch("src.agents.nodes.search_nodes.service.retrieve") as retrieve,
        ):
            state = await agent.ainvoke({"query": "a vehicle cutting into our lane", "top_k": 10})
        retrieve.assert_not_called()
        assert state["matched"] is False
        assert state["results"] == []
        assert "single frames" in state["reason"]

    @pytest.mark.asyncio
    async def test_match_returns_hits_and_scene_count(self, parsed_constraint):
        ranked = [f"f{i}" for i in range(20)]
        with (
            parsed_constraint(objects=["pedestrian"]),
            patch("src.agents.nodes.search_nodes.service.retrieve", return_value=(ranked, {f: 0.3 for f in ranked})),
            patch("src.agents.nodes.search_nodes.service.rerank_candidates", return_value=ranked),
            patch("src.agents.nodes.search_nodes.service.count_satisfying", return_value=7),
            patch("src.agents.nodes.search_nodes.service.verify", return_value=("high", 0.6, 0.457)),
            patch("src.agents.nodes.search_nodes.service.build_hits", return_value=["hit"]),
            patch("src.agents.nodes.search_nodes.service.count_distinct_scenes", return_value=6),
            patch("src.agents.nodes.search_nodes.get_corpus"),
        ):
            state = await agent.ainvoke({"query": "a pedestrian", "top_k": 10})
        assert state["matched"] is True
        assert state["distinct_scenes"] == 6

    @pytest.mark.asyncio
    async def test_rejection_short_circuits_before_reranking(self, parsed_constraint):
        """§6.1: when nothing matches, there is nothing to arrange. Reranking must not run.

        This also pins the ordering fix — verify decides on the retrieval ranking, so a rejected
        query never reaches the reranker at all.
        """
        ranked = ["f0", "f1"]
        with (
            parsed_constraint(objects=["car"], relations={"car": ["front_left"]}),
            patch("src.agents.nodes.search_nodes.service.retrieve", return_value=(ranked, {"f0": 0.1, "f1": 0.1})),
            patch("src.agents.nodes.search_nodes.service.rerank_candidates") as rerank,
            patch("src.agents.nodes.search_nodes.service.verify", return_value=("no_match", 0.2, 0.457)),
        ):
            state = await agent.ainvoke({"query": "a snow-covered road", "top_k": 10})
        rerank.assert_not_called()
        assert state["matched"] is False
        assert state["results"] == []
        # The archive is described, not just refused — with the size read from provenance, since
        # the literal this replaced kept passing while the message went stale by 17×.
        assert f"{get_corpus().provenance['n_frames']:,} keyframes" in state["reason"]

    @pytest.mark.asyncio
    async def test_unsatisfiable_constraint_is_relaxed_then_answered(self, parsed_constraint):
        """A match whose constraint nothing satisfies gets widened, once, and then answered."""
        ranked = ["f0", "f1"]
        with (
            parsed_constraint(objects=["car"], relations={"car": ["front_left"]}),
            patch("src.agents.nodes.search_nodes.service.retrieve", return_value=(ranked, {"f0": 0.5, "f1": 0.5})),
            patch("src.agents.nodes.search_nodes.service.rerank_candidates", return_value=ranked) as rerank,
            patch("src.agents.nodes.search_nodes.service.count_satisfying", return_value=0),
            patch("src.agents.nodes.search_nodes.service.verify", return_value=("high", 0.6, 0.457)),
            patch("src.agents.nodes.search_nodes.service.build_hits", return_value=["hit"]),
            patch("src.agents.nodes.search_nodes.service.count_distinct_scenes", return_value=4),
            patch("src.agents.nodes.search_nodes.get_corpus"),
        ):
            state = await agent.ainvoke({"query": "a car to the front-left", "top_k": 10})
        # relations dropped, then nothing left to give up: exactly one retry, not MAX_ITERATIONS
        assert rerank.call_count == 2
        assert state["matched"] is True
        assert "position" in state["reason"]  # the widening is admitted to the user

    @pytest.mark.asyncio
    async def test_low_confidence_shows_results_with_a_caveat_not_instead_of_them(self, parsed_constraint):
        """The whole point of the band: a marginal score must never hide real results.

        A wrongly shown frame is self-correcting — the user looks and rephrases. A wrongly hidden
        one is invisible: they conclude the archive lacks footage it holds and stop looking.
        """
        ranked = [f"f{i}" for i in range(20)]
        with (
            parsed_constraint(objects=["pedestrian"]),
            patch("src.agents.nodes.search_nodes.service.retrieve", return_value=(ranked, {f: 0.3 for f in ranked})),
            patch("src.agents.nodes.search_nodes.service.rerank_candidates", return_value=ranked),
            patch("src.agents.nodes.search_nodes.service.count_satisfying", return_value=4),
            patch("src.agents.nodes.search_nodes.service.verify", return_value=("low", 0.40, 0.457)),
            patch("src.agents.nodes.search_nodes.service.build_hits", return_value=["hit"]),
            patch("src.agents.nodes.search_nodes.service.count_distinct_scenes", return_value=5),
            patch("src.agents.nodes.search_nodes.get_corpus"),
        ):
            state = await agent.ainvoke({"query": "a pedestrian", "top_k": 10})
        assert state["matched"] is True
        assert state["confidence"] == "low"
        assert state["results"] == ["hit"]  # shown, not withheld
        assert "may not be what you asked for" in state["reason"]

    @pytest.mark.asyncio
    async def test_both_caveats_survive_together(self, parsed_constraint):
        """Low confidence AND a widened constraint are two different warnings; neither may
        overwrite the other, because the user needs both to judge what they are looking at."""
        ranked = ["f0", "f1"]
        with (
            parsed_constraint(objects=["car"], relations={"car": ["front_left"]}),
            patch("src.agents.nodes.search_nodes.service.retrieve", return_value=(ranked, {"f0": 0.4, "f1": 0.4})),
            patch("src.agents.nodes.search_nodes.service.rerank_candidates", return_value=ranked),
            patch("src.agents.nodes.search_nodes.service.count_satisfying", return_value=0),
            patch("src.agents.nodes.search_nodes.service.verify", return_value=("low", 0.40, 0.457)),
            patch("src.agents.nodes.search_nodes.service.build_hits", return_value=["hit"]),
            patch("src.agents.nodes.search_nodes.service.count_distinct_scenes", return_value=2),
            patch("src.agents.nodes.search_nodes.get_corpus"),
        ):
            state = await agent.ainvoke({"query": "a car to the front-left", "top_k": 10})
        assert "may not be what you asked for" in state["reason"]
        assert "widened" in state["reason"]

    @pytest.mark.asyncio
    async def test_parse_failure_degrades_to_an_apology_not_a_crash(self):
        with patch(
            "src.agents.nodes.search_nodes.parse_constraint", AsyncMock(side_effect=RuntimeError("openai down"))
        ):
            state = await agent.ainvoke({"query": "anything", "top_k": 10})
        assert state["results"] == []
        assert "unavailable" in state["reason"]
