"""Turn confirmed reviews into a dataset file — the artifact the product actually delivers.

`reviews.py` explains why the database is a working buffer; this is the thing worth keeping. A user
who reviews and never exports has produced nothing, so these two formats are the end of the
workflow, not a convenience feature.

**Every export carries the corpus provenance.** A list of frame ids is not a test set: six months
later, `558a…_CAM_FRONT` means nothing unless you know which archive it indexes and which encoder
ranked it. `provenance.json` already records exactly that for the corpus, so it rides along —
the same discipline `promote_artifacts.py` applies to artifacts, applied to what leaves the system.

**Rows carry `scene_id` and `timestamp_s`.** Those are what let someone open the source clip at the
right moment. Without them the export is only usable by this system, which defeats the point of
exporting.
"""

from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from datetime import datetime, timezone

from src.services.reviews import Review

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc  # noqa: UP017

# Column order is the contract: reviewers open these in a spreadsheet, and a reordering that only
# shows up downstream is the kind of change nobody notices until a script silently reads the wrong
# column. Identity first, verdict second, locator last.
#
# `reviewer` sits with identity, before the verdict: it is part of what a row *is*, not a note about
# it. Without it an export of a multi-tester session is one undifferentiated pile, inter-rater
# agreement cannot be computed from it, and the rubric's "3-5 people" has no evidence in the
# artifact that is supposed to be the evidence.
COLUMNS = ("query", "frame_id", "reviewer", "decision", "note", "reviewed_at", "scene_id", "timestamp_s")


def _rows(
    reviews: list[Review],
    scene_of: dict[str, str],
    timestamp_of: dict[str, float],
    caption_of: dict[str, str] | None = None,
    metadata_of: dict[str, dict] | None = None,
) -> list[dict]:
    """Join each decision to where its frame lives in the archive.

    A frame missing from the corpus is exported with empty locators rather than dropped: it means
    the corpus was re-ingested under the review set, and losing the row would hide that. An empty
    cell is a question the reviewer can chase; a vanished row is not.
    """
    captions = caption_of or {}
    metas = metadata_of or {}
    rows = []
    for r in reviews:
        meta = metas.get(r.frame_id, {})
        satisfied = [f"object:{k}" for k in meta.get("objects", {})] + [
            f"rel:{k}:{rel}" for k, rels in meta.get("relations", {}).items() for rel in rels
        ]
        row = {
            "query": r.query,
            "frame_id": r.frame_id,
            "reviewer": r.reviewer,
            "decision": r.decision,
            "note": r.note,
            "reviewed_at": r.reviewed_at,
            "scene_id": scene_of.get(r.frame_id, ""),
            "timestamp_s": timestamp_of.get(r.frame_id, ""),
            "caption": captions.get(r.frame_id, ""),
            "satisfied": satisfied,
        }
        rows.append(row)
    return rows


def to_json(reviews: list[Review], corpus) -> str:
    """The full record: what was judged, against which corpus, when."""
    return json.dumps(
        {
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "count": len(reviews),
            # Stated at the top rather than left to be derived by counting distinct values in a
            # 400-row list: how many people judged this is the first question asked of the artifact.
            "reviewers": sorted({r.reviewer for r in reviews}),
            "corpus": corpus.provenance,
            "decisions": _rows(
                reviews,
                corpus.scene_of,
                corpus.timestamp_of,
                getattr(corpus, "caption_of", None),
                getattr(corpus, "metadata_of", None),
            ),
        },
        indent=2,
        ensure_ascii=False,
    )


def to_csv(reviews: list[Review], corpus) -> str:
    """The same rows, flat, for a spreadsheet.

    CSV has nowhere structured to put provenance, and inventing a comment header would break every
    naive parser. So it is omitted here and the JSON export is named as the complete one — stated
    in `docs/api-contract.md` rather than left for someone to notice.

    `\\r\\n` is what `csv` writes by default and what RFC 4180 specifies; `newline=""` on the buffer
    stops the platform translating it again into `\\r\\r\\n`, which Excel renders as blank rows.
    """
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(_rows(reviews, corpus.scene_of, corpus.timestamp_of))
    return buffer.getvalue()


def to_zip(reviews: list[Review], corpus, thumbs_dir: str) -> bytes:
    """Package reviewed frame JPEG images and their JSON manifest into a single ZIP archive.

    Includes `manifest.json` at the root and all available `images/<frame_id>.jpg` files.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Include the full JSON manifest so the archive is self-documenting
        manifest_json = to_json(reviews, corpus)
        zf.writestr("manifest.json", manifest_json)

        # Include unique frame JPEG images (from local thumbs_dir or corpus.image_url_of in DATABASE_URL)
        image_urls = getattr(corpus, "image_url_of", {}) or {}
        added_frames: set[str] = set()
        for r in reviews:
            if r.frame_id in added_frames:
                continue
            added_frames.add(r.frame_id)
            img_name = f"{r.frame_id}.jpg"
            img_path = os.path.join(thumbs_dir, img_name)
            if os.path.isfile(img_path):
                zf.write(img_path, arcname=f"images/{img_name}")
            elif img_url := image_urls.get(r.frame_id):
                try:
                    import urllib.request

                    with urllib.request.urlopen(img_url, timeout=10) as resp:
                        zf.writestr(f"images/{img_name}", resp.read())
                except Exception:
                    pass

    return buffer.getvalue()


def filename(decision: str | None, extension: str) -> str:
    """A download name that says what is in the file and when it was judged."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"scenesearch-{decision or 'all'}-{stamp}.{extension}"
