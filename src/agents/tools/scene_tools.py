"""Agent tools over the SceneSearch corpus.

Each wraps a stage the graph runs deterministically, exposed so a model can invoke it directly for
exploratory questions ("is there any night footage with a bus?") without going through the fixed
pipeline. The graph does **not** route through these — its ordering is load-bearing and measured,
and letting a model choose whether to filter before diversifying would discard the reason that order
exists (see `services/search/retriever.py`).

Tool conventions: full type hints, a docstring the model selects on, a **string** return, and errors
handled inside — a tool that raises ends the agent turn, while a tool that returns "I could not do
that" lets it recover.
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from src.config import get_settings
from src.services.search import service
from src.services.search.artifacts import get_corpus

logger = logging.getLogger(__name__)

MAX_LISTED = 5


@tool
def search_frames(query: str) -> str:
    """Search the driving-footage archive for frames matching a natural-language description.

    Use for any question about what footage exists, e.g. "a bus at night" or "traffic cones".
    Returns the best-matching frames with their clip and timestamp.

    Args:
        query: What to look for, in plain English.

    Returns:
        A short list of matching frames, or a note that nothing matched.
    """
    try:
        ranked, scores = service.retrieve(query)
        corpus = get_corpus()
        lines = [
            f"{fid[:8]}… clip {corpus.scene_of.get(fid, '?')[:8]}… "
            f"t={corpus.timestamp_of.get(fid, 0):.1f}s score={scores.get(fid, 0):.3f}"
            for fid in ranked[:MAX_LISTED]
        ]
        return f"Top {len(lines)} of {corpus.n_frames} frames:\n" + "\n".join(lines)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.exception("search_frames failed")
        return f"Could not search the archive: {exc}"


@tool
def filter_by_metadata(objects: str, position: str = "") -> str:
    """Count frames whose DETECTED contents match an object and optional position.

    Facts come from an object detector run over the pixels, never from dataset annotations, so this
    reports what is actually visible. Use it to check whether a combination exists at all before
    claiming it does.

    Args:
        objects: Comma-separated categories — pedestrian, car, truck, bus, bicycle, motorcycle.
            These six are what the detector can emit; anything else is invisible to this tool.
        position: Optional, one of front, front_left, front_right — the outer thirds of the picture
            and everything between them. This was an edge-of-frame condition until 2026-08-20, when
            the band was re-cut on image position against a human review; the detector still reads a
            position less reliably than it reads presence.

    Returns:
        How many frames satisfy the combination, with examples.
    """
    try:
        cats = [c.strip() for c in objects.split(",") if c.strip()]
        constraint = {"objects": cats, "relations": {c: [position.strip()] for c in cats} if position.strip() else {}}
        corpus = get_corpus()
        from src.services.search.filters import satisfies

        hits = [f for f, m in corpus.metadata_of.items() if satisfies(m, constraint)]
        if not hits:
            return f"No frames contain {objects}" + (f" at {position}." if position else ".")
        shown = ", ".join(f[:8] + "…" for f in hits[:MAX_LISTED])
        return (
            f"{len(hits)} of {corpus.n_frames} frames contain {objects}"
            + (f" at {position}" if position else "")
            + f". Examples: {shown}"
        )
    except (KeyError, ValueError) as exc:
        logger.exception("filter_by_metadata failed")
        return f"Could not apply that filter: {exc}"


@tool
def verify_results(query: str) -> str:
    """Check whether the archive genuinely contains something, before promising it does.

    Compares the query against captions of the best-matching frames. Use this when a query might
    describe footage that was never recorded — the archive is a fixed set of driving clips from
    one place and period, so whole categories of scene are absent however plausible they sound.

    Deliberately names no place, period or count. The agent reads this docstring verbatim to choose
    tools, so anything specific here cannot be read from provenance and would go stale silently.
    The counts did exactly that in `rejection_reason`; the place outlived them and was still
    claiming Boston and Singapore on 2026-08-25, over a corpus of Hanoi footage. The tool's
    decision depends on none of it.

    Args:
        query: The scenario to check for.

    Returns:
        Whether the archive appears to contain it, and how confidently.
    """
    try:
        ranked, _ = service.retrieve(query)
        verdict, score, tau = service.verify(query, ranked)
        phrasing = {
            "high": "appears to be present",
            "low": "may be present, but could not be confirmed",
            "no_match": "does NOT appear to be present",
        }[verdict]
        return (
            f"'{query}' {phrasing} in the archive "
            f"(caption match {score:.3f} against a {tau:.3f} threshold, "
            f"judged over the top {get_settings().verify_top_k} frames)."
        )
    except (OSError, ValueError, RuntimeError) as exc:
        logger.exception("verify_results failed")
        return f"Could not verify that: {exc}"


SCENE_TOOLS = [search_frames, filter_by_metadata, verify_results]
