"""Promote M1/M2 research outputs into the artifacts the deployed service reads.

This is the **ingest** half of `experiments/M2_DESIGN.md` §3, run offline and once. It writes the
three-table contract from §4 plus the two files rejection needs, into `data/artifacts/`:

    frames.jsonl        frame_id (PK) · video_id · scene_id · timestamp_s
    vectors.npy         frame_id -> 768-d SigLIP2, row order == frames.jsonl
    metadata.jsonl      frame_id -> detected objects + positions + scene tags (§11.2)
    captions.jsonl      frame_id -> Florence-2 caption          (rejection, M2 §6.1)
    caption_vectors.npy frame_id -> 384-d MiniLM, same row order

Why a promotion step exists at all: `experiments/m1/outputs/` is gitignored, so the service cannot
read it and the deploy would have nothing to search. And two of these cannot be computed at query
time even in principle — `metadata.jsonl` needs the camera intrinsics out of nuScenes, which the
deployed service has no copy of. Ingest is where facts about the corpus get made; query only reads.

Runs in the **research** environment (numpy, PIL, nuscenes-devkit), not the app venv — the service
deliberately does not depend on the devkit:

    C:/Users/Precision/ssv/Scripts/python.exe scripts/promote_artifacts.py \
        --dataroot VinUni_Applied_AI/02_build/data/nuscene/mini

Idempotent: re-running overwrites cleanly and skips thumbnails that already exist.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from typing import NamedTuple

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M1 = os.path.join(REPO, "experiments", "m1")
SIGLIP_STEM = "emb_openclip_ViT-B-16-SigLIP2_webli"
CAPTION_STEM = "emb_caption_Florence-2-base_all-MiniLM-L6-v2"
# Defaults describe the nuScenes-mini corpus this script was written for. They are DEFAULTS, not
# facts: promoting a different corpus must pass --retrieval and --query-set, or provenance.json
# would claim these artifacts came from an experiment measured on a different set of frames — worse
# than no provenance, because it looks authoritative.
PROVENANCE = {
    "retrieval": "40095e80",
    "rejection_ablation": "rejection_ablation.json",
    "query_set": "v3 (2026-07-31)",
    # What this corpus is, recorded by the step that knows. This script promotes nuScenes and only
    # nuScenes — it takes a nuScenes `--dataroot`, a `v1.0-*` version, and writes 32-hex sample
    # tokens as frame ids — so naming it here is a statement of fact, not a guess about a directory.
    #
    # It is written *down* rather than assumed by a reader, and that distinction is the whole point.
    # The frame card used to print a hardcoded `nuScenes (Production)`, which was false for every
    # frame the moment a second corpus was merged in. A name in provenance travels with the corpus
    # it describes, so it cannot be wrong about a different one.
    "corpus_name": "nuScenes",
}
# A nuScenes sample token plus a camera suffix. Kept identical to `src/api/routes.py:_FRAME_ID`,
# so an id this script is willing to write is exactly one the API is willing to serve.
FRAME_ID = re.compile(r"^[0-9a-f]{32}_[A-Z_]+$")


def load_manifest(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_frames(rows: list[dict]) -> list[dict]:
    """Manifest rows -> §4's `frames` table.

    `timestamp` in the manifest is an absolute epoch in microseconds, which is meaningless to a UI.
    §4 asks for "offset into the source video", so it is rebased per scene: the earliest keyframe of
    each clip becomes 0.0. video_id and scene_id are both the nuScenes scene token here because on
    this corpus one clip *is* one scene; they are kept as separate fields because at archive scale
    they diverge — M2_DESIGN §7 notes the right diversity grouping is then a time bucket within a
    clip, which is a change to scene_id alone.
    """
    origin: dict[str, int] = {}
    for r in rows:
        tok = r["scene_token"]
        origin[tok] = min(origin.get(tok, r["timestamp"]), r["timestamp"])
    return [
        {
            "frame_id": r["item_id"],
            "video_id": r["scene_token"],
            "scene_id": r["scene_token"],
            "timestamp_s": round((r["timestamp"] - origin[r["scene_token"]]) / 1e6, 3),
        }
        for r in rows
    ]


def load_embeddings(stem: str, ids: list[str], root: str) -> np.ndarray:
    """Load a cached embedding matrix and reorder its rows to match `ids`."""
    npy = os.path.join(root, "outputs", f"{stem}.npy")
    meta = os.path.join(root, "outputs", f"{stem}.meta.json")
    if not (os.path.exists(npy) and os.path.exists(meta)):
        sys.exit(f"missing {stem} in {root}/outputs/ — run scripts/run_ingest.py first")
    emb = np.load(npy, allow_pickle=False)
    with open(meta) as f:
        cached_ids = json.load(f)["ids"]
    if cached_ids == ids:
        return emb
    pos = {i: n for n, i in enumerate(cached_ids)}
    missing = [i for i in ids if i not in pos]
    if missing:
        sys.exit(f"{stem} is missing {len(missing)} of the manifest's frames — re-encode")
    return emb[[pos[i] for i in ids]]


def fp16_is_safe(emb: np.ndarray, top_k: int = 10) -> tuple[bool, int]:
    """Does storing vectors as fp16 leave the ranking identical? Returns (safe, n_probes_changed).

    §4 specifies fp16 on disk, and at 7.2M frames that is 22 GB against 11 GB — a decision worth
    making. At 404 frames it saves 600 KB, which is worth nothing, so it is only taken if it is
    free. `float16` carries ~3 decimal digits and these cosine scores sit in a narrow band with
    small gaps between neighbours, so near-ties genuinely can flip; that is measured here rather
    than assumed.

    Probes are the corpus vectors themselves. Random unit vectors in 768-d are near-orthogonal to
    everything and would produce an unrealistically flat score distribution — the easy case. Real
    queries land close to some frames, which is exactly where rounding decides orderings.
    """
    lo = emb.astype(np.float16).astype(np.float32)
    changed = 0
    for probe in range(emb.shape[0]):
        a = np.argsort(-(emb @ emb[probe]))[:top_k]
        b = np.argsort(-(lo @ lo[probe]))[:top_k]
        if not np.array_equal(a, b):
            changed += 1
    return changed == 0, changed


class Paths(NamedTuple):
    """Where one promotion run reads research artifacts from, and writes service artifacts to.

    Bundled rather than passed separately because the two travel together through every writer, and
    `--research-root` exists precisely so they can differ: a new corpus is ingested into its own
    workdir so it cannot overwrite the caches backing M1's published experiments.
    """

    research: str
    artifacts: str


def write_metadata(nusc, rows: list[dict], paths: Paths) -> None:
    """Detector boxes -> objects + relations, using **each frame's own** camera intrinsics.

    Calibration is a property of the log, not of the dataset. trainval carries three distinct
    CAM_FRONT intrinsic matrices with `cx` spanning 786.7 to 826.6, and even v1.0-mini carries two
    (816.3 and 826.6).

    This previously read `nusc.sample[0]`'s calibration once and applied it to every frame, which
    mislabels every frame from any other log. Not hypothetical on the current corpus: **163 of the
    404 shipped frames — 40% — come from the second calibration.** `M2_DESIGN` §9.2 records that the
    ±30° band falls at image x ≈ 85 and 1547 of 1600, so `front_left` / `front_right` are decided
    within a few dozen pixels of the frame edge, which is exactly where a 10 px (mini) or 40 px
    (trainval) shift in `cx` pushes a box across the boundary.
    """
    sys.path.insert(0, M1)
    from scenesearch.metadata.extract import DetectionStore, record_from_detections

    cache = os.path.join(paths.research, "artifacts/metadata/detections_frcnn.jsonl")
    dets = DetectionStore(cache_path=cache).detections_for([r["image_path"] for r in rows])
    with open(os.path.join(paths.artifacts, "metadata.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            sd = nusc.get("sample_data", nusc.get("sample", r["sample_token"])["data"]["CAM_FRONT"])
            k = np.array(nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])["camera_intrinsic"])
            rec = record_from_detections(
                dets[os.path.basename(r["image_path"])], k[0, 0], k[0, 2], sd["width"], sd["height"]
            )
            f.write(json.dumps({"frame_id": r["item_id"], **rec}) + "\n")


def detector_vocabulary() -> list[str]:
    """The categories `write_metadata` above can emit, read from the mapping it actually uses.

    Read rather than restated: a hand-copied list here would keep claiming six categories after a
    detector swap widened or narrowed them, and it is consulted at query time to *refuse* a search.
    A stale vocabulary would refuse categories the corpus holds.
    """
    sys.path.insert(0, M1)
    from scenesearch.metadata.extract import COCO_TO_VOCAB

    return sorted(set(COCO_TO_VOCAB.values()))


def write_captions(rows: list[dict], paths: Paths) -> None:
    """Re-key the research caption cache from image basename to frame_id."""
    sys.path.insert(0, M1)
    from scenesearch.pipelines.caption_retrieval import _strip_pad

    out_path = os.path.join(paths.artifacts, "captions.jsonl")
    src = os.path.join(paths.research, "artifacts/captions/florence2_base_detailed.jsonl")
    by_image: dict[str, str] = {}
    with open(src, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                by_image[row["image"]] = _strip_pad(row["caption"])
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(
                json.dumps({"frame_id": r["item_id"], "caption": by_image[os.path.basename(r["image_path"])]}) + "\n"
            )


class ThumbnailSpec(NamedTuple):
    """Where thumbnails go, how wide, and the detections that decide what gets redacted.

    Bundled rather than passed as four arguments, and `detections` is not optional: a signature that
    lets redaction be omitted is a signature that will eventually be called without it, and the
    failure — an unredacted face on a public URL — is not one that shows up in a test run.
    """

    out_dir: str
    width: int
    privacy_detections: dict[str, list[dict]]
    retrieval_detections: dict[str, list[dict]]
    force: bool = False


def write_thumbnails(rows: list[dict], spec: ThumbnailSpec) -> int:
    """Downscaled, **redacted** JPEGs for the UI. nuScenes is CC BY-NC-SA 4.0 — see README.

    Faces and licence plates are mosaicked at source resolution before the downscale, so no file
    on disk ever contains the original pixels — `scripts/anonymise.py` has the geometry and the
    limits. This is the only image the service serves, in the grid and in the detail modal alike.

    Unlike the rest of this script, an existing thumbnail is **skipped**, which was safe when the
    output was a pure function of the source and is not any more: a thumbnail written before
    redaction existed would survive a re-promotion untouched. `--force-thumbs` is the way to
    regenerate, and `scripts/anonymise.py` rewrites them all without re-running the promotion.
    """
    from anonymise import redact, regions_for
    from PIL import Image

    os.makedirs(spec.out_dir, exist_ok=True)
    written = 0
    for r in rows:
        # item_id builds a filename, so validate its shape before writing 404 files with it. It is
        # not attacker-controlled — it comes from a manifest this repo generates from nuScenes
        # sample tokens — but a malformed or hand-edited manifest would otherwise scatter JPEGs
        # across the filesystem, and finding that afterwards is far harder than refusing it here.
        if not FRAME_ID.match(r["item_id"]):
            raise ValueError(f"manifest item_id is not a frame id: {r['item_id']!r}")
        dst = os.path.join(spec.out_dir, f"{r['item_id']}.jpg")
        if os.path.exists(dst) and not spec.force:
            continue
        with Image.open(r["image_path"]) as im:
            im = im.convert("RGB")
            key = os.path.basename(r["image_path"])
            redact(im, regions_for(spec.privacy_detections.get(key, []) + spec.retrieval_detections.get(key, [])))
            im.thumbnail((spec.width, spec.width * im.height // im.width), Image.LANCZOS)
            im.save(dst, "JPEG", quality=80, optimize=True)
        written += 1
    return written


def resolve_paths(nusc, rows: list[dict]) -> None:
    """Rewrite each row's `image_path` from the devkit, in place.

    The manifest stores an **absolute** path captured when it was generated, so it silently goes
    stale the moment the dataroot moves — which is how splitting `data/nuscene/` into one directory
    per version broke this script while `audit_corpus.py`, which reads the dataroot directly, kept
    passing.

    It is also what multi-blob needs: frames from a downloaded blob live wherever that blob was
    merged to, and no manifest written earlier can know that. Asking the devkit makes the answer a
    function of `--dataroot` instead of of history.
    """
    for r in rows:
        sd_token = nusc.get("sample", r["sample_token"])["data"]["CAM_FRONT"]
        r["image_path"] = nusc.get_sample_data_path(sd_token)


def select_scenes(nusc, rows: list[dict], spec: str) -> list[dict]:
    """Keep only rows whose scene is listed in `spec`, a file of scene names or tokens.

    A merged trainval dataroot holds whatever blobs were extracted into it, and the corpus we want
    is rarely all of them — part 7 is 85 clear-daytime scenes that would dilute condition coverage,
    and mini overlaps parts 9 and 10. Filtering here keeps that choice in one place instead of
    encoding it in which files happen to sit on disk.

    Accepts either form because `scripts/measure/audit_scenes.py --parts` reports names (`scene-0894`) while
    the manifest and metadata tables use tokens.
    """
    wanted: set[str] = set()
    with open(spec, encoding="utf-8") as f:
        for line in f:
            entry = line.strip()
            if entry and not entry.startswith("#"):
                wanted.add(entry)
    by_name = {s["name"]: s["token"] for s in nusc.scene}
    unknown = [w for w in wanted if w not in by_name and w not in by_name.values()]
    if unknown:
        sys.exit(f"--scenes lists {len(unknown)} unknown scenes, first: {unknown[0]!r}")
    tokens = {by_name.get(w, w) for w in wanted}
    kept = [r for r in rows if r["scene_token"] in tokens]
    if not kept:
        sys.exit("--scenes matched no manifest rows; is the manifest built from this dataroot?")
    return kept


def main() -> None:
    # Imported here, like `redact`/`regions_for` below: this module has no top-level sys.path setup
    # and relies on `scripts/` being sys.path[0] when run directly.
    from anonymise import THUMB_WIDTH

    ap = argparse.ArgumentParser()
    ap.add_argument("--dataroot", required=True)
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--out", default=os.path.join(REPO, "data"))
    ap.add_argument("--thumb-width", type=int, default=THUMB_WIDTH)
    ap.add_argument(
        "--force-thumbs",
        action="store_true",
        help="regenerate thumbnails that already exist — needed after any change to "
        "redaction, since an existing file is otherwise left untouched",
    )
    ap.add_argument("--scenes", metavar="FILE", help="restrict to the scenes named or tokenised in FILE, one per line")
    ap.add_argument(
        "--research-root", default=M1, help="workdir holding artifacts/ and outputs/ (default: experiments/m1)"
    )
    ap.add_argument(
        "--retrieval",
        default=PROVENANCE["retrieval"],
        help="experiment id these vectors were measured under; pass it for any corpus "
        "other than the mini default, or provenance.json will misattribute them",
    )
    ap.add_argument(
        "--query-set",
        default=PROVENANCE["query_set"],
        help="query set version the measurement used, e.g. 'v4 (2026-08-01)'",
    )
    ap.add_argument("--force-fp32", action="store_true", help="skip the fp16 check and store vectors as fp32")
    args = ap.parse_args()

    art = os.path.join(args.out, "artifacts")
    os.makedirs(art, exist_ok=True)
    paths = Paths(research=os.path.abspath(args.research_root), artifacts=art)
    rows = load_manifest(os.path.join(paths.research, "artifacts/dataset/manifest.jsonl"))
    # Built once, up front: the scene filter needs it, and so does per-frame calibration lookup.
    from nuscenes.nuscenes import NuScenes

    nusc = NuScenes(version=args.version, dataroot=args.dataroot, verbose=False)
    if args.scenes:
        before = len(rows)
        rows = select_scenes(nusc, rows, args.scenes)
        print(
            f"[scenes]  {len({r['scene_token'] for r in rows})} scenes selected "
            f"({len(rows)} of {before} manifest frames)"
        )
    resolve_paths(nusc, rows)
    ids = [r["item_id"] for r in rows]
    print(f"[frames]  {len(rows)} keyframes")

    frames = build_frames(rows)
    with open(os.path.join(art, "frames.jsonl"), "w", encoding="utf-8") as f:
        for fr in frames:
            f.write(json.dumps(fr) + "\n")

    emb = load_embeddings(SIGLIP_STEM, ids, paths.research)
    if args.force_fp32:
        safe, changed = False, -1
    else:
        safe, changed = fp16_is_safe(emb)
    dtype = np.float16 if safe else np.float32
    print(
        f"[vectors] {emb.shape} fp16 {'SAFE' if safe else 'REJECTED'}"
        + ("" if safe else f" — {changed} of {emb.shape[0]} probes reranked; storing fp32")
    )
    np.save(os.path.join(art, "vectors.npy"), emb.astype(dtype))
    np.save(os.path.join(art, "caption_vectors.npy"), load_embeddings(CAPTION_STEM, ids, paths.research).astype(dtype))

    write_metadata(nusc, rows, paths)
    write_captions(rows, paths)
    print("[metadata] + [captions] written")

    # Read after `write_metadata`, which is what fills any gap in the cache. Read from the file
    # rather than kept from that call so the two passes cannot disagree about what was detected —
    # one of them decides the metadata, the other decides what gets redacted.
    from anonymise import load_detections
    from privacy_detector import privacy_config_from_cache

    privacy_cache = os.path.join(paths.research, "artifacts/metadata/privacy_detections.jsonl")
    if not os.path.exists(privacy_cache):
        sys.exit("missing dedicated privacy cache — run run_ingest.py with privacy models first")
    privacy_detections = load_detections(privacy_cache, require_privacy=True)
    missing_privacy = [r for r in rows if os.path.basename(r["image_path"]) not in privacy_detections]
    if missing_privacy:
        sys.exit(f"privacy cache is missing {len(missing_privacy)} selected frames; refusing unverified thumbnails")

    retrieval_cache = os.path.join(paths.research, "artifacts/metadata/detections_frcnn.jsonl")
    if not os.path.exists(retrieval_cache):
        sys.exit(
            "missing retrieval cache — the head band that covers turned-away pedestrians "
            "comes from its person boxes, and redacting without it under-blurs silently"
        )

    spec = ThumbnailSpec(
        out_dir=os.path.join(args.out, "thumbs"),
        width=args.thumb_width,
        privacy_detections=privacy_detections,
        retrieval_detections=load_detections(retrieval_cache),
        force=args.force_thumbs,
    )
    n = write_thumbnails(rows, spec)
    print(f"[thumbs]  {n} generated ({len(rows) - n} already present) at {args.thumb_width}px, faces/plates redacted")

    # Copy the cache in beside the artifacts it certifies. `verify_privacy_assets.py` checks the
    # *promoted* corpus, and a gate that can only run with a path into experiments/m1/runs/ cannot
    # be a release gate: the deployed set would be verified against whatever research run happened
    # to be on that machine, or not verified at all.
    shutil.copyfile(privacy_cache, os.path.join(art, "privacy_detections.jsonl"))

    with open(os.path.join(art, "provenance.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                **PROVENANCE,
                "retrieval": args.retrieval,
                "query_set": args.query_set,
                "n_frames": len(rows),
                "vector_dtype": str(np.dtype(dtype)),
                "encoder": "openclip:ViT-B-16-SigLIP2:webli",
                # Which corpus this is, so a deployed answer traces to a scene set and not just
                # to "whatever the dataroot held that day".
                "version": args.version,
                "n_scenes": len({r["scene_token"] for r in rows}),
                "scene_filter": os.path.basename(args.scenes) if args.scenes else None,
                # Where the embeddings came from, relative to the repo. tests/test_services/
                # test_fidelity.py re-reads that cache to prove promotion did not reorder a row,
                # and it can only do that if the artifacts say which run produced them — a second
                # corpus in experiments/m1/runs/ makes a hardcoded path silently wrong.
                "research_outputs": os.path.relpath(paths.research, REPO).replace(os.sep, "/"),
                # What the metadata above *can* say, which is not the same as what it does say.
                # `record_from_detections` maps six COCO classes, so `construction_vehicle`,
                # `traffic_cone` and `barrier` are unreachable however many frames are ingested —
                # while `llm.py` still offers all nine to the parser. Declaring the vocabulary is
                # what lets `rejection.contradicted` refuse those three as fact instead of
                # answering them confidently from captions that never mention an absence.
                "detector": {
                    "model": "mobilenet_v3",
                    "vocabulary": detector_vocabulary(),
                    "cache": "detections_frcnn.jsonl",
                },
                "privacy": privacy_config_from_cache(privacy_cache),
            },
            f,
            indent=2,
        )

    # Scene tags run last, and that ordering is load-bearing twice over. They are a second pass over
    # `metadata.jsonl`, so they must follow the pass that writes it — otherwise `write_metadata`
    # overwrites them and the corpus ships with a `time` field the filter trusts and nothing wrote.
    # And `write_scene_tags` appends its own block to `provenance.json`, so it must also follow the
    # dump above, which replaces that file wholesale. See M2_DESIGN §11.2.
    from tag_scenes import TAGGED_AXES, write_scene_tags

    write_scene_tags(art)
    print(f"[tags]    scene tags on {list(TAGGED_AXES)}")

    total = sum(os.path.getsize(os.path.join(art, x)) for x in os.listdir(art))
    print(f"\nwritten -> {art}/  ({total / 1e6:.1f} MB) + thumbs/")


if __name__ == "__main__":
    main()
