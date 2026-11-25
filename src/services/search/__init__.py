"""The online query path — M2_DESIGN §3's "query" half.

Promoted from `experiments/m1/scenesearch/`, which stays where it is as the evidence trail. Each
module here names the experiment that validated it; `tests/test_services/test_fidelity.py` asserts
this path still reproduces `experiment_40095e80`'s ranking, so the two copies cannot drift silently.

What is deliberately *not* promoted: `evaluation/`, `groundtruth/`, `data/`, and the captioning
pipeline. `groundtruth/` above all — the metadata filter is scored against annotations, so a product
path that could read them would make the M2 §9 measurement circular. Ingest writes; query reads.

Re-exports are resolved lazily (PEP 562). Same names, same public API — but importing one module no
longer drags in the whole subsystem, and `filters.py` is pure stdlib precisely so that ingest can
use it. `scripts/tag_scenes.py` and `scripts/measure/measure_scene_tag_lift.py` run in the research
environment, which has the devkit and open_clip but not pydantic; eagerly importing `artifacts` here
made `from src.services.search.filters import ...` fail there on a dependency neither script uses.
"""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "Corpus": "artifacts",
    "FlatIndex": "index",
    "MetadataFilterReranker": "filters",
    "Retriever": "retriever",
    "SceneCapReranker": "diversity",
    "ensure_captions": "captions",
    "get_corpus": "artifacts",
    "metadata_constraint": "filters",
    "satisfies": "filters",
    "verify_match": "rejection",
}


def __getattr__(name: str) -> Any:
    """Import the owning module on first access. Raises AttributeError for anything unexported."""
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f"{__name__}.{_EXPORTS[name]}"), name)


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = [
    "Corpus",
    "FlatIndex",
    "MetadataFilterReranker",
    "Retriever",
    "SceneCapReranker",
    "ensure_captions",
    "get_corpus",
    "satisfies",
    "metadata_constraint",
    "verify_match",
]
