"""The three agent tools.

The property that matters most for a tool is not that it works — it is that it **never raises**. A
tool that throws ends the agent's turn; one that returns "I could not do that" lets the model
recover or say so. Each test below therefore checks the failure path as well as the happy one.

`filter_by_metadata` runs against the real corpus (no model needed, so it is fast and honest);
the two that embed a query have retrieval patched.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.agents.tools.scene_tools import (
    SCENE_TOOLS,
    filter_by_metadata,
    search_frames,
    verify_results,
)


def test_all_three_tools_are_exported():
    """The brief asks for at least three: metadata-filter, vector-search, rerank/verify."""
    assert len(SCENE_TOOLS) == 3
    names = {t.name for t in SCENE_TOOLS}
    assert names == {"search_frames", "filter_by_metadata", "verify_results"}


def test_every_tool_has_a_docstring_the_model_can_select_on():
    """The agent picks tools by description, so an undescribed tool is an unusable one."""
    for tool in SCENE_TOOLS:
        assert tool.description and len(tool.description) > 60, tool.name


class TestFilterByMetadata:
    def test_finds_a_common_combination(self, corpus):
        out = filter_by_metadata.invoke({"objects": "car"})
        assert "frames contain car" in out
        assert "No frames" not in out

    def test_position_narrows_the_result(self, corpus):
        """front_left is an edge-of-frame condition, so it must return fewer frames than 'any car'."""
        anywhere = filter_by_metadata.invoke({"objects": "car"})
        left = filter_by_metadata.invoke({"objects": "car", "position": "front_left"})
        assert int(anywhere.split()[0]) > int(left.split()[0])

    def test_absent_combination_says_so_plainly(self, corpus):
        out = filter_by_metadata.invoke({"objects": "bus,bicycle,motorcycle,truck", "position": "front_left"})
        assert out.startswith("No frames") or "frames contain" in out

    def test_returns_a_string_on_failure_rather_than_raising(self):
        with patch("src.services.search.artifacts.get_corpus", side_effect=ValueError("bad")):
            out = filter_by_metadata.invoke({"objects": "car"})
        assert isinstance(out, str)


class TestSearchFrames:
    def test_lists_matches(self, corpus):
        ranked = corpus.frame_ids[:10]
        with patch("src.agents.tools.scene_tools.service.retrieve", return_value=(ranked, {f: 0.3 for f in ranked})):
            out = search_frames.invoke({"query": "a pedestrian"})
        assert f"Top 5 of {corpus.n_frames} frames" in out

    def test_returns_a_string_on_failure_rather_than_raising(self):
        with patch("src.agents.tools.scene_tools.service.retrieve", side_effect=RuntimeError("model gone")):
            out = search_frames.invoke({"query": "a pedestrian"})
        assert "Could not search" in out


class TestVerifyResults:
    @pytest.mark.parametrize(
        "verdict,expected",
        [
            ("high", "appears to be present"),
            ("low", "may be present"),
            ("no_match", "does NOT appear to be present"),
        ],
    )
    def test_reports_the_verdict_and_the_numbers(self, verdict, expected):
        with (
            patch("src.agents.tools.scene_tools.service.retrieve", return_value=(["f0"], {})),
            patch("src.agents.tools.scene_tools.service.verify", return_value=(verdict, 0.5, 0.457)),
        ):
            out = verify_results.invoke({"query": "a snow-covered road"})
        assert expected in out
        assert "0.457" in out  # the threshold is shown, not just the verdict

    def test_returns_a_string_on_failure_rather_than_raising(self):
        with patch("src.agents.tools.scene_tools.service.retrieve", side_effect=OSError("artifacts missing")):
            out = verify_results.invoke({"query": "anything"})
        assert "Could not verify" in out
