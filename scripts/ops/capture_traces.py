"""Produce the LangSmith traces for Demo Day deliverable #4.

The rubric asks for **5-10 traces**, each showing input → LLM call → retrieval → final output.
LangGraph instruments every node, so one run of the agent produces exactly that shape: `parse`
(the LLM call), `retrieve`, `verify`, `rerank`, `respond`, nested under one trace per query.

The eight queries below are not arbitrary — they are chosen so the traces *together* demonstrate
every behaviour the system has, including the ones that are easy to miss in a live demo because
nothing visible happens:

    high confidence      the ordinary case
    low confidence       answered but flagged — the band, not a binary
    no match             the archive genuinely lacks it
    out of scope         a single frame cannot answer it, so it is not attempted
    relaxation           the constraint was too narrow and got widened, visibly

Setup — a free LangSmith account, then in `.env`:

    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=lsv2_...
    LANGSMITH_PROJECT=scenesearch

Then:

    python scripts/ops/capture_traces.py

Afterwards the traces must be made public, or they cannot be graded. **LangSmith has no
project-level sharing** — there is no "make this project public" setting, only per-run sharing —
so each root trace gets its own link:

    from langsmith import Client
    c = Client(api_key=...)
    for r in c.list_runs(project_name=..., is_root=True):
        print(c.share_run(r.id))       # -> https://smith.langchain.com/public/<token>/r

Put those links in `README.md` (§ Agent traces). Reverse with `Client.unshare_run(run_id)`.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

# One level deeper than a top-level script, so the repo root counts three. `scripts/` must be
# added explicitly: running this file puts `scripts/ops/` on sys.path[0], not `scripts/`.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

# Windows consoles default to cp1252, which has no "↳". Printing one raised UnicodeEncodeError
# *after* the first trace had already been sent — so the run died half-finished, leaving LangSmith
# holding a partial set that looks like a complete one. Reconfiguring beats replacing the character:
# the next non-ASCII glyph anyone adds would otherwise reintroduce the same crash.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (query, what this trace is here to show)
QUERIES: list[tuple[str, str]] = [
    ("a wet road at night", "high confidence — the ordinary path, scene conditions parsed from language"),
    (
        "a pedestrian to the front-left",
        "spatial: the metadata filter's headline case, returned with a low-confidence caveat",
    ),
    ("a car to the front-left", "the query no image embedding can answer — cars are in 5,187 of 6,858 frames (76%)"),
    ("a bus at night", "multi-condition: an object and a scene condition together"),
    ("traffic cones on the road", "single concept, an uncommon object"),
    ("a parked car to the front-right", "object + position + attribute — the fullest constraint the parser can build"),
    ("a bus on fire", "REJECTED: every noun is present in the archive, the situation is not"),
    ("a vehicle cutting into our lane", "OUT OF SCOPE: motion over time, so retrieval is never attempted"),
]


def share_recent(project: str, api_key: str, limit: int) -> None:
    """Make the most recent root traces public and print their links.

    A mode rather than a documented snippet because it has to be re-run every time the traces are
    regenerated — a new corpus means new runs, and the old links still resolve to traces measured
    over a corpus that no longer ships, which is worse than no links.

    LangSmith has no project-level sharing. There is no "make this project public" setting, only
    `share_run` per root run, so the deliverable is N links rather than one.
    """
    from langsmith import Client

    client = Client(api_key=api_key)
    runs = list(client.list_runs(project_name=project, is_root=True, limit=limit))
    if not runs:
        sys.exit(f"no root runs in project {project!r} — capture some first")
    print(f"{len(runs)} traces, newest first:\n")
    for run in runs:
        query = (run.inputs or {}).get("query", "?")
        print(f"- `{query}` — [trace]({client.share_run(run.id)})")
    print("\nPaste into README.md § Agent traces. Reverse with Client.unshare_run(run_id).")


async def main() -> None:
    from src.config import get_settings

    settings = get_settings()
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        sys.exit(
            "LangSmith is off. Set LANGSMITH_TRACING=true and LANGSMITH_API_KEY in .env first —\n"
            "without them this runs the queries and records nothing."
        )
    # src.main sets the LANGCHAIN_* variables LangChain actually reads, from settings.
    from src.main import _configure_tracing

    _configure_tracing()

    from src.agents.graph import agent
    from src.services.search.encoder import warmup

    print(f"project: {settings.langsmith_project}\nwarming encoders…")
    warmup()

    print(f"\n{'query':38}{'outcome':22}{'hits':>5}{'clips':>7}{'ms':>8}")
    for query, why in QUERIES:
        t0 = time.perf_counter()
        state = await agent.ainvoke({"query": query, "top_k": 10})
        dt = (time.perf_counter() - t0) * 1000
        if (state.get("constraint") or {}).get("out_of_scope"):
            outcome = "out of scope"
        elif not state.get("matched"):
            outcome = "no match"
        else:
            outcome = f"matched ({state.get('confidence')})"
        print(
            f"{query[:36]:38}{outcome:22}{len(state.get('results', [])):5}{state.get('distinct_scenes', 0):7}{dt:8.0f}"
        )
        print(f"    ↳ {why}")

    print(f"\n{len(QUERIES)} traces sent to LangSmith.")
    # Not "make the project public": there is no such setting. LangSmith shares per *run*, and the
    # instruction to look for a project-level toggle sent someone hunting through Settings for a
    # control that does not exist. `--share` below does the per-run sharing this actually needs.
    print("Now: python scripts/ops/capture_traces.py --share   (per-run links for README.md)")


if __name__ == "__main__":
    if "--share" in sys.argv:
        from src.config import get_settings as _get

        _s = _get()
        if not _s.langsmith_api_key:
            sys.exit("LANGSMITH_API_KEY is not set — nothing to share")
        share_recent(_s.langsmith_project, _s.langsmith_api_key, len(QUERIES))
    else:
        asyncio.run(main())
