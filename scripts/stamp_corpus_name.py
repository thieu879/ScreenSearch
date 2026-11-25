"""Record what a corpus *is*, on artifacts built before anything wrote it down.

`promote_artifacts.py` and `ingest_folder.py` now write `corpus_name`, and `merge_corpora.py`
carries it into `merged_from[].name`. Corpora built before those changes carry no name, so
`Corpus.source_names` can place their frames only when the source path happens to be distinctive —
`data/staging/hanoi/artifacts` gives `hanoi`, while `data/artifacts` is where *every* promoted
corpus lives and so gives nothing. The frame detail then reads "—" for those frames.

"—" is right when the name is unknown and wrong when it is merely unrecorded, and this is the second
case: the nuScenes corpus is nuScenes, and the only reason the service cannot say so is that no step
ever wrote it into `provenance.json`. This writes it, once, deliberately, by a person who knows which
corpus they are naming — the same posture as `stamp_rejection_band.py`, and for the same reason: a
fact that cannot be recomputed has to be recorded rather than inferred at read time.

**It does not re-derive or guess.** You pass the name. It refuses to overwrite a different one
without `--force`, so running it twice is safe and running it on the wrong corpus is caught.

    # A merged corpus, on the machine that merged it — the usual case, and the one that works:
    python scripts/stamp_corpus_name.py --artifacts data/merged/artifacts --backfill-parts

    # Name a single corpus:
    python scripts/stamp_corpus_name.py --artifacts data/artifacts --name nuScenes

    # Name one part of a merge by hand, when its source is not on this machine:
    python scripts/stamp_corpus_name.py --artifacts data/merged/artifacts \\
        --part data/artifacts --name nuScenes

`--backfill-parts` is the one to reach for. Naming a part by hand is not enough on its own: a part
also has to say which clips are *its*, or `source_names` cannot tell two named parts apart and
correctly refuses to attribute anything. See `backfill_parts`.

None of this moves the corpus fingerprint — that is frame ids plus encoder — so a fitted rejection
band stays fitted and `/status` does not change. Re-running the merge instead would rebuild 9,069
frames of vectors and thumbnails to add two strings.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def load(path: str) -> dict:
    if not os.path.exists(path):
        sys.exit(f"{path} does not exist — point --artifacts at a corpus directory.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def stamp_corpus(provenance: dict, name: str, force: bool) -> str:
    """Name the corpus as a whole. Returns what changed, for the caller to print."""
    existing = provenance.get("corpus_name")
    if existing == name:
        return f"corpus_name already {name!r} — nothing to do"
    if existing and not force:
        sys.exit(f"corpus_name is already {existing!r}; pass --force to replace it with {name!r}.")
    provenance["corpus_name"] = name
    return f"corpus_name {existing!r} -> {name!r}"


def stamp_part(provenance: dict, part_path: str, name: str, force: bool) -> str:
    """Name one contributing corpus inside a merged one, matched on its recorded path."""
    parts = provenance.get("merged_from") or []
    if not parts:
        sys.exit("this corpus has no merged_from — it was not merged, so use --name without --part.")
    wanted = part_path.replace("\\", "/").rstrip("/")
    matches = [p for p in parts if (p.get("path") or "").replace("\\", "/").rstrip("/") == wanted]
    if not matches:
        known = ", ".join(repr(p.get("path")) for p in parts)
        sys.exit(f"no merged_from entry with path {wanted!r}. This corpus was merged from: {known}")
    if len(matches) > 1:
        sys.exit(f"{len(matches)} merged_from entries share the path {wanted!r} — cannot tell which you mean.")

    part = matches[0]
    existing = part.get("name")
    if existing == name:
        return f"merged_from[{wanted}].name already {name!r} — nothing to do"
    if existing and not force:
        sys.exit(f"merged_from[{wanted}].name is already {existing!r}; pass --force to replace it.")
    part["name"] = name
    return f"merged_from[{wanted}].name {existing!r} -> {name!r}"


_GENERIC = frozenset({"", ".", "data", "staging", "artifacts", "merged", "corpus", "corpora"})


def _name_from_path(path: str) -> str | None:
    """The distinctive segment of a corpus path — the same rule `Corpus.source_names` falls back to.

    Applied here so the name is *recorded* rather than re-derived on every read: a corpus that says
    what it is beats one whose name is a property of where it happened to sit on disk.
    """
    for segment in reversed(path.replace("\\", "/").split("/")):
        if segment.lower() not in _GENERIC:
            return segment
    return None


def _video_ids_of(artifacts_dir: str, provenance: dict) -> list[str]:
    """Which videos a source corpus holds — from its provenance, or from its own frames.

    **The frames are the fallback that makes this work for nuScenes**, whose provenance records no
    `video_ids` at all: only folder ingest writes that list. Reading the distinct `video_id` out of
    the corpus's own `frames.jsonl` is not an inference — it is the corpus stating which videos it
    is made of, in the same file that defines its frames. Without it, nuScenes frames stay
    unattributable and the frame detail keeps showing an em dash for 6,858 of 9,069 frames, which
    is the complaint that started this.
    """
    recorded = provenance.get("video_ids")
    if recorded:
        return sorted(recorded)
    frames = os.path.join(artifacts_dir, "frames.jsonl")
    if not os.path.exists(frames):
        return []
    seen: set[str] = set()
    with open(frames, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                video_id = json.loads(line).get("video_id")
                if video_id:
                    seen.add(video_id)
    return sorted(seen)


def backfill_parts(provenance: dict, root: str, force: bool) -> list[str]:
    """Fill `name`, `video_ids` and `corpus_description` per part, from the sources on disk.

    **Naming a part is not enough on its own, and getting that wrong is instructive.** The first
    version of this script wrote only `name`, which made a second part of the merge nameable and
    tripped `source_names`' ambiguity guard: a pooled `video_ids` list is only attributable when
    exactly one part could have contributed it, so naming both parts turned a corpus where Hanoi
    frames were correctly labelled into one where nothing was. The guard was right; the stamp was
    half a job. A part needs to say *which clips are its own*, and only its source corpus knows.

    So this reads each `merged_from[].path` on the machine that did the merge — where those
    directories still exist — and copies across exactly what `merge_corpora.py` now records at merge
    time. A part whose source is gone is left alone and reported, rather than filled with a guess.
    """
    parts = provenance.get("merged_from") or []
    if not parts:
        sys.exit("this corpus has no merged_from — it was not merged, so use --name without --backfill-parts.")

    changes: list[str] = []
    for part in parts:
        path = part.get("path") or ""
        source = os.path.join(root, path.replace("/", os.sep), "provenance.json")
        if not os.path.exists(source):
            changes.append(f"  {path}: source not on this machine — left as {part.get('name')!r}")
            continue
        with open(source, encoding="utf-8") as f:
            src = json.load(f)

        filled = []
        for key, value in (
            ("name", src.get("corpus_name") or _name_from_path(path)),
            ("video_ids", _video_ids_of(os.path.dirname(source), src)),
            ("corpus_description", src.get("corpus_description")),
        ):
            if value in (None, "") and key != "video_ids":
                continue
            if part.get(key) not in (None, [], "") and not force:
                continue
            part[key] = value
            filled.append(key)
        changes.append(f"  {path}: {', '.join(filled) if filled else 'already complete'}")
    return changes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artifacts", required=True, help="the corpus directory holding provenance.json")
    ap.add_argument("--name", help="what this corpus is called, e.g. nuScenes")
    ap.add_argument(
        "--backfill-parts",
        action="store_true",
        help="fill every merged_from entry from its source corpus on disk (name, video_ids, description)",
    )
    ap.add_argument(
        "--part",
        metavar="PATH",
        help="name one contributing corpus of a merged one, matched on its recorded merged_from path",
    )
    ap.add_argument("--force", action="store_true", help="replace a name that is already recorded")
    ap.add_argument("--dry-run", action="store_true", help="report what would change and write nothing")
    args = ap.parse_args()

    if not args.backfill_parts and not args.name:
        ap.error("pass --name, or --backfill-parts to read the names from the source corpora")

    path = os.path.join(args.artifacts, "provenance.json")
    provenance = load(path)

    if args.backfill_parts:
        # Relative to the repo, because `merged_from[].path` is recorded that way.
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        change = "backfilled merged_from from source corpora:\n" + "\n".join(
            backfill_parts(provenance, root, args.force)
        )
    elif args.part:
        change = stamp_part(provenance, args.part, args.name, args.force)
    else:
        change = stamp_corpus(provenance, args.name, args.force)

    if args.dry_run:
        print(f"[dry-run] {path}: {change}")
        return

    with open(path, "w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"{path}: {change}")
    print("Restart the service to pick it up — provenance is read once, at corpus load.")


if __name__ == "__main__":
    main()
