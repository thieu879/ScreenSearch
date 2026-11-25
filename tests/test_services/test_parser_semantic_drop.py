"""Issue #9 & #21: an unsupported modifier must be reported rather than silently dropped, and the
caveat must distinguish a spatial relation from a modifier.

The behaviour is unchanged; **where it lives moved on 2026-08-24**, and these tests moved with it.
`v1.6` taught the rule inside the parser's own prompt, which grew `_SYSTEM` to 10,428 characters and
made `gpt-4o-mini` repeat categories until it exhausted `max_tokens` — "a pedestrian on the right"
answered "Search is temporarily unavailable" on every attempt against the deployed key. The rule now
lives in `_MODIFIER_SYSTEM`, asked in its own small call.

Several assertions below are about what `_SYSTEM` must *not* contain. They look odd until you know
that re-adding the rule there is exactly the regression, and that it costs a live outage rather than
a wrong field. `eval/results/parser_prompt_stability.json` is the measurement.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from openai import APIError

from src.agents.nodes.search_nodes import object_relative_note
from src.services.llm import (
    _MODIFIER_SYSTEM,
    _SYSTEM,
    _CategoryCondition,
    _ParsedQuery,
    detect_unsupported_modifier,
    parse_constraint,
)

#: The parser prompt measured stable at 6/6 on the canary query, on both API keys. `v1.6` shipped
#: 10,428 and scored 0/6. Adding 226 characters to its Rules block took it back to 1/6, so the
#: margin here is small and real rather than a round number.
STABLE_PROMPT_CEILING = 8600


def test_parser_prompt_stays_at_its_measured_size() -> None:
    """A guard on the one property that was measured to break the deployed search."""
    assert len(_SYSTEM) <= STABLE_PROMPT_CEILING, (
        f"_SYSTEM is {len(_SYSTEM)} chars, over the {STABLE_PROMPT_CEILING} measured stable. "
        "Growing it is what broke v1.6 — run scripts/measure/measure_parser_stability.py against the "
        "deployed key before raising this ceiling."
    )


def test_modifier_rule_lives_in_its_own_prompt_and_not_the_parser_s() -> None:
    """The split itself. Putting these back in `_SYSTEM` reproduces the v1.6 outage."""
    assert "unsupported_relation" in _MODIFIER_SYSTEM or "null" in _MODIFIER_SYSTEM
    assert "on fire" in _MODIFIER_SYSTEM
    assert "without a helmet" in _MODIFIER_SYSTEM

    assert "on fire" not in _SYSTEM
    assert "without a helmet" not in _SYSTEM


def test_parser_still_owns_the_object_relative_case() -> None:
    """The split moved modifiers only. A dropped *position* is still the parser's own finding."""
    assert "unsupported_relation" in _SYSTEM
    assert "to the right of a bus" in _SYSTEM


def test_modifier_prompt_does_not_report_a_missing_object_category() -> None:
    """Issue #112: a filter it cannot express is not footage the archive lacks.

    The corpus holds 241 captions naming traffic cones. A caveat saying we cannot check for them
    reads to a user as "we may not have them", which is the error #112 was raised for.
    """
    assert "traffic cones" in _MODIFIER_SYSTEM
    tail = _MODIFIER_SYSTEM[_MODIFIER_SYSTEM.index("traffic cones") :]
    assert "null" in tail


@pytest.mark.asyncio
async def test_modifier_phrase_fills_unsupported_relation_when_the_parser_leaves_it_empty() -> None:
    """The point of the second call: the caveat still reaches the user."""
    parsed = _ParsedQuery(conditions=[_CategoryCondition(category="bus")], query_en="a bus on fire")
    with (
        patch("src.services.llm._parse", AsyncMock(return_value=parsed)),
        patch("src.services.llm.detect_unsupported_modifier", AsyncMock(return_value="on fire")),
    ):
        constraint = await parse_constraint("a bus on fire")

    assert constraint.unsupported_relation == "on fire"
    assert constraint.objects == ["bus"]


@pytest.mark.asyncio
async def test_a_dropped_position_outranks_a_modifier() -> None:
    """Precedence is deliberate: the parser's finding names a position we ignored, which is more
    specific than a word the vocabulary lacks. Overwriting it would tell the user less."""
    parsed = _ParsedQuery(
        conditions=[_CategoryCondition(category="motorcycle"), _CategoryCondition(category="bus")],
        unsupported_relation="to the right of a bus",
    )
    with (
        patch("src.services.llm._parse", AsyncMock(return_value=parsed)),
        patch("src.services.llm.detect_unsupported_modifier", AsyncMock(return_value="red")),
    ):
        constraint = await parse_constraint("a red motorbike to the right of a bus")

    assert constraint.unsupported_relation == "to the right of a bus"


@pytest.mark.asyncio
async def test_a_failed_modifier_check_costs_the_caveat_not_the_search() -> None:
    """Fail-soft, and the second reason the calls are separate.

    In `v1.6` this job shared the parser's request, so its failure was the search's failure. Here a
    search that returns the right frames without a caveat is plainly better than no search at all.
    `None` is what the check returns when it fails — see the test below for where that is decided.
    """
    parsed = _ParsedQuery(conditions=[_CategoryCondition(category="bus")], query_en="a bus on fire")
    with (
        patch("src.services.llm._parse", AsyncMock(return_value=parsed)),
        patch("src.services.llm.detect_unsupported_modifier", AsyncMock(return_value=None)),
    ):
        constraint = await parse_constraint("a bus on fire")

    assert constraint.objects == ["bus"]
    assert constraint.unsupported_relation is None


@pytest.mark.asyncio
async def test_detect_unsupported_modifier_swallows_an_api_failure() -> None:
    """Where the fail-soft actually lives, so the caller never sees the error."""
    failing = AsyncMock(side_effect=APIError("down", request=None, body=None))
    llm = type("_LLM", (), {"with_structured_output": lambda self, _: type("_S", (), {"ainvoke": failing})()})()
    with patch("src.services.llm.get_llm", return_value=llm):
        assert await detect_unsupported_modifier("a bus on fire") is None


def test_caveat_note_distinguishes_spatial_and_modifier_clauses() -> None:
    """object_relative_note must emit appropriate message for spatial vs attribute clauses."""
    # Empty
    assert object_relative_note({}) == ""
    assert object_relative_note({"unsupported_relation": None}) == ""
    assert object_relative_note({"unsupported_relation": ""}) == ""

    # Spatial object-to-object relation
    spatial_note = object_relative_note({"unsupported_relation": "to the right of a bus"})
    assert "places one object relative to another" in spatial_note
    assert "'to the right of a bus'" in spatial_note

    behind_note = object_relative_note({"unsupported_relation": "behind a truck"})
    assert "places one object relative to another" in behind_note

    # Unsupported attribute / modifier
    modifier_note = object_relative_note({"unsupported_relation": "on fire"})
    assert "verified automatically" in modifier_note
    assert "'on fire'" in modifier_note
    assert "places one object relative to another" not in modifier_note

    broken_note = object_relative_note({"unsupported_relation": "broken"})
    assert "verified automatically" in broken_note
    assert "'broken'" in broken_note
