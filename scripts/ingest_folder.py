"""Ingest a folder of frames — the devkit-free path, for footage that is not nuScenes.

**Interpreter: `C:/Users/Precision/ssv`, not `.venv`.** It needs CUDA, `ultralytics` and the
`scenesearch` package in `experiments/m1/` — which is in this repository and is put on `sys.path`
below, at runtime. An editor pointed at `.venv` cannot execute that insert, so it underlines those
imports in red. That is expected and does not mean this file is dead: `--help` runs clean under
`ssv`, and `tests/test_services/test_ingest_folder.py` exercises the pure parts under `.venv`. See
`scripts/README.md` and `pyrightconfig.json`.

`promote_artifacts.py` is the nuScenes path and cannot leave it: it enters through the devkit for
the manifest and reads `fx`/`cx` per frame from `calibrated_sensor`. M2_DESIGN §10.5 measures the
whole coupling and finds it is **two seams, not a rewrite** — everything expensive (`stage_detect`,
`stage_caption`, `stage_embed`) already takes plain image paths. This script replaces the two seams
and reuses the rest, so the generic path runs the identical detector, captioner and encoder.

**The declared field of view is required, and ≤ 60° is refused rather than warned about.** §10.5
measured why: with `cx = W/2` the ±30° relation bands land at `W/2 ± fx·tan30°`, and once
`hfov ≤ 60°` they fall outside the image, so every object becomes `front` and §9's filter silently
becomes a no-op — while precision stays at 96%, because the `front` labels it still emits are
correct. Nothing looks wrong. A warning in a log is not a control for that; a refusal is. Getting
within ±2° is harmless (96–97% exact agreement), which is what makes "declare your camera" a
workable ask.

**The input contract, which is also the Module 1 → Module 2 handoff.** A directory of images, and
optionally a `frames.json` sidecar beside them:

    {"video_id": "clip-01", "fps": 2.0, "hfov_deg": 120.0,
     "frames": [{"file": "000001.jpg", "timestamp_s": 0.0}, ...]}

Without the sidecar, frames are taken in lexical order at `--fps`, and `--fov` must be given.
`scripts/extract_keyframes.py` writes the sidecar.

**Frame ids are derived, not taken from filenames.** `api/routes.py:_FRAME_ID` admits only
`[0-9a-f]{32}_[A-Z_]+` — a whitelist that is the thumbnail endpoint's path-traversal defence, so a
corpus of `frame_0001.jpg` would ingest happily and then 404 on every image. Ids are the md5 of
`video_id:filename`, which is stable across re-runs and re-encodes and cannot collide across videos.

**`scene_id` is a time bucket widened to fit the content, not the video.** Diversity (§7) groups by
`scene_id`; on one continuous clip a single group makes the cap meaningless. §4 already anticipated
this — "at archive scale they diverge, and the right grouping is then a time bucket within a clip" —
so this is that case arriving, not a workaround. What §4 did not anticipate is a *stopped* vehicle,
where the clock keeps advancing while the view does not: `regroup` therefore unions the buckets each
near-duplicate run spans, after the vectors exist. See `regroup_scenes.py` and
`docs/tasks/task-stationary-runs.md`.

**Several videos make one corpus, and each keeps its own camera.** `--frames` takes any number of
directories; every one becomes a `video_id`, declares its own FOV through its sidecar, and lands in
its own subdirectory of `--workdir`. That last part is load-bearing rather than tidy: the detector
and caption caches are keyed by *image basename*, and `extract_keyframes.py` numbers every clip from
`000001.jpg`, so a shared workdir would serve the first video's boxes and captions for the second and
report a completely successful ingest. `by_frame_id` translates each cache into globally unique ids
before anything is merged.

Runs in the **research** environment, which has the detector, captioner and encoder:

    C:/Users/Precision/ssv/Scripts/python.exe scripts/ingest_folder.py \
        --frames data/incoming/clip-01 --fov 120 --workdir experiments/m1/runs/archive \
        --out data/staging/archive

    # two clips, one searchable corpus; FOV comes from each sidecar
    ... --frames data/incoming/clip-01 data/incoming/clip-02 --workdir experiments/m1/runs/archive
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from typing import NamedTuple

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "experiments", "m1"))

from _console import use_utf8  # noqa: E402, F401 -- console encoding; imported for effect

# Re-exported, not merely used: `test_ingest_folder.py` and `docs/handover/keyframe-handoff-contract.md` §2
# both name `ingest_folder.MIN_FOV_DEG`, so this module stays the published home of the constant
# even though the definition moved to `_fov` to be shared with the extractor.
from _fov import MIN_FOV_DEG, check_fov  # noqa: E402, F401 -- see above
from anonymise import (  # noqa: E402
    FACE_MARGIN_PX,
    HEAD_FRACTION,
    MOSAIC_SAMPLES,
    PERSON_LABELS,
    THUMB_WIDTH,
    load_detections,
    redact,
    regions_for,
)
from privacy_detector import PrivacyDetector, config_from_environment, load_cache  # noqa: E402
from promote_artifacts import CAPTION_STEM, SIGLIP_STEM, load_embeddings  # noqa: E402
from regroup_scenes import regroup  # noqa: E402
from scenesearch.metadata.extract import (  # noqa: E402
    BASELINE_DETECTOR,
    COCO_TO_VOCAB,
    DEFAULT_DETECTOR,
    DETECTORS,
)
from tag_scenes import write_scene_tags  # noqa: E402

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")
SIDECAR = "frames.json"

# Seconds per diversity group. nuScenes clips are ~20 s and one clip is one scene there, so this
# reproduces the grouping the diversity cap was measured against (§7) on continuous footage.
#
# This is the *starting* grouping, not the final one: elapsed time only stands in for changed content
# while the camera is moving, and a stopped vehicle puts a bucket boundary in the middle of one
# frozen moment. `regroup` (see `regroup_scenes.py`) then unions the buckets a near-duplicate run
# spans, so do not read a `scene_id` in a written corpus as necessarily being 20 seconds wide.
SCENE_BUCKET_S = 20.0

CAMERA = "CAM_FRONT"

# MiniLM's width, and the filename `src/services/search/captions.py` appends deferred captions to.
# Duplicated rather than imported: that module reaches `src.config` and therefore pydantic, which
# this script's research environment does not have — the same reason `filters.py` is re-exported
# lazily. Both values are asserted against their real definitions in the tests.
CAPTION_DIM = 384
CAPTIONS_DEFERRED = "captions_deferred.jsonl"


def frame_id_for(video_id: str, filename: str) -> str:
    """A stable id the API will actually serve.

    md5 of `video_id:filename` rather than of the pixels: a re-encode by the extractor would change
    content bytes and orphan every review verdict and thumbnail keyed to the old id, while the pair
    stays put. Distinct videos cannot collide because `video_id` is inside the hash.
    """
    digest = hashlib.md5(f"{video_id}:{filename}".encode(), usedforsecurity=False).hexdigest()
    return f"{digest}_{CAMERA}"


def read_sidecar(frames_dir: str) -> dict | None:
    path = os.path.join(frames_dir, SIDECAR)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_rows(frames_dir: str, video_id: str, fps: float) -> list[dict]:
    """One row per frame: the shape `stage_*` and the artifact writers already consume.

    The sidecar wins where it exists, because the extractor knows the real timestamps and lexical
    order only approximates them — a clip sampled at a variable rate would otherwise be given
    evenly spaced times that quietly misplace every frame in the UI.
    """
    sidecar = read_sidecar(frames_dir)
    if sidecar:
        video_id = sidecar.get("video_id", video_id)
        listed = [(e["file"], float(e["timestamp_s"])) for e in sidecar["frames"]]
    else:
        names = sorted(n for n in os.listdir(frames_dir) if n.lower().endswith(IMAGE_SUFFIXES))
        listed = [(n, i / fps) for i, n in enumerate(names)]
    if not listed:
        sys.exit(f"no images in {frames_dir}")
    return [
        {
            "item_id": frame_id_for(video_id, name),
            "image_path": os.path.join(frames_dir, name),
            "video_id": video_id,
            "timestamp_s": round(ts, 3),
            "scene_id": f"{video_id}#{int(ts // SCENE_BUCKET_S):04d}",
        }
        for name, ts in listed
    ]


def by_frame_id(rows: list[dict], by_image: dict) -> dict[str, list]:
    """Re-key a per-video cache from image basename to `frame_id`.

    **This is what makes more than one video safe.** `DetectionStore` and `CaptionRetrievalEncoder`
    key their JSONL caches by `os.path.basename`, and `extract_keyframes.py` numbers every clip from
    `000001.jpg` — so two videos sharing one cache would silently serve the *first* video's boxes and
    captions for the second, and the ingest would look entirely successful. Each video therefore gets
    its own workdir, and its cache is translated into globally unique ids here before anything merges.
    """
    return {row["item_id"]: by_image.get(os.path.basename(row["image_path"]), []) for row in rows}


def write_metadata(rows: list[dict], detections: dict, out_path: str) -> None:
    """Detector boxes → objects + relations, with `fx` from the declared FOV instead of a calibration.

    Width is read per image rather than once: a folder can hold more than one resolution, and `fx`
    depends on width. `hfov_deg` is read per *row* for the same reason one level up — with several
    videos in one corpus each has its own camera, and applying one clip's FOV to another's frames is
    the §10.5 failure applied to a subset, which is harder to notice than getting it wrong everywhere.

    `bonnet_top` is read per row for the same reason again — it is where *that* camera's bodywork
    starts, and a corpus can hold clips from more than one car.
    """
    from PIL import Image
    from scenesearch.metadata.extract import drop_ego_boxes, record_from_detections

    with open(out_path, "w", encoding="utf-8") as f:
        for row in rows:
            with Image.open(row["image_path"]) as im:
                width, height = im.width, im.height
            fx = (width / 2) / math.tan(math.radians(row["hfov_deg"] / 2))
            dets = drop_ego_boxes(detections.get(row["item_id"], []), (width, height), row["bonnet_top"])
            record = record_from_detections(dets, fx, width / 2, width, height)
            f.write(json.dumps({"frame_id": row["item_id"], **record}) + "\n")


def write_frames(rows: list[dict], out_path: str) -> None:
    """§4's `frames` table. `scene_id` is the content group (see `regroup`); `video_id` stays the clip."""
    with open(out_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(
                json.dumps(
                    {
                        "frame_id": row["item_id"],
                        "video_id": row["video_id"],
                        "scene_id": row["scene_id"],
                        "timestamp_s": row["timestamp_s"],
                    }
                )
                + "\n"
            )


def read_caption_cache(cache_path: str) -> dict[str, str]:
    """image basename → caption, from one video's cache. Absent file means nothing captioned."""
    from scenesearch.pipelines.caption_retrieval import _strip_pad

    by_image: dict[str, str] = {}
    if not os.path.exists(cache_path):
        return by_image
    with open(cache_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                by_image[row["image"]] = _strip_pad(row["caption"])
    return by_image


def write_captions(rows: list[dict], captions: dict[str, str], out_path: str) -> None:
    """§4's caption column, already keyed by `frame_id` — see `by_frame_id`."""
    with open(out_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps({"frame_id": row["item_id"], "caption": captions.get(row["item_id"], "")}) + "\n")


class RedactionCaches(NamedTuple):
    """The two detection sources a redaction pass needs, keyed by frame id.

    `privacy` carries face and licence-plate boxes; `retrieval` carries the person boxes whose top
    band covers a pedestrian the face detector could not see. Neither is optional — §the module
    docstring of `anonymise.py` records what happens when only the first is used.
    """

    privacy: dict[str, list[dict]]
    retrieval: dict[str, list[dict]]


def write_thumbnails(rows: list[dict], detections: RedactionCaches, out_dir: str, width: int = THUMB_WIDTH) -> int:
    """Redacted thumbnails, same contract as the nuScenes path — faces, plates and person heads.

    Both caches travel together in one object rather than as two dicts, so a caller cannot pass the
    privacy cache and forget the retrieval one: the result would be silently under-blurred
    thumbnails, which look exactly like correctly redacted ones.
    """
    from PIL import Image

    os.makedirs(out_dir, exist_ok=True)
    stats = {"frames": 0, "privacy_unverified": 0, "with_region": 0, "regions": 0, "faces": 0, "plates": 0, "heads": 0}
    for row in rows:
        dets = detections.privacy.get(row["item_id"], []) + detections.retrieval.get(row["item_id"], [])
        regions = regions_for(dets)
        stats["frames"] += 1
        stats["with_region"] += 1 if regions else 0
        stats["regions"] += len(regions)
        stats["faces"] += sum(1 for d in dets if d.get("label") == "face")
        stats["plates"] += sum(1 for d in dets if d.get("label") == "license_plate")
        stats["heads"] += sum(1 for d in dets if d.get("label") in PERSON_LABELS)
        with Image.open(row["image_path"]) as im:
            im = im.convert("RGB")
            redact(im, regions)
            im.thumbnail((width, width * im.height // im.width), Image.LANCZOS)
            im.save(os.path.join(out_dir, f"{row['item_id']}.jpg"), "JPEG", quality=80, optimize=True)
    return stats


def stamp_anonymisation(provenance_path: str, stats: dict) -> None:
    """Append the redaction certificate, the way `write_scene_tags` appends its own block.

    Without it a corpus from this path carries redacted thumbnails and no evidence that it does, and
    `verify_privacy_assets.py` refuses it — correctly, since "no certificate" and "not redacted" are
    the same thing to a release gate. `privacy_unverified` is 0 by construction: `ingest_one` exits
    before this point if any frame is missing from the privacy cache.
    """
    with open(provenance_path, encoding="utf-8") as f:
        prov = json.load(f)
    prov["anonymisation"] = {
        "geometry": f"dedicated face/plate boxes expanded by <= {FACE_MARGIN_PX}px, "
        f"unioned with person box top {HEAD_FRACTION:.2f} (head)",
        "method": f"mosaic to <= {MOSAIC_SAMPLES} samples per side, at source resolution",
        "source": "privacy_detections.jsonl (face, licence plate) "
        "unioned with person boxes from detections_frcnn.jsonl",
        "frames": stats["frames"],
        "frames_with_a_region": stats["with_region"],
        "frames_privacy_verified": stats["frames"] - stats["privacy_unverified"],
        "privacy_unverified": stats["privacy_unverified"],
        "regions": stats["regions"],
        "faces": stats["faces"],
        "plates": stats["plates"],
        "heads": stats["heads"],
        "limit": "coverage is the union of person-box recall and dedicated detector recall; "
        "unverified frames must not be published",
    }
    with open(provenance_path, "w", encoding="utf-8") as f:
        json.dump(prov, f, indent=2)


def run_stages(rows: list[dict], workdir: str, args=None) -> dict[str, str]:
    """Detector, captioner, encoders — the three expensive stages, unchanged from `run_ingest.py`.

    Imported rather than reimplemented: they are what makes the generic path produce vectors in the
    *same* space as the nuScenes path, and a second copy would be free to drift out of it.

    `--skip-captions` drops the captioner, which is ~83% of the wall clock (15m05s of the 18-minute
    834-frame run). Rejection then captions on demand at query time — `src/services/search/captions.py`
    has the whole argument, and §6.1's option B is what makes it sound rather than a shortcut.

    **The detection cache is named after the backbone**, not `detections_frcnn.jsonl` for whatever
    ran. One file per detector is the invariant `_read_cache` enforces from the other side, and the
    generic name is what made the 08-08 mixing bug possible: it parses cleanly, matches nothing, and
    quietly produces the wrong artifact. `mobilenet_v3` keeps the historical filename so existing
    workdirs still resolve.
    """
    from run_ingest import stage_caption, stage_detect, stage_embed

    detector = getattr(args, "detector", DEFAULT_DETECTOR)
    # Anchored to `BASELINE_DETECTOR`, not to the default: the historical filename belongs to
    # `mobilenet_v3`, which is what the docstring above says and what every existing workdir holds.
    # Spelled `== DEFAULT_DETECTOR` it inverted the moment the default moved (2026-08-20), writing
    # resnet50_v2 boxes into `detections_frcnn.jsonl` — the 08-08 mixing bug, rebuilt.
    stem = "detections_frcnn" if detector == BASELINE_DETECTOR else f"detections_{detector}"
    captions = not args.skip_captions
    caches = {
        "detections": os.path.join(workdir, f"artifacts/metadata/{stem}.jsonl"),
        "privacy": os.path.join(workdir, "artifacts/metadata/privacy_detections.jsonl"),
        "captions": os.path.join(workdir, "artifacts/captions/florence2_base_detailed.jsonl"),
        "outputs": os.path.join(workdir, "outputs"),
    }
    for path in caches.values():
        os.makedirs(path if path.endswith("outputs") else os.path.dirname(path), exist_ok=True)

    paths = [r["image_path"] for r in rows]
    stage_detect(paths, caches["detections"], model=detector)
    PrivacyDetector(args.privacy_config, args.privacy_device).detect_to_cache(paths, caches["privacy"])
    if captions:
        stage_caption(paths, caches["captions"])
    stage_embed(rows, caches["outputs"], caches["captions"], captions=captions)
    return caches


def write_empty_captions(rows: list[dict], out_path: str) -> None:
    """`captions.jsonl` with every caption blank — the shape a deferred corpus starts in.

    Written rather than omitted so `Corpus.load`'s row-count check still has all three artifacts to
    compare. An empty string means "not captioned yet" and is what `ensure_captions` looks for.
    """
    with open(out_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps({"frame_id": row["item_id"], "caption": ""}) + "\n")


def write_provenance(
    rows: list[dict], out_path: str, captions_deferred: bool = False, privacy_config=None, detector: str | None = None
) -> None:
    """What this corpus is and how its geometry was obtained.

    `intrinsics` is the field that matters on a re-read: "declared" versus nuScenes' "per-frame
    calibration" is the difference between a measured relation and an assumed one, and §10.5 shows
    the assumption is worth 96.8% at best and 74.2% if the declaration is wrong.

    `hfov_deg` is recorded **per video**, not once. A corpus can hold clips from several cameras, and
    a single number would describe all but one of them wrongly while looking authoritative — the same
    reason §10.5 argues for declaring the camera at all.

    **`detector` is recorded here for the first time.** It used not to be, and that was a real gap:
    the detector decides both the metadata filter *and*, through `anonymise.py`'s person boxes, the
    redaction — 89% of redacted area is head bands. `record_baseline.py` had to carry the shipped
    backbone as a hand-maintained constant because this file could not answer the question. A corpus
    that cannot say which detector produced its boxes cannot have its privacy certificate reproduced.
    """
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source": "folder ingest (scripts/ingest_folder.py)",
                # The corpus directory's own name — `data/staging/hanoi/artifacts/provenance.json`
                # is `hanoi` — which is the only name anyone has for a folder-ingested corpus.
                # Recorded so `merge_corpora.py` can carry it into `merged_from[].name` and a frame
                # can say which corpus it came from (`services/search/artifacts.py:source_names`).
                # Taken from `out_path` rather than a sixth parameter: this function is already at
                # five, and the path it is writing to is the same fact.
                "corpus_name": os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(out_path)))) or None,
                "video_ids": sorted({r["video_id"] for r in rows}),
                "n_frames": len(rows),
                "n_scenes": len({r["scene_id"] for r in rows}),
                "vector_dtype": "float32",
                "encoder": "openclip:ViT-B-16-SigLIP2:webli",
                "privacy": privacy_config.as_dict() if privacy_config else None,
                "intrinsics": {
                    "source": "declared horizontal FOV, cx = W/2",
                    "hfov_deg": {v: h for v, h in sorted({(r["video_id"], r["hfov_deg"]) for r in rows})},
                    "bonnet_top": {v: b for v, b in sorted({(r["video_id"], r["bonnet_top"]) for r in rows})},
                    "caveat": "not a calibration; M2_DESIGN 10.5 measures what the substitution costs",
                },
                "detector": {
                    "model": detector or DEFAULT_DETECTOR,
                    "vocabulary": sorted(set(COCO_TO_VOCAB.values())),
                    "ego_filter": "wide boxes centred below bonnet_top dropped as the camera's own "
                    "vehicle (extract.py:drop_ego_boxes)",
                    "note": "also produces the person boxes anonymise.py turns into head bands, so "
                    "changing it reissues the privacy certificate",
                },
                # No `rejection_band` key here, and that absence is the message: `band.py` reads a
                # corpus with none as `unfitted` and says so at /status. Writing a placeholder would
                # be worse than writing nothing, because the check cannot tell a placeholder from a
                # measurement — which is how the string below sat next to an inherited band for two
                # corpora without anything noticing.
                "rejection_thresholds": "INHERITED FROM nuScenes - re-fit before trusting "
                "(M2_DESIGN 10.3); use the review loop to collect ~20 judgments, then "
                "scripts/measure/measure_rejection_band.py, which stamps `rejection_band` here",
                # The flag `Corpus.captions_deferred` reads. It travels with the corpus rather than
                # sitting in settings because it is a fact about these files, and a deployment pointed at
                # a deferred corpus with the setting off would refuse every query — every caption vector
                # is zero, so every score is 0.0, which `classify` reads as "nothing matches".
                "captions": {
                    "deferred": captions_deferred,
                    "note": "captioned at query time from redacted thumbnails, O(k) per query "
                    "(M2_DESIGN 6.1 option B); scores shift versus full-resolution ingest "
                    "captions, so re-fit the band before trusting a refusal"
                    if captions_deferred
                    else "captioned at ingest, full resolution",
                },
            },
            f,
            indent=2,
        )


def resolve_video(frames_dir: str, args) -> dict:
    """What this directory is: video_id, declared geometry, and sampling rate.

    Sidecar first, flags as the fallback, for every field. Returned as a dict rather than a tuple
    because it now carries four values and a positional fifth is how the wrong one gets unpacked
    into the wrong variable.

    `bonnet_top` defaults to 1.0 — no bodywork, filter disabled — so a corpus extracted before this
    existed, or shot on a camera that sees none, behaves exactly as it did.
    """
    sidecar = read_sidecar(frames_dir) or {}
    hfov = args.fov if args.fov is not None else sidecar.get("hfov_deg")
    if hfov is None:
        sys.exit(f"{frames_dir}: --fov is required (no hfov_deg in its sidecar). See M2_DESIGN 10.5.")
    check_fov(float(hfov))
    bonnet = args.bonnet_top if args.bonnet_top is not None else sidecar.get("bonnet_top", 1.0)
    return {
        "video_id": args.video_id or sidecar.get("video_id") or os.path.basename(os.path.normpath(frames_dir)),
        "hfov_deg": float(hfov),
        "fps": sidecar.get("fps", args.fps),
        "bonnet_top": float(bonnet),
    }


def ingest_one(frames_dir: str, args) -> tuple[list[dict], dict, dict, dict]:
    """Run the stages for one video. Returns (rows, detections, captions), both keyed by frame_id.

    The workdir is **per video**, which is not a tidiness preference — see `by_frame_id`. Sharing one
    would make the second video silently inherit the first's boxes and captions.
    """
    spec = resolve_video(frames_dir, args)
    video_id, hfov = spec["video_id"], spec["hfov_deg"]
    rows = build_rows(frames_dir, video_id, spec["fps"])
    for row in rows:
        row["hfov_deg"] = hfov
        row["bonnet_top"] = spec["bonnet_top"]
    ego = "no ego filter" if spec["bonnet_top"] >= 1.0 else f"bonnet_top={spec['bonnet_top']}"
    print(
        f"[frames]  {len(rows)} images, video_id={video_id!r}, "
        f"{len({r['scene_id'] for r in rows})} diversity buckets, hfov={hfov} deg, {ego}"
    )

    workdir = os.path.join(args.workdir, video_id)
    caches = run_stages(rows, workdir, args)
    ids = [r["item_id"] for r in rows]
    vectors = load_embeddings(SIGLIP_STEM, ids, workdir).astype("float32")

    # Needs the vectors, so it cannot happen in `build_rows` where the buckets are first assigned.
    # Merges only: on footage whose runs sit inside their buckets this is a no-op.
    merged = regroup(rows, vectors)
    if merged:
        print(f"[scenes]  {merged} buckets merged across stationary runs, {len({r['scene_id'] for r in rows})} left")

    captions = {} if args.skip_captions else by_frame_id(rows, read_caption_cache(caches["captions"]))

    # Checked here rather than after `by_frame_id`, which cannot express it: that helper defaults a
    # missing image to `[]`, and an empty detection list is indistinguishable from a frame that
    # genuinely has no face and no plate. Past this point a frame absent from the cache would be
    # redacted with no regions and published looking exactly like a verified one.
    privacy_by_image = load_cache(caches["privacy"], args.privacy_config)
    missing = [r for r in rows if os.path.basename(r["image_path"]) not in privacy_by_image]
    if missing:
        sys.exit(
            f"{frames_dir}: privacy cache covers {len(rows) - len(missing)} of {len(rows)} "
            f"frames; refusing to write unverified thumbnails for the other {len(missing)}"
        )

    return (
        rows,
        by_frame_id(rows, load_detections(caches["detections"])),
        by_frame_id(rows, privacy_by_image),
        {
            "vectors": vectors,
            "captions": captions,
            "caption_vectors": None
            if args.skip_captions
            else load_embeddings(CAPTION_STEM, ids, workdir).astype("float32"),
        },
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--frames",
        required=True,
        nargs="+",
        metavar="DIR",
        help="one or more directories of extracted frames; each becomes one video_id",
    )
    ap.add_argument("--fov", type=float, help="camera horizontal FOV in degrees; required unless the sidecar has it")
    ap.add_argument(
        "--bonnet-top",
        type=float,
        default=None,
        help="fraction of frame height above which the camera's own bodywork starts "
        "(0.75 on the first-release corpus). Wide boxes centred below it are the "
        "ego vehicle and are dropped. 1.0 disables. Sidecar supplies it if unset.",
    )
    ap.add_argument(
        "--detector",
        default=DEFAULT_DETECTOR,
        choices=sorted(DETECTORS),
        help="retrieval detector backbone. The cache is named after it, so two "
        "backbones never share a file -- see extract.py:_read_cache.",
    )
    ap.add_argument("--workdir", required=True, help="root for per-video detector/caption/embedding caches")
    # Required, with no default, unlike `promote_artifacts.py`. This script ingests a *different*
    # corpus by definition, and `data/` holds the one every number in `report.md` was measured on —
    # a convenient default here is a one-flag way to destroy the evidence trail. Stage, then swap.
    ap.add_argument("--out", required=True, help="artifacts + thumbs destination; use a staging dir, not data/")
    ap.add_argument("--video-id", default=None, help="defaults to the frames directory name; single --frames only")
    ap.add_argument("--fps", type=float, default=2.0, help="sampling rate, used only without a sidecar")
    ap.add_argument("--thumb-width", type=int, default=THUMB_WIDTH)
    ap.add_argument("--privacy-face-model", help="dedicated face detector weights")
    ap.add_argument("--privacy-plate-model", help="dedicated licence-plate detector weights")
    ap.add_argument("--privacy-face-threshold", type=float)
    ap.add_argument("--privacy-plate-threshold", type=float)
    ap.add_argument(
        "--privacy-imgsz", type=int, help="privacy detector inference resolution; see privacy_detector.DEFAULT_IMGSZ"
    )
    ap.add_argument("--privacy-device", help="privacy detector device, e.g. cuda:0 or cpu")
    ap.add_argument(
        "--skip-captions",
        action="store_true",
        help="defer captioning to query time (~83%% faster ingest; first query per frame "
        "pays ~1.1 s on GPU). For live-ingest demos — see src/services/search/captions.py",
    )
    args = ap.parse_args()
    args.privacy_config = config_from_environment(
        args.privacy_face_model,
        args.privacy_plate_model,
        args.privacy_face_threshold,
        args.privacy_plate_threshold,
        args.privacy_imgsz,
    )

    if args.video_id and len(args.frames) > 1:
        sys.exit(
            "--video-id names one video; with several --frames directories it would give them "
            "all the same id and collapse them into one clip. Use per-directory sidecars."
        )

    rows: list[dict] = []
    detections: dict = {}
    privacy_detections: dict = {}
    captions: dict = {}
    vector_blocks, caption_blocks = [], []
    for frames_dir in args.frames:
        video_rows, video_dets, video_privacy, embeddings = ingest_one(frames_dir, args)
        # Distinct ids are guaranteed by `frame_id_for` hashing `video_id:filename`, so this can only
        # trip if two directories resolve to the same video_id — which would silently drop frames.
        clash = {r["video_id"] for r in video_rows} & {r["video_id"] for r in rows}
        if clash:
            sys.exit(
                f"{frames_dir}: video_id {clash.pop()!r} is already in this corpus. Ids key "
                "thumbnails and review verdicts, so two clips sharing one would overwrite each "
                "other. Set a distinct video_id in the sidecar."
            )
        rows += video_rows
        detections.update(video_dets)
        privacy_detections.update(video_privacy)
        captions.update(embeddings["captions"])
        vector_blocks.append(embeddings["vectors"])
        if embeddings["caption_vectors"] is not None:
            caption_blocks.append(embeddings["caption_vectors"])

    if len(args.frames) > 1:
        print(
            f"[corpus]  {len(rows)} frames from {len(args.frames)} videos, "
            f"{len({r['scene_id'] for r in rows})} diversity buckets total"
        )

    art = os.path.join(args.out, "artifacts")
    os.makedirs(art, exist_ok=True)
    np.save(os.path.join(art, "vectors.npy"), np.concatenate(vector_blocks, axis=0))
    write_frames(rows, os.path.join(art, "frames.jsonl"))
    write_metadata(rows, detections, os.path.join(art, "metadata.jsonl"))
    if args.skip_captions:
        # Zeros and blanks, paired with the provenance flag that makes them mean "deferred" rather
        # than "lost". `caption_vectors.npy` still has to exist and still has to have N rows —
        # `Corpus.load` checks the three artifacts describe one corpus before serving any of them.
        np.save(os.path.join(art, "caption_vectors.npy"), np.zeros((len(rows), CAPTION_DIM), dtype="float32"))
        write_empty_captions(rows, os.path.join(art, "captions.jsonl"))
        print("[artifacts] frames + vectors + metadata written; captions DEFERRED to query time")
    else:
        np.save(os.path.join(art, "caption_vectors.npy"), np.concatenate(caption_blocks, axis=0))
        write_captions(rows, captions, os.path.join(art, "captions.jsonl"))
        print("[artifacts] frames + vectors + metadata + captions written")

    thumb_stats = write_thumbnails(
        rows, RedactionCaches(privacy_detections, detections), os.path.join(args.out, "thumbs"), args.thumb_width
    )
    print(
        f"[thumbs]  {thumb_stats['frames']} written at {args.thumb_width}px; "
        f"{thumb_stats['with_region']} carry a region "
        f"({thumb_stats['faces']} faces, {thumb_stats['plates']} plates, "
        f"{thumb_stats['heads']} person heads)"
    )

    write_provenance(rows, os.path.join(art, "provenance.json"), args.skip_captions, args.privacy_config, args.detector)
    stamp_anonymisation(os.path.join(art, "provenance.json"), thumb_stats)
    with open(os.path.join(art, "privacy_detections.jsonl"), "w", encoding="utf-8") as f:
        for row in rows:
            f.write(
                json.dumps(
                    {
                        "frame_id": row["item_id"],
                        "image": os.path.basename(row["image_path"]),
                        "dets": privacy_detections.get(row["item_id"], []),
                        "privacy": args.privacy_config.as_dict(),
                    }
                )
                + "\n"
            )
    write_scene_tags(art)
    print("[tags]    scene tags written; provenance records the declared-FOV caveat")
    print(f"\nwritten -> {art}/ and {os.path.join(args.out, 'thumbs')}/")
    if args.skip_captions:
        print(
            f"NOTE: captions deferred. The first query touching a frame captions it from its "
            f"thumbnail and caches the result in {CAPTIONS_DEFERRED}; measured at ~6.8 s/frame on "
            f"a CPU server, up to verify_top_k frames per query, then 18 ms once cached. "
            f"Retrieval and ranking are unaffected. Pre-warm the demo queries, or serve on a GPU."
        )
    print(
        "NEXT: the rejection band is still nuScenes-fitted — re-fit it from ~20 reviewed queries "
        "(M2_DESIGN 10.3) before trusting 'nothing matches' on this corpus."
    )


if __name__ == "__main__":
    main()
