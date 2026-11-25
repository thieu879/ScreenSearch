"""The out-of-scope explanation is assembled from model output, so it needs a sentence boundary.

Caught by walking the three refusal flows before the 7-12 August feedback sessions: the parser
returns a clause, and substituting it raw produced "...across time. cutting in is motion over time,
not one frame Try describing..." — which a tester reads as a broken product, not an explanation.
"""

from __future__ import annotations

import pytest

from src.agents.nodes.search_nodes import OUT_OF_SCOPE_REASON, as_sentence


@pytest.mark.parametrize(
    ("fragment", "expected"),
    [
        ("cutting in is motion over time, not one frame", "Cutting in is motion over time, not one frame."),
        ("  a lane change happens over seconds  ", "A lane change happens over seconds."),
        ("This spans multiple frames.", "This spans multiple frames."),
        ("Is this one moment?", "Is this one moment?"),
        ("", ""),
    ],
)
def test_a_model_fragment_becomes_a_sentence(fragment, expected):
    assert as_sentence(fragment) == expected


def test_the_assembled_reason_has_no_run_on():
    """The actual defect: no full stop before `Try`, which is where the two sentences collide."""
    reason = OUT_OF_SCOPE_REASON.format(why=as_sentence("cutting in is motion over time, not one frame"))
    assert "one frame. Try describing" in reason
