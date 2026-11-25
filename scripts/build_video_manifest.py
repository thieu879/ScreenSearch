"""Map a corpus's `video_id`s back to the footage they came from — the join nothing recorded.

A frame already knows almost everything: `frames.jsonl` carries `video_id`, `scene_id` and
`timestamp_s`, so any hit resolves to *"clip01_hanoi at 274.5 s"*. What no artifact records is what
`clip01_hanoi` **is**. The yt-dlp sidecars that came with the download hold the answer — id, URL,
uploader, licence — and they sit outside the repo where nothing points at them.

**This is a licence obligation before it is a convenience.** All 24 Hanoi clips are Creative Commons
**Attribution**, which requires crediting the author. Neither the corpus nor the deployed product
credits anyone today, and the frames are about to be handed to enterprises. The markdown half of this
script exists to be that credit, in git, rather than a promise in a planning doc.

**It writes the pointer, never the pixels.** The source clips are unredacted street video — faces and
plates intact — and the whole privacy gate exists because frames are redacted *before* publication.
Republishing the clips would make this project the publisher of exactly what `publish_assets.py`
refuses to release. A URL plus a timestamp is a better answer anyway: it is public, verifiable by
anyone, and costs nothing to store.

**`sha256` is the part that survives a takedown.** A YouTube video can disappear; the hash proves that
whatever archived copy someone holds is the one this corpus was built from. `--no-hash` skips it for
a quick re-run, and skipping it is the only way to get a manifest that cannot be checked.

    .venv/Scripts/python.exe scripts/build_video_manifest.py --corpus data/staging/hanoi
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The fields worth keeping out of a 70-key yt-dlp dump: identity, credit, and the geometry a later
# dense re-extraction needs. Everything else is formats, thumbnails and playback state.
KEEP = ("id", "title", "webpage_url", "uploader", "channel_url", "license", "duration", "upload_date")


def corpus_video_ids(corpus: str) -> set[str]:
    """Every `video_id` the corpus actually holds frames for."""
    path = os.path.join(corpus, "artifacts", "frames.jsonl")
    with open(path, encoding="utf-8") as f:
        return {json.loads(line)["video_id"] for line in f if line.strip()}


def sha256_of(path: str) -> str:
    """Hash a file in blocks — these are gigabyte-scale and must not be read into memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_sidecar(path: str, hash_media: bool) -> dict:
    """One `.info.json` reduced to the fields a manifest needs, plus the media file's identity."""
    with open(path, encoding="utf-8") as f:
        info = json.load(f)
    record = {k: info[k] for k in KEEP if k in info}
    record["fps"] = info.get("fps")
    record["resolution"] = f"{info.get('width')}x{info.get('height')}"
    media = path.replace(".info.json", ".mp4")
    if os.path.exists(media):
        record["media_file"] = os.path.basename(media)
        record["bytes"] = os.path.getsize(media)
        if hash_media:
            record["sha256"] = sha256_of(media)
    return record


def collect(sidecars: str, hash_media: bool) -> dict[str, dict]:
    """Every sidecar in the directory, keyed by the `video_id` its filename implies."""
    out = {}
    for path in sorted(glob.glob(os.path.join(sidecars, "*.info.json"))):
        video_id = os.path.basename(path)[: -len(".info.json")]
        out[video_id] = read_sidecar(path, hash_media)
    return out


def check(videos: dict[str, dict], wanted: set[str]) -> list[str]:
    """A corpus video with no source is the failure this script exists to make impossible."""
    missing = sorted(wanted - set(videos))
    if missing:
        raise SystemExit(f"{len(missing)} corpus videos have no sidecar (first: {missing[0]}) — wrong directory?")
    return sorted(set(videos) - wanted)


def write_manifest(path: str, videos: dict[str, dict], corpus: str) -> None:
    """The machine-readable half, written beside the corpus so it travels with it."""
    payload = {
        "corpus": os.path.basename(os.path.normpath(corpus)),
        "videos": len(videos),
        "source": "yt-dlp .info.json sidecars taken at download time",
        "deep_link": "{webpage_url}&t={timestamp_s:.0f} — frames.jsonl carries video_id and timestamp_s",
        "redistribution": "pointer only. The clips are unredacted street video; this project publishes "
        "redacted frames and must not become the publisher of the footage they came from.",
        "clips": dict(sorted(videos.items())),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def short_licence(text: str) -> str:
    """`Creative Commons Attribution license (reuse allowed)` is the source's wording, not a label.

    Shortened for the table only. The full string stays in `videos.json`: a licence paraphrased into
    a document is a claim about permissions that nobody checked against the original.
    """
    lowered = text.lower()
    if "creative commons attribution" in lowered:
        return "CC BY"
    return text


def write_credits(path: str, videos: dict[str, dict], counts: dict[str, int]) -> None:
    """The human-readable half: the attribution CC BY requires, in git, in one table."""
    lines = [
        "# Hanoi corpus — where the footage came from",
        "",
        "**Generated by `scripts/build_video_manifest.py`. Do not hand-edit — re-run it.**",
        "",
        f"{len(videos)} clips. Every one is licensed **Creative Commons Attribution**, which requires "
        "crediting the author; this page is that credit and the reason it is committed rather than "
        "generated on demand.",
        "",
        "**The clips themselves are not redistributed here.** They are unredacted street video, and "
        "this project publishes redacted frames — a URL and a timestamp trace a result back just as "
        "exactly, without making us the publisher of the footage. Any archived copy can be checked "
        "against the `sha256` in the corpus's `videos.json`.",
        "",
        "A retrieved frame resolves to a moment: `frames.jsonl` gives `video_id` and `timestamp_s`, "
        "and the source link plus `&t=<seconds>` opens the video there. That `timestamp_s` really is "
        "seconds into the source rather than an ingest-relative clock — each clip's last keyframe "
        "lands within a few seconds of the duration the sidecar reports, which is what makes the link "
        "land in the right place.",
        "",
        "`licence` is shortened here; `videos.json` keeps each source's own wording verbatim, because "
        "a paraphrased licence is not a licence.",
        "",
        "| video_id | frames | source | title | uploader | licence | length |",
        "|---|---|---|---|---|---|---|",
    ]
    for video_id, v in sorted(videos.items()):
        mins = f"{v.get('duration', 0) // 60}:{v.get('duration', 0) % 60:02d}"
        lines.append(
            f"| `{video_id}` | {counts.get(video_id, 0)} | [{v.get('id', '?')}]({v.get('webpage_url', '')}) "
            f"| {v.get('title', '').replace('|', '/')} | [{v.get('uploader', '?').strip()}]"
            f"({v.get('channel_url', '')}) | {short_licence(v.get('license', '?'))} | {mins} |"
        )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def frame_counts(corpus: str) -> dict[str, int]:
    """How many frames each video contributed — the column that shows the corpus's real shape."""
    counts: dict[str, int] = {}
    with open(os.path.join(corpus, "artifacts", "frames.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                vid = json.loads(line)["video_id"]
                counts[vid] = counts.get(vid, 0) + 1
    return counts


def main() -> None:
    """Read the sidecars, check them against the corpus, write both halves."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=os.path.join(ROOT, "data", "staging", "hanoi"))
    parser.add_argument("--sidecars", default=os.path.join(ROOT, "..", "data", "first_release"))
    parser.add_argument("--doc", default=os.path.join(ROOT, "docs", "reference", "hanoi-sources.md"))
    parser.add_argument("--no-hash", action="store_true", help="skip sha256 — faster, and uncheckable")
    args = parser.parse_args()

    wanted = corpus_video_ids(args.corpus)
    videos = collect(args.sidecars, not args.no_hash)
    unused = check(videos, wanted)
    counts = frame_counts(args.corpus)

    manifest = os.path.join(args.corpus, "artifacts", "videos.json")
    write_manifest(manifest, videos, args.corpus)
    write_credits(args.doc, videos, counts)

    licences = {v.get("license", "?") for v in videos.values()}
    print(f"{len(videos)} clips, {len(wanted)} of them contributing frames")
    print(f"licences: {', '.join(sorted(licences))}")
    print(f"uploaders: {', '.join(sorted({v.get('uploader', '?').strip() for v in videos.values()}))}")
    if unused:
        print(f"note: {len(unused)} sidecars have no frames in this corpus ({unused[0]} ...)")
    print(f"\nwrote {os.path.relpath(manifest, ROOT)}")
    print(f"wrote {os.path.relpath(args.doc, ROOT)}")


if __name__ == "__main__":
    main()
