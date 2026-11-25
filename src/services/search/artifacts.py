"""Load the ingest-written artifacts once, at startup.

Everything here is read-only and shared across requests. M2_DESIGN §3 splits the system by *when*
work happens: ingest writes these files offline, query only reads them, and the two halves never
call each other. That is what makes a request cheap — no detector, no captioner, no nuScenes devkit
in the request path, just a matmul against a resident matrix.

Produced by `scripts/promote_artifacts.py`. See `data/artifacts/provenance.json` for which
experiment each artifact came from.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from src.config import get_settings


def fingerprint_of(frame_ids: list[str], encoder: str) -> str:
    """The corpus id `band.py` compares against. Module-level so a script can compute it from
    `frames.jsonl` alone, without loading 40 MB of vectors to stamp twelve characters."""
    return hashlib.sha256("\n".join([*frame_ids, encoder]).encode("utf-8")).hexdigest()[:12]


# Path segments that name a *location* rather than a corpus. `data/artifacts` is where the promoted
# corpus lives on every box, so it says nothing about which corpus that is; `data/staging/hanoi/
# artifacts` says `hanoi`. Deriving a name is second best and `merge_corpora.py` now records one —
# this is what keeps corpora merged before that from being nameless forever.
_GENERIC_PATH_SEGMENTS = frozenset({"", ".", "data", "staging", "artifacts", "merged", "corpus", "corpora"})


def _name_from_path(path: str) -> str | None:
    """The distinctive segment of a source corpus's path, or None when every segment is generic."""
    for segment in reversed(path.replace("\\", "/").split("/")):
        if segment.lower() not in _GENERIC_PATH_SEGMENTS:
            return segment
    return None


def _read_jsonl(path: str) -> list[dict]:
    """Read a JSONL artifact, failing loudly — a half-loaded corpus is worse than no service."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"missing artifact {path}. Run scripts/promote_artifacts.py (see M2_DESIGN §4).")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@dataclass(frozen=True)
class Corpus:
    """The searchable corpus: §4's three tables plus what rejection needs.

    Row order is identical across `frame_ids`, `vectors` and `caption_vectors` — the promotion
    script guarantees it, and `load` re-checks rather than trusting it, because a silent misalignment
    would return confident results for the wrong frames.
    """

    frame_ids: list[str]
    vectors: np.ndarray  # (N, 768) L2-normalised SigLIP2
    caption_vectors: np.ndarray  # (N, 384) L2-normalised MiniLM
    scene_of: dict[str, str]  # frame_id -> scene_id, the diversity grouping key
    timestamp_of: dict[str, float]  # frame_id -> offset into its clip, seconds
    metadata_of: dict[str, dict]  # frame_id -> detected objects + relations
    caption_of: dict[str, str]  # frame_id -> Florence-2 caption
    provenance: dict
    # frame_id -> the clip it was extracted from, which `videos.json` resolves to a URL and a
    # credit. Defaulted rather than required because it is the one field a corpus can be complete
    # without: every artifact set on disk carries `video_id`, but four tests build a `Corpus` by
    # hand to exercise something else entirely, and a required field would make them all say
    # `video_of={}` to prove they do not care.
    video_of: dict[str, str] = field(default_factory=dict)
    image_url_of: dict[str, str] = field(default_factory=dict)
    fingerprint_override: str | None = None

    @property
    def n_frames(self) -> int:
        return len(self.frame_ids)

    @property
    def fingerprint(self) -> str:
        """A short content id for *this* corpus — what the rejection band is fitted against.

        `provenance.json` carries no universal corpus id: promoted nuScenes corpora have
        `retrieval`, folder-ingested ones have nothing, and neither moves when the files under them
        do. So the id is derived from the corpus itself, and a band stamped for one fingerprint is
        visibly not a band for another (`band.py`).

        Frame ids and the encoder, deliberately, and **not** the captions: on a caption-deferred
        corpus `caption_of` grows at query time as the cache fills, and a fingerprint that moved
        every few searches would report drift that is not there. The cost of that choice is stated
        rather than hidden — re-captioning the same frames with a different captioner shifts every
        option-B score and this will not notice.
        """
        if self.fingerprint_override:
            return self.fingerprint_override
        return fingerprint_of(self.frame_ids, str(self.provenance.get("encoder", "")))

    @property
    def source_names(self) -> dict[str, str]:
        """Which corpus each **video** came from, for the corpora this one was merged out of.

        Empty for a corpus that was not merged, and partial for one whose parts cannot all be named
        — both of which mean callers get `None` for those frames rather than a guess. That is the
        whole point: the frame card used to print a hardcoded `nuScenes (Production)` on every
        result, which became false the moment the service was pointed at Hanoi, and the fix at the
        time was to show nothing. This names what can be named and keeps showing nothing for the
        rest.

        Two sources of the name, in order:

        1. `merged_from[].name`, written by `scripts/merge_corpora.py`. Recorded at merge time by
           the step that actually knows, which is where this belongs.
        2. Failing that, the distinctive segment of the recorded source `path` — `data/staging/
           hanoi/artifacts` is `hanoi`. Derived rather than invented, and it exists because the
           deployed corpus was merged before names were recorded; without it every frame on the box
           stays blank until a re-merge. A path of only generic segments (`data/artifacts`) yields
           nothing, and nothing is the correct answer there.

        Attribution is by `video_id` because that is what a merge preserves per frame.

        **The corpus deployed today records no per-part `video_ids`** — `merge_provenance` unioned
        them into one top-level list — so there is a fallback for exactly that shape: if only one
        part can be named at all, the top-level list is that part's, because the other contributed
        none. When *two* parts are nameable the fallback refuses and returns nothing, since a union
        cannot say which of them a clip came from and inventing an answer is the failure this whole
        field exists to avoid.
        """
        parts = self.provenance.get("merged_from") or []
        named = [(p, p.get("name") or _name_from_path(p.get("path") or "")) for p in parts]
        named = [(p, n) for p, n in named if n]

        names: dict[str, str] = {}
        for part, name in named:
            for video_id in part.get("video_ids") or []:
                names[video_id] = name
        if names:
            return names

        if len(named) == 1:
            only_name = named[0][1]
            return {video_id: only_name for video_id in self.provenance.get("video_ids") or []}
        return {}

    @property
    def captions_deferred(self) -> bool:
        """Was this corpus ingested with `--skip-captions`, leaving captioning to query time?

        Read from provenance rather than inferred from empty captions, because the two failures look
        identical from here and mean opposite things: a deferred corpus should caption on demand, a
        corpus whose captions went missing should be re-ingested, not quietly re-captioned one frame
        at a time from thumbnails. The ingest that creates the condition is the thing that knows.
        """
        return bool((self.provenance.get("captions") or {}).get("deferred"))

    @classmethod
    def load(cls, artifacts_dir: str) -> Corpus:
        """Read every artifact and check they describe the same corpus."""
        frames = _read_jsonl(os.path.join(artifacts_dir, "frames.jsonl"))
        ids = [r["frame_id"] for r in frames]
        vectors = np.load(os.path.join(artifacts_dir, "vectors.npy"), allow_pickle=False)
        caption_vectors = np.load(os.path.join(artifacts_dir, "caption_vectors.npy"), allow_pickle=False)
        meta = {r["frame_id"]: r for r in _read_jsonl(os.path.join(artifacts_dir, "metadata.jsonl"))}
        caps = {r["frame_id"]: r["caption"] for r in _read_jsonl(os.path.join(artifacts_dir, "captions.jsonl"))}
        if not (vectors.shape[0] == caption_vectors.shape[0] == len(ids)):
            raise ValueError(
                f"artifact row counts disagree: frames={len(ids)} vectors={vectors.shape[0]} "
                f"caption_vectors={caption_vectors.shape[0]} — re-run promote_artifacts.py"
            )
        with open(os.path.join(artifacts_dir, "provenance.json"), encoding="utf-8") as f:
            provenance = json.load(f)
        # Captions written after ingest, on a caption-deferred corpus. Imported here rather than at
        # module scope because `captions` imports `Corpus` — and merged into `caption_of` at load so
        # a restart does not re-pay for captioning the demo already did.
        from src.services.search.captions import read_cache

        caps.update({k: v for k, v in read_cache(artifacts_dir).items() if k in set(ids)})
        return cls(
            frame_ids=ids,
            vectors=np.ascontiguousarray(vectors.astype("float32")),
            caption_vectors=np.ascontiguousarray(caption_vectors.astype("float32")),
            scene_of={r["frame_id"]: r["scene_id"] for r in frames},
            timestamp_of={r["frame_id"]: r["timestamp_s"] for r in frames},
            metadata_of=meta,
            caption_of=caps,
            provenance=provenance,
            # `.get` rather than `[...]`: `video_id` has been written by every ingest this project
            # has, but an artifact set is read from disk and a missing key here should cost the
            # source link, not the service.
            video_of={r["frame_id"]: r.get("video_id", "") for r in frames},
        )


    @classmethod
    def load_from_db(cls, database_url: str) -> Corpus:
        """Load corpus metadata and provenance directly from PostgreSQL (DATABASE_URL).

        Heavy vector matrices (`image_vector`, `caption_vector`) stay in PostgreSQL and are queried
        via `pgvector` cosine operators (`<=>`) per search request instead of being pulled into RAM.
        """
        import psycopg2

        url = database_url.replace("postgres://", "postgresql://", 1) if database_url.startswith("postgres://") else database_url
        with psycopg2.connect(url, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT version_id, config FROM public.ingest_provenance WHERE is_active = true ORDER BY created_at DESC LIMIT 1"
                )
                prov_row = cur.fetchone()
                if not prov_row:
                    raise FileNotFoundError("no active ingest_provenance record in PostgreSQL")
                version_id, provenance = prov_row[0], prov_row[1] or {}
                fp = (
                    (provenance.get("rejection_band") or {}).get("corpus")
                    or (version_id.rsplit("-", 1)[-1] if "-" in str(version_id) else None)
                )

                cur.execute(
                    """
                    SELECT frame_id, scene_id, video_id, timestamp_sec,
                           detection_metadata, captions, image_url
                    FROM public.frames
                    ORDER BY created_at, frame_id
                    """
                )
                rows = cur.fetchall()
                if not rows:
                    raise FileNotFoundError("public.frames table in PostgreSQL is empty")

        ids: list[str] = []
        scene_of: dict[str, str] = {}
        video_of: dict[str, str] = {}
        timestamp_of: dict[str, float] = {}
        metadata_of: dict[str, dict] = {}
        caption_of: dict[str, str] = {}
        image_url_of: dict[str, str] = {}

        for fid, scene_id, video_id, ts, meta, caps, img_url in rows:
            ids.append(fid)
            scene_of[fid] = scene_id or ""
            video_of[fid] = video_id or ""
            timestamp_of[fid] = float(ts or 0.0)
            m = dict(meta) if isinstance(meta, dict) else {}
            m["frame_id"] = fid
            metadata_of[fid] = m
            if isinstance(caps, dict) and caps.get("en"):
                caption_of[fid] = str(caps["en"])
            elif isinstance(caps, str) and caps:
                caption_of[fid] = caps
            if img_url:
                image_url_of[fid] = str(img_url)

        return cls(
            frame_ids=ids,
            vectors=np.empty((0, 768), dtype="float32"),
            caption_vectors=np.empty((0, 384), dtype="float32"),
            scene_of=scene_of,
            timestamp_of=timestamp_of,
            metadata_of=metadata_of,
            caption_of=caption_of,
            provenance=provenance,
            video_of=video_of,
            image_url_of=image_url_of,
            fingerprint_override=fp,
        )


@lru_cache(maxsize=1)
def get_corpus() -> Corpus:
    """Process-wide corpus. Cached because loading it per request would dominate latency."""
    settings = get_settings()
    if settings.use_database_corpus and settings.database_url and "localhost:5432/dbname" not in settings.database_url:
        try:
            return Corpus.load_from_db(settings.database_url)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Could not load corpus from DATABASE_URL (%s); falling back to disk artifacts_dir=%s",
                exc,
                settings.artifacts_dir,
            )
    return Corpus.load(settings.artifacts_dir)
