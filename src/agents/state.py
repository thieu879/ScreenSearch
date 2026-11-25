"""State passed between SceneSearch graph nodes.

A TypedDict rather than a Pydantic model because LangGraph expects one. Every field is here because
some node downstream reads it — this is not a scratch space. `scores` is the one large entry (a
float per corpus frame); it is carried rather than recomputed because `rerank` and `respond` both
need it and re-running the matmul would cost more than holding it.
"""

from __future__ import annotations

from typing import TypedDict

from src.models.schemas import FrameHit


class AgentState(TypedDict, total=False):
    """Fields flow forward only; each node returns just what it changed."""

    # --- input ---
    query: str
    top_k: int

    # --- parse_query: the structured reading of the query ---
    constraint: dict

    # --- retrieve / rerank ---
    ranked: list[str]
    scores: dict[str, float]

    # --- verify: M2_DESIGN §6.1 rejection, decided on the pre-rerank ranking ---
    matched: bool
    verify_score: float
    # "high" | "low" | None. Set whenever matched — "low" means show the results *with* the caveat
    # in `reason`, never instead of them.
    confidence: str | None

    # How many displayed results meet the structured constraint. Zero means the constraint was too
    # narrow to be useful, which is what triggers relaxation — not the absence of results, since the
    # filter is a rerank and always returns a full ranking.
    satisfied_count: int

    # --- relax: how the constraint was widened, so the answer can admit it ---
    iteration: int
    relaxations: list[str]

    # --- respond ---
    results: list[FrameHit]
    distinct_scenes: int
    reason: str

    # Set by any node that fails. The router then routes straight to respond, so a failure produces
    # an honest empty answer rather than a half-built one.
    error: str

    # --- retained from the template so /chat keeps working ---
    response: str
    analysis: str
