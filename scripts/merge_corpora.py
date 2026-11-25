"""Append one corpus's artifacts to another's, so one service can search both.

`docs/reference/corpus-growth.md` § 2 has called this the missing step since it was written: ingest
produces a *complete* artifact set per invocation, and nothing merges against a corpus already on
disk, so "add fifty hours" has meant "re-ingest everything" and re-pay a captioning bill for frames
whose captions cannot have changed. This is that step, at the size it is actually needed: nuScenes
(6,858 frames, annotated, what every published number describes) plus Hanoi (2,211 frames, the only
half with source video and therefore the only half a moment clip or a deep link can exist for).

**What it refuses, and why each refusal is the point.**

- **Different encoder → refused.** Two halves embedded by different models are not one vector space,
  and a dot product across them is a number with no meaning that will still sort.
- **Different detector → refused.** `objects` and `relations` are what the metadata filter reads; a
  corpus whose halves saw different detectors answers "a pedestrian on the right" differently
  depending on which half a frame came from, invisibly.
- **Colliding frame or scene ids → refused.** Frame ids are `md5(video_id:filename)` so distinct
  videos cannot collide, but asserting it costs nothing and a collision would silently drop rows.
  `scene_id` is the diversity grouping key: a collision would let one street's frames cap another's.
- **Row counts that disagree with the vectors → refused.** `vectors.npy` is aligned to
  `frames.jsonl` **by position only**, so an off-by-one gives every frame a confident score for a
  different picture. Every file is counted against every other before anything is written.

**The band does not survive, and that is intended.** `provenance.rejection_band` is stamped against a
fingerprint of the frame ids; appending frames changes it, so `/status` reports `corpus_mismatch`
until someone re-fits. This writes the marker rather than carrying either half's numbers across —
inheriting a band is exactly the failure M2_DESIGN §10.3 measured on Tokyo, where a stale band was
wrong in both directions with no symptom.

**`videos.json` is merged, not overwritten.** It is what `source` deep links and the moment join are
built from, and only one half has one.

    .venv/Scripts/python.exe scripts/merge_corpora.py \\
        --sources data/artifacts data/staging/hanoi/artifacts --into data/merged
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from _console import use_utf8  # noqa: E402, F401 -- console encoding; imported for effect

#: Line-oriented artifacts, appended in source order. Each must have exactly one row per frame:
#: `Corpus.load` zips them by position, so a short file is a silent misalignment rather than an error.
JSONL = ("frames.jsonl", "metadata.jsonl", "captions.jsonl", "privacy_detections.jsonl")

#: Matrices, concatenated on axis 0 in the same order. Row `i` must be frame `i` of the merged
#: `frames.jsonl` — the one invariant this whole script exists to keep.
MATRICES = ("vectors.npy", "caption_vectors.npy")

#: What identifies the thing that drew the boxes. **`model` is required on both sides and must
#: match**; the rest are compared only where both halves declare them, because an absent key is a
#: documentation gap and not evidence of a difference. Comparing the whole `detector` block instead
#: refuses this merge over prose: nuScenes records `builder`, `vocabulary` and the 08-14 backfill
#: note, Hanoi records `ego_filter` and a note about the privacy certificate, and both say
#: `resnet50_v2` — which is the only part that decides whether `objects` and `relations` mean the
#: same thing on both halves.
DETECTOR_IDENTITY = ("model", "builder", "weights", "score_threshold")


def read_jsonl(path: str) -> list[dict]:
    """Every row of a JSONL artifact, in file order."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def provenance_of(source: str) -> dict:
    """One corpus's provenance, or a hard stop. A corpus that cannot say what made it is not one."""
    path = os.path.join(source, "provenance.json")
    if not os.path.exists(path):
        sys.exit(f"{source} has no provenance.json — refusing to merge a corpus that cannot say what made it.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_compatible(provenances: list[dict], sources: list[str]) -> list[str]:
    """Refuse halves that were made differently. Returns notes worth printing but not refusing over.

    Two checks, both about meaning rather than tidiness: the encoder decides whether the vectors
    share a space at all, and the detector decides whether the metadata filter answers "a pedestrian
    on the right" the same way on both halves.
    """
    encoders = {json.dumps(p.get("encoder"), sort_keys=True) for p in provenances}
    if len(encoders) > 1:
        named = "\n  ".join(f"{s}: {json.dumps(p.get('encoder'))}" for s, p in zip(sources, provenances))
        sys.exit(
            f"REFUSING to merge: `encoder` differs between the halves.\n  {named}\n"
            "Two halves embedded by different models are not one vector space, and a dot product "
            "across them is a number with no meaning that will still sort."
        )

    detectors = [p.get("detector") or {} for p in provenances]
    models = [d.get("model") for d in detectors]
    if not all(models) or len(set(models)) > 1:
        named = "\n  ".join(f"{s}: model={m!r}" for s, m in zip(sources, models))
        sys.exit(
            f"REFUSING to merge: the detector `model` is missing or differs.\n  {named}\n"
            "`objects` and `relations` are what the metadata filter reads, so a corpus whose halves "
            "saw different detectors answers a relational query differently depending on which half "
            "a frame came from, invisibly."
        )

    notes = []
    for key in DETECTOR_IDENTITY[1:]:
        declared = {s: d[key] for s, d in zip(sources, detectors) if key in d}
        if len(declared) == len(sources) and len({json.dumps(v, sort_keys=True) for v in declared.values()}) > 1:
            sys.exit(f"REFUSING to merge: detector `{key}` differs — {declared}")
        if 0 < len(declared) < len(sources):
            missing = [os.path.relpath(s, ROOT) for s in sources if s not in declared]
            notes.append(f"detector `{key}` is declared by only some halves (missing: {', '.join(missing)})")
    return notes


def check_alignment(source: str) -> int:
    """Every artifact in one source must have the same number of rows. Returns that number."""
    counts = {
        name: len(read_jsonl(os.path.join(source, name)))
        for name in JSONL
        if os.path.exists(os.path.join(source, name))
    }
    for name in MATRICES:
        counts[name] = int(np.load(os.path.join(source, name), mmap_mode="r").shape[0])
    if len(set(counts.values())) != 1:
        sys.exit(f"REFUSING to merge: {source} is internally misaligned — {counts}. Row i must be frame i everywhere.")
    return next(iter(counts.values()))


def _name_of(source: str, provenance: dict) -> str | None:
    """A short name for one contributing corpus, or None rather than an invented one.

    Prefers a name the corpus recorded about itself; otherwise the distinctive segment of its path,
    which is how `data/staging/hanoi/artifacts` becomes `hanoi`. `data/artifacts` is the path every
    promoted corpus lives at, so it names a location rather than a corpus and yields nothing — the
    frame detail then shows no source for those frames, which is the honest outcome and the one the
    UI already handles.
    """
    recorded = provenance.get("corpus_name")
    if recorded:
        return str(recorded)
    generic = {"", ".", "data", "staging", "artifacts", "merged", "corpus", "corpora"}
    for segment in reversed(os.path.relpath(source, ROOT).replace("\\", "/").split("/")):
        if segment.lower() not in generic:
            return segment
    return None


def merge_provenance(provenances: list[dict], sources: list[str], total: int) -> dict:
    """One provenance for the merged corpus, with the band deliberately not carried across."""
    merged = dict(provenances[0])
    merged["source"] = "merged by scripts/merge_corpora.py"
    # `name` and `video_ids` per part, so a frame can be traced back to the corpus it came from.
    # Without them the merged provenance says only how many frames each part contributed, and the
    # frame detail has nothing true to put in "Data Source" — which is why it showed a hardcoded
    # `nuScenes (Production)` on every result until someone blanked it. `Corpus.source_names` reads
    # these; it can fall back to the path when `name` is absent, but only the merge knows which
    # clips came from where, so recording it here is the part that cannot be reconstructed later.
    merged["merged_from"] = [
        {
            "path": os.path.relpath(s, ROOT).replace("\\", "/"),
            "name": _name_of(s, p),
            "n_frames": p.get("n_frames"),
            "source": p.get("source"),
            "video_ids": sorted(p.get("video_ids") or []),
            "corpus_description": p.get("corpus_description"),
        }
        for s, p in zip(sources, provenances)
    ]
    # `merged = dict(provenances[0])` carries the first corpus's `corpus_description` onto the whole
    # merge, and that is a false provenance claim rather than a stale one: the shipped corpus tells
    # users its 9,069 keyframes were "recorded in Boston and Singapore", which is untrue of the 2,211
    # from Hanoi. `rejection.py:_corpus_description` names this exact failure as the thing it exists
    # to prevent — and returning nothing shortens its sentence to a claim true of any corpus, which
    # is the documented safe default. So: keep it only when every part says the same thing. The
    # per-part descriptions are recorded in `merged_from` above, so nothing is lost.
    descriptions = {(p.get("corpus_description") or "").strip() for p in provenances}
    if len(descriptions) > 1:
        merged.pop("corpus_description", None)

    merged["n_frames"] = total
    merged["video_ids"] = sorted({v for p in provenances for v in (p.get("video_ids") or [])})
    merged["n_scenes"] = sum(p.get("n_scenes") or 0 for p in provenances)
    merged["intrinsics"] = {
        key: {k: v for p in provenances for k, v in ((p.get("intrinsics") or {}).get(key) or {}).items()}
        for key in ("hfov_deg", "bonnet_top")
    }
    merged["rejection_thresholds"] = (
        "REFIT REQUIRED - merged corpus. Appending frames changes the fingerprint the band is "
        "stamped against, so /status reports corpus_mismatch until scripts/measure/measure_rejection_band.py "
        "is re-run over the merged judgment set and stamped. Inheriting a band is the M2_DESIGN 10.3 "
        "failure: wrong in both directions, with no symptom."
    )
    merged.pop("rejection_band", None)
    return merged


def merge_videos(sources: list[str], into: str) -> int:
    """Union the clip manifests. Only the half with source video has one, and `source` needs it."""
    clips: dict[str, dict] = {}
    base: dict = {}
    for source in sources:
        path = os.path.join(source, "videos.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        base = base or {k: v for k, v in data.items() if k != "clips"}
        clips.update(data.get("clips") or {})
    if not clips:
        return 0
    with open(os.path.join(into, "videos.json"), "w", encoding="utf-8") as f:
        json.dump({**base, "corpus": "merged", "videos": len(clips), "clips": clips}, f, indent=2, ensure_ascii=False)
    return len(clips)


def merge(sources: list[str], into: str) -> dict:
    """Concatenate every artifact in source order, refusing anything that would misalign rows."""
    provenances = [provenance_of(s) for s in sources]
    notes = check_compatible(provenances, sources)
    counts = [check_alignment(s) for s in sources]

    rows = {name: [] for name in JSONL}
    seen_frames: set[str] = set()
    seen_scenes: dict[str, str] = {}
    for source in sources:
        for name in JSONL:
            path = os.path.join(source, name)
            if os.path.exists(path):
                rows[name] += read_jsonl(path)
        for frame in read_jsonl(os.path.join(source, "frames.jsonl")):
            if frame["frame_id"] in seen_frames:
                sys.exit(f"REFUSING to merge: frame id {frame['frame_id']} appears in more than one half.")
            seen_frames.add(frame["frame_id"])
            owner = seen_scenes.setdefault(frame["scene_id"], source)
            if owner != source:
                sys.exit(
                    f"REFUSING to merge: scene id {frame['scene_id']!r} appears in both {owner} and {source}. "
                    "It is the diversity grouping key — a collision lets one street's frames cap another's."
                )

    os.makedirs(into, exist_ok=True)
    for name, records in rows.items():
        if not records:
            continue
        with open(os.path.join(into, name), "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    for name in MATRICES:
        np.save(os.path.join(into, name), np.concatenate([np.load(os.path.join(s, name)) for s in sources], axis=0))

    total = sum(counts)
    with open(os.path.join(into, "provenance.json"), "w", encoding="utf-8") as f:
        json.dump(merge_provenance(provenances, sources, total), f, indent=2, ensure_ascii=False)
    return {
        "frames": total,
        "per_source": dict(zip(sources, counts)),
        "clips": merge_videos(sources, into),
        "notes": notes,
    }


def verify(into: str, expected: int) -> None:
    """Re-read what was written and check it the way the service will. Cheap, and it has to hold."""
    counts = {
        name: len(read_jsonl(os.path.join(into, name))) for name in JSONL if os.path.exists(os.path.join(into, name))
    }
    for name in MATRICES:
        counts[name] = int(np.load(os.path.join(into, name), mmap_mode="r").shape[0])
    if set(counts.values()) != {expected}:
        sys.exit(f"merge wrote something misaligned: {counts}, expected {expected} rows everywhere.")
    frames = read_jsonl(os.path.join(into, "frames.jsonl"))
    if len({f["frame_id"] for f in frames}) != expected:
        sys.exit("merge wrote duplicate frame ids.")


def link_thumbs(sources: list[str], into: str) -> int:
    """Copy both halves' thumbnails into one directory, since `THUMBS_DIR` is a single path.

    **Hard links where the filesystem allows them, a copy otherwise.** A hard link is a real
    directory entry, so unlike a symlink farm it survives `tar` and `scp` — and it costs no disk,
    which matters at 385 MB across 9,069 files. Existing entries are left alone, so a re-run is
    cheap. The box is fed the *new* half only; it already holds the other one.
    """
    copied = 0
    os.makedirs(into, exist_ok=True)
    for source in sources:
        thumbs = os.path.join(os.path.dirname(source), "thumbs")
        if not os.path.isdir(thumbs):
            thumbs = os.path.join(ROOT, "data", "thumbs") if source.endswith("artifacts") else thumbs
        if not os.path.isdir(thumbs):
            continue
        for name in os.listdir(thumbs):
            # Skip anything that is not a thumbnail file:  is a directory, and
            # the copy raised PermissionError on it rather than saying so.
            if not os.path.isfile(os.path.join(thumbs, name)):
                continue
            target = os.path.join(into, name)
            if os.path.exists(target):
                continue
            try:
                os.link(os.path.join(thumbs, name), target)
            except OSError:
                shutil.copy2(os.path.join(thumbs, name), target)
            copied += 1
    return copied


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge two artifact sets into one searchable corpus.")
    ap.add_argument("--sources", nargs="+", default=["data/artifacts", "data/staging/hanoi/artifacts"])
    ap.add_argument("--into", default="data/merged/artifacts")
    ap.add_argument("--thumbs-into", default="", help="also gather both halves' thumbnails here")
    args = ap.parse_args()

    sources = [os.path.join(ROOT, s) for s in args.sources]
    into = os.path.join(ROOT, args.into)
    result = merge(sources, into)
    verify(into, result["frames"])
    for note in result["notes"]:
        print(f"  note: {note}")
    for source, count in result["per_source"].items():
        print(f"  {count:>6} frames  {os.path.relpath(source, ROOT)}")
    print(f"  {result['frames']:>6} frames  -> {os.path.relpath(into, ROOT)}  ({result['clips']} source clips)")
    if args.thumbs_into:
        copied = link_thumbs(sources, os.path.join(ROOT, args.thumbs_into))
        print(f"  {copied:>6} thumbnails copied -> {args.thumbs_into}")
    print("\n/status will report `corpus_mismatch` until the band is re-fitted against this corpus.")


if __name__ == "__main__":
    main()
