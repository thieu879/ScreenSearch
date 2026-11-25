"""The parser prompt must define `time_of_day` by light, not by two literal words.

Issue #74 reported that `time_of_day` "only fires on the literal words day/night", leaving a
58%-night corpus unfiltered. Measured against the pre-fix prompt on 2026-08-14, that premise was
**overstated**: of six representative queries, five already parsed correctly — "in the morning",
"in the afternoon", "xe tải lúc trời nắng", "after dark", and "at dusk" (correctly null). Only
"a truck in the hot sun" returned null where it should have returned `day`.

So the value here is smaller than the issue claimed, and different in kind. The model was
generalising past the rule it was given; the rule said "ONLY if it mentions day or night", and the
correct answers were arriving in spite of it. Behaviour that is right by luck is not specified, and
nothing would notice if a later prompt edit took it away — that is what these tests hold down.

**Why prompt text rather than a parse.** Every test in this repo mocks the LLM, so a behavioural
test would assert against a fixture it wrote itself. The live check lives in the PR description:
38 calls, 0 failures, including `query_en` verbatim (9/9) and PR #78's bare-side positions, both of
which share `_SYSTEM` and are the things a change here can silently move.
"""

from __future__ import annotations

from src.services.llm import _SYSTEM

# Phrasings that state the light without using "day" or "night". "hot sun" is the one that actually
# failed; the rest were passing unspecified.
DAYLIGHT_PHRASINGS = ("morning", "afternoon", "midday", "sunny", "hot sun", "trời nắng")
DARKNESS_PHRASINGS = ("after dark", "midnight", "buổi tối", "ban đêm")

# Neither state. Null for the same reason snow is not rain — the vocabulary has two values and
# these fall between them.
BETWEEN_STATES = ("dusk", "dawn", "twilight", "sunrise", "sunset")


def _time_rule() -> str:
    """The prose rule governing `time_of_day`, up to where the examples begin."""
    rules, _, _ = _SYSTEM.partition("Examples")
    _, _, rule = rules.partition("`time_of_day` is whether the query says it is LIGHT or DARK")
    assert rule, "the time_of_day rule is no longer stated in terms of light and dark"
    return rule


def test_rule_is_defined_by_light_not_by_two_words() -> None:
    """The rule must say it is not about the literal words, or it reads as the old one."""
    rule = _time_rule()
    assert "not whether it uses the words" in rule or "not whether the query uses" in rule, (
        "the rule no longer disclaims the literal-word reading that issue #74 was filed about"
    )


def test_daylight_and_darkness_phrasings_are_named() -> None:
    """Each side lists phrasings that never say "day" or "night"."""
    rule = _time_rule()
    for phrase in DAYLIGHT_PHRASINGS + DARKNESS_PHRASINGS:
        assert phrase in rule, f"the time rule no longer names {phrase!r}"


def test_between_states_are_explicitly_null() -> None:
    """Dusk and friends are named as neither, so the model is not left to round them."""
    rule = _time_rule().lower()  # the sentence opens with "Dusk", so compare case-insensitively
    for phrase in BETWEEN_STATES:
        assert phrase in rule, f"{phrase!r} is no longer listed as neither day nor night"
    assert "null" in rule, "the rule does not say what to emit for the between states"


def test_examples_cover_a_light_phrasing_and_a_between_state() -> None:
    """The worked examples show both, since the rule alone was what the model outran before."""
    _, _, tail = _SYSTEM.partition("Examples")
    body, _, _ = tail.partition("query_en examples")
    assert "hot sun" in body and "time_of_day: day" in body, "no worked daylight example"
    assert "dusk" in body, "no worked example for a between state"


def test_sun_does_not_become_a_weather_claim() -> None:
    """Sunlight sets the time and leaves weather alone — it says nothing about the sky.

    `weather` is not in `filters.TAGGED_AXES`, so a spurious `clear` is stripped before it reaches
    the filter, but it would still surface in the API response and the UI's constraint chips as a
    condition the user never stated.
    """
    rule = _time_rule()
    assert "weather stays null" in rule, "the rule no longer keeps sunlight out of the weather axis"
