"""The parser prompt must describe "left" and "right" identically.

Found in the UI on 2026-08-13: `a truck to the left` came back with trucks scattered across the
frame, and the reason was not the band's calibration — the band was never consulted. The parser
classified the bare phrase "to the left" as *object*-relative, set `unsupported_relation`, and
dropped the position. `a truck to the right` parsed correctly in the same session, twice.

The cause was in the prompt, not the model. The rule sentence stated the bare-frame case using only
"right" ("`to the right` on its own is about the frame"), and every worked example did the same. The
sole `left` examples were hyphenated (`to the front-left`) or Vietnamese. With no example of a bare
`left`, the model fell through to the object-relative branch — reasonably, on what it was shown.

**Why these assert on prompt text rather than on a parse.** Every test in this repo mocks the LLM,
so a behavioural test would assert against a fixture the test itself wrote and would have stayed
green throughout the bug. The defect was an asymmetry in a string; this is a test on that string.
It cannot prove the model parses `left` correctly — only that we no longer *document* the two sides
differently, which is the regression that actually happened and the one a future edit can repeat.
"""

from __future__ import annotations

import re

from src.services.llm import _SYSTEM

# The four bare phrasings a user actually types. "front-left"/"front-right" are excluded: they were
# never the broken case, because the position word is in the phrase itself.
BARE_SIDE_PHRASINGS = ("to the left", "to the right", "on the left", "on the right")


def _example_lines() -> list[str]:
    """Lines of the prompt's `Examples:` block, where the worked parses live."""
    _, _, tail = _SYSTEM.partition("Examples")
    body, _, _ = tail.partition("query_en examples")
    return [line.strip() for line in body.splitlines() if "->" in line or "conditions:" in line]


def test_every_bare_side_phrasing_has_a_worked_example() -> None:
    """Each of the four bare phrasings maps to a position somewhere in the examples.

    This is the assertion that fails on the original prompt: "to the right" and "on the right" would
    pass, both `left` forms would not.
    """
    joined = "\n".join(_example_lines())
    for phrasing in BARE_SIDE_PHRASINGS:
        side = "front_left" if "left" in phrasing else "front_right"
        # The example and its position land on the same line, or on the line wrapped beneath it.
        hit = re.search(rf'"[^"]*{re.escape(phrasing)}"[^\n]*(?:\n[^\n]*)?{side}', joined)
        assert hit, f"no example maps the bare phrasing {phrasing!r} to {side}"


def test_bare_side_examples_never_drop_the_position() -> None:
    """A bare side phrasing must not be shown setting `unsupported_relation`.

    The object-relative examples are "... of a bus" / "... of a car". If an example ever pairs a
    *bare* side with a dropped position, the prompt is teaching the exact confusion this fixes.
    """
    for line in _example_lines():
        if "unsupported_relation" not in line:
            continue
        quoted = re.findall(r'"([^"]*)"', line)
        for text in quoted:
            for phrasing in BARE_SIDE_PHRASINGS:
                if phrasing in text and " of " not in text:
                    raise AssertionError(f"bare phrasing {text!r} shown as an unsupported relation")


def test_rule_text_names_both_sides_as_frame_relative() -> None:
    """The prose rule states the frame-relative case for left and right, not just right."""
    rule, _, _ = _SYSTEM.partition("Examples")
    _, _, frame_rule = rule.partition("A position is where something sits in the FRAME")
    assert "to the left" in frame_rule, "the FRAME rule does not mention 'to the left'"
    assert "to the right" in frame_rule, "the FRAME rule does not mention 'to the right'"


def test_object_relative_examples_exist_for_both_sides() -> None:
    """Both sides are shown being dropped, so neither side is the one with only half a story."""
    joined = "\n".join(_example_lines())
    assert re.search(r'"[^"]*to the left of [^"]*"', joined), "no left-side object-relative example"
    assert re.search(r'"[^"]*to the right of [^"]*"', joined), "no right-side object-relative example"
