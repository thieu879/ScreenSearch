"""`top_k`'s default is one setting, read by both entry points into the search graph.

It used to be the literal `10`, written three times: in `SearchRequest`, in the rerank node and in
the build-hits node. Nothing failed if one moved, and the frontend held a fourth copy it sent on
every request — so the number that decides both the page size *and* the diversity window
(`services/search/diversity.py`) had four owners and no single source. These tests fail if a literal
comes back, which is the only way that regression is visible: every existing test passes `top_k`
explicitly, so a drifted default is invisible to all of them.
"""

from __future__ import annotations

import pytest

from src.agents.nodes.search_nodes import _top_k
from src.config import get_settings
from src.models.schemas import SearchRequest


@pytest.fixture
def top_k_setting(monkeypatch):
    """Set `DEFAULT_TOP_K` for one test, clearing the settings cache on both sides."""

    def _set(value: int) -> int:
        monkeypatch.setenv("DEFAULT_TOP_K", str(value))
        get_settings.cache_clear()
        return value

    yield _set
    monkeypatch.delenv("DEFAULT_TOP_K", raising=False)
    get_settings.cache_clear()


def test_an_omitted_top_k_takes_the_configured_default() -> None:
    assert SearchRequest(query="a pedestrian").top_k == get_settings().default_top_k


def test_the_default_follows_the_setting_rather_than_a_literal(top_k_setting) -> None:
    """The point of the change: move the setting and the request default moves with it."""
    top_k_setting(7)
    assert SearchRequest(query="a pedestrian").top_k == 7


def test_the_graph_fallback_reads_the_same_setting(top_k_setting) -> None:
    """`/chat`, the scene tools and the measurement scripts invoke the graph without a request."""
    top_k_setting(7)
    assert _top_k({"query": "a pedestrian"}) == 7


def test_an_explicit_top_k_still_wins_on_both_paths(top_k_setting) -> None:
    top_k_setting(7)
    assert SearchRequest(query="a pedestrian", top_k=3).top_k == 3
    assert _top_k({"query": "a pedestrian", "top_k": 3}) == 3


@pytest.mark.parametrize("value", [0, 51])
def test_the_measured_bounds_are_unchanged(value: int) -> None:
    """1–50 is the contract `docs/api-contract.md` publishes; widening it is a separate decision."""
    with pytest.raises(ValueError):
        SearchRequest(query="a pedestrian", top_k=value)
