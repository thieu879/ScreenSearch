"""The parse retries a length-capped response, and only that.

**This is the one failure the suite could not previously see.** `testing.md` requires the LLM to be
mocked, which is right — but a mock cannot degenerate, so the `v1.6` outage passed 465 tests while
every spatial search on the box answered "Search is temporarily unavailable". The residue of that
failure is still live: measured in-container against the deployed key on 2026-08-31,
`a pedestrian to the front-left` parsed 18/20 with 2 `LengthFinishReasonError`, while six canary
queries went 60/60. So it is one query *shape*, at roughly 10%, not the parser at large.

What a mock *can* test is the control flow around the failure, which is what these do: that a
stochastic length error is retried, that a deterministic error is not, and that giving up still
raises so the responder can be honest rather than inventing an empty constraint.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from openai import APIError, LengthFinishReasonError

from src.services import llm


def length_error() -> LengthFinishReasonError:
    """The real exception, constructed the way the SDK raises it.

    Built rather than faked with a bare `Exception`, because the whole behaviour under test is that
    *this* type is singled out from every other `OpenAIError`.
    """
    return LengthFinishReasonError.__new__(LengthFinishReasonError)


def parsed() -> llm._ParsedQuery:
    return llm._ParsedQuery(conditions=[], query_en="a pedestrian to the front-left")


@pytest.mark.asyncio
async def test_a_length_capped_parse_is_retried_and_succeeds():
    """The point of the change: the same query at temperature 0 can succeed on a later attempt."""
    ok = parsed()
    ainvoke = AsyncMock(side_effect=[length_error(), ok])
    with patch.object(llm, "get_llm") as get:
        get.return_value.with_structured_output.return_value.ainvoke = ainvoke
        assert await llm._parse("a pedestrian to the front-left") is ok
    assert ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_it_gives_up_rather_than_retrying_forever():
    """Three attempts, then raise — so `search_nodes` still reports the honest failure.

    Swallowing it would be worse than the error: the search would answer with a constraint nobody
    parsed, which is the silent-wrong-answer failure this product exists to avoid.
    """
    ainvoke = AsyncMock(side_effect=[length_error() for _ in range(llm._PARSE_RETRIES + 1)])
    with patch.object(llm, "get_llm") as get:
        get.return_value.with_structured_output.return_value.ainvoke = ainvoke
        with pytest.raises(LengthFinishReasonError):
            await llm._parse("a pedestrian to the front-left")
    assert ainvoke.await_count == llm._PARSE_RETRIES + 1


@pytest.mark.asyncio
async def test_a_deterministic_error_is_not_retried():
    """Retrying an auth failure or a bad request turns one clear error into three slow ones.

    Only `LengthFinishReasonError` is known to be non-deterministic here; everything else would
    repeat identically, so the narrowness of the `except` is the design, not an oversight.
    """
    ainvoke = AsyncMock(side_effect=APIError("boom", request=None, body=None))
    with patch.object(llm, "get_llm") as get:
        get.return_value.with_structured_output.return_value.ainvoke = ainvoke
        with pytest.raises(APIError):
            await llm._parse("a pedestrian to the front-left")
    assert ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_the_common_path_still_costs_one_call():
    """~90% of this query and 100% of the canaries parse first time; they must not pay for the retry."""
    ainvoke = AsyncMock(return_value=parsed())
    with patch.object(llm, "get_llm") as get:
        get.return_value.with_structured_output.return_value.ainvoke = ainvoke
        await llm._parse("a bus at night")
    assert ainvoke.await_count == 1
