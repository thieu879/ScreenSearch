"""Mirror a promoted corpus into the PostgreSQL ``frames`` table.

The artifacts under ``data/artifacts/`` stay the corpus of record. This script copies them into
Postgres so the admin dashboard, the ``reviews`` foreign key and any future SQL-side filtering see
the same frames the search path holds in memory. **It does not change how search works** —
``services/search/artifacts.py`` still reads the ``.npy`` files at startup, and the rejection band
is still fitted against those.

Alignment is not re-derived here. The rows come out of ``Corpus.load`` — the same call the service
makes — so a misalignment this script could introduce is one the service would already have refused
to start with. That matters more than it sounds: ``vectors.npy`` is row-aligned to ``frames.jsonl``
by position only, and a silent off-by-one would give every frame a confident score for a different
picture.

Usage::

    python scripts/ops/load_frames_to_db.py                       # nuScenes, from data/artifacts
    python scripts/ops/load_frames_to_db.py --dry-run             # build every row, write nothing
    python scripts/ops/load_frames_to_db.py --corpus hanoi --artifacts data/staging/hanoi/artifacts

Re-running is safe: rows are upserted on ``frame_id`` inside one transaction, so a dropped
connection leaves the table as it was rather than half-loaded.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np
import psycopg2

# One level deeper than a top-level script, so the repo root counts three. `scripts/` must be
# added explicitly: running this file puts `scripts/ops/` on sys.path[0], not `scripts/`.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from fetch_assets import REPO_ID, REVISION  # noqa: E402 -- single source of truth for the pin

from src.config import get_settings  # noqa: E402
from src.services.search.artifacts import Corpus  # noqa: E402

#: Column order shared by the CSV, the COPY and the upsert. One tuple, so the three cannot drift.
COLUMNS = (
    "frame_id",
    "corpus",
    "scene_id",
    "video_id",
    "timestamp_sec",
    "frame_path",
    "image_url",
    "image_vector",
    "caption_vector",
    "detection_metadata",
    "captions",
    "version_id",
)

#: Keys of a metadata record that are not detection metadata — ``frame_id`` is already the row key.
_NOT_DETECTION = {"frame_id"}


@dataclass(frozen=True)
class Options:
    """One load's parameters, so the row builder stays inside the three-argument rule."""

    artifacts: str
    corpus: str
    image_base: str
    batch: int
    dry_run: bool


def _vector_literal(row: np.ndarray) -> str:
    """A pgvector text literal for one embedding row.

    ``%.9g`` because that is the shortest decimal form that round-trips float32 exactly. A coarser
    format would perturb every score slightly, and this project's thresholds (0.30 / 0.50, fitted
    with a 0.035 margin) are tight enough that "slightly" is not obviously free.
    """
    return "[" + ",".join(f"{x:.9g}" for x in row.tolist()) + "]"


def _video_of(artifacts: str) -> dict[str, str]:
    """``frame_id`` -> ``video_id``, read from ``frames.jsonl``.

    ``Corpus`` does not carry it, having no use for it at query time. It matters here because on
    nuScenes a clip *is* a scene and the two ids are equal, while on Hanoi 24 videos hold 384 scene
    groups — so taking one for the other flattens exactly the corpus that needs the distinction.
    """
    with open(os.path.join(artifacts, "frames.jsonl"), encoding="utf-8") as f:
        return {r["frame_id"]: r.get("video_id") for r in (json.loads(x) for x in f if x.strip())}


def _rows(corpus: Corpus, opts: Options, version_id: str) -> Iterator[list[Any]]:
    """Yield one CSV row per frame, in ``COLUMNS`` order and in artifact row order."""
    video_of = _video_of(opts.artifacts)
    # Thumbnails sit beside the artifacts on both corpora: data/{artifacts,thumbs} for nuScenes,
    # data/staging/hanoi/{artifacts,thumbs} for Hanoi. Derived rather than hardcoded, because the
    # nuScenes path is right only for nuScenes and nothing would have complained on the other.
    thumbs = os.path.relpath(os.path.join(os.path.dirname(opts.artifacts), "thumbs"), ROOT).replace(os.sep, "/")
    for i, fid in enumerate(corpus.frame_ids):
        meta = {k: v for k, v in corpus.metadata_of.get(fid, {}).items() if k not in _NOT_DETECTION}
        caption = corpus.caption_of.get(fid)
        yield [
            fid,
            opts.corpus,
            corpus.scene_of.get(fid),
            video_of.get(fid),
            corpus.timestamp_of.get(fid),
            f"{thumbs}/{fid}.jpg",
            f"{opts.image_base}{fid}.jpg" if opts.image_base else None,
            _vector_literal(corpus.vectors[i]),
            _vector_literal(corpus.caption_vectors[i]),
            json.dumps(meta, ensure_ascii=False) if meta else None,
            json.dumps({"en": caption}, ensure_ascii=False) if caption else None,
            version_id,
        ]


def _upsert_provenance(cur: Any, version_id: str, provenance: dict) -> None:
    """Record which pipeline produced these rows, and make it the active one.

    The ``version_id`` foreign key is the whole point: without it a row cannot say which detector
    drew its boxes or which spatial band produced its ``relations`` — the gap that let the Hanoi
    corpus carry a retired bearing band for nine days with no symptom.
    """
    cur.execute("UPDATE ingest_provenance SET is_active = false WHERE is_active")
    cur.execute(
        """
        INSERT INTO ingest_provenance (version_id, config, is_active)
        VALUES (%s, %s, true)
        ON CONFLICT (version_id) DO UPDATE
           SET config = EXCLUDED.config, is_active = true
        """,
        (version_id, json.dumps(provenance, ensure_ascii=False)),
    )


def _copy_batch(cur: Any, batch: list[list[Any]]) -> None:
    """COPY one batch of rows into the staging table, as CSV so quoting is the writer's problem."""
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(batch)
    buf.seek(0)
    cur.copy_expert(f"COPY frames_stage ({', '.join(COLUMNS)}) FROM STDIN WITH (FORMAT csv)", buf)


def _stage(cur: Any, rows: Iterator[list[Any]], batch_size: int) -> int:
    """Create the staging table and COPY every row into it. Returns the row count."""
    cur.execute("CREATE TEMP TABLE frames_stage (LIKE public.frames INCLUDING DEFAULTS) ON COMMIT DROP")
    total, batch = 0, []
    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            _copy_batch(cur, batch)
            total += len(batch)
            batch = []
            print(f"  staged {total}", flush=True)
    if batch:
        _copy_batch(cur, batch)
        total += len(batch)
    print(f"  staged {total}", flush=True)
    return total


def _merge(cur: Any) -> int:
    """Upsert the staging table into ``frames``. Returns rows affected."""
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c != "frame_id")
    cur.execute(
        f"""
        INSERT INTO public.frames ({", ".join(COLUMNS)})
        SELECT {", ".join(COLUMNS)} FROM frames_stage
        ON CONFLICT (frame_id) DO UPDATE SET {updates}, updated_at = now()
        """
    )
    return cur.rowcount


def _parse_args() -> Options:
    """CLI arguments."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artifacts", default=os.path.join(ROOT, "data/artifacts"), help="promoted artifacts directory")
    ap.add_argument("--corpus", default="nuscenes", help="corpus name stored on every row")
    ap.add_argument(
        "--image-base",
        default=f"https://huggingface.co/datasets/{REPO_ID}/resolve/{REVISION}/",
        help="prefix for image_url; pass '' to leave it null and serve thumbnails from the API",
    )
    ap.add_argument("--batch", type=int, default=500, help="rows per COPY")
    ap.add_argument("--dry-run", action="store_true", help="build every row, write nothing")
    a = ap.parse_args()
    return Options(a.artifacts, a.corpus, a.image_base, a.batch, a.dry_run)


def main() -> None:
    """Load the corpus, or describe what a load would write."""
    opts = _parse_args()
    corpus = Corpus.load(opts.artifacts)
    version_id = f"{opts.corpus}-{corpus.fingerprint}"
    print(f"{corpus.n_frames} frames, encoder {corpus.provenance.get('encoder')}, version_id {version_id}")

    if opts.dry_run:
        first = next(_rows(corpus, opts, version_id))
        trim = {c: (v[:70] + "..." if isinstance(v, str) and len(v) > 70 else v) for c, v in zip(COLUMNS, first)}
        print(json.dumps(trim, indent=2, ensure_ascii=False))
        print("dry run - nothing written")
        return

    with psycopg2.connect(get_settings().database_url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            _upsert_provenance(cur, version_id, corpus.provenance)
            staged = _stage(cur, _rows(corpus, opts, version_id), opts.batch)
            merged = _merge(cur)
    print(f"staged {staged}, upserted {merged} into frames")


if __name__ == "__main__":
    main()
