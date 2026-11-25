"""Redact faces and licence plates from displayed frames — Brief §Bảo mật, "blur khuôn mặt/biển số".

**This runs at ingest and bakes the redaction into the thumbnails on disk.** The service never sees
an unredacted pixel, so there is no request-path cost, no new production dependency, and no way for
a bug in a query handler to serve the original. It is the same split M2_DESIGN §3 applies to
everything else: ingest makes facts about the corpus, query only reads them.

**Regions come from two sources unioned, because measurement showed neither is sufficient alone.**

*Plates* come from a dedicated plate detector. An object detector can say "truck" without locating a
licence plate; projecting a plate band onto that box destroys the whole side of a semi-truck. That
bug is why the vehicle-box path was removed, and it stays removed — no vehicle label produces a
region here.

*Faces* come from a dedicated face detector **and** from the top band of a `person` box. The face
detector alone was measured on 834 frames of Tokyo street footage: it found 8 faces where the
retrieval detector found 337 people, leaving 153 of 157 person-frames with nothing redacted, and
around half of those 8 were an advertising poster, signage, or motion blur. The head crops showed
why — in driving footage people are overwhelmingly turned away or in profile. A face detector must
*see a face*; a person box does not care which way they are facing. Neither signal is dropped,
because a union can only over-blur, and over-blur is the direction this module chooses everywhere
else.

Two asymmetries shape the geometry, both in the same direction — **over-blur rather than under-blur**:

* A false positive costs a smudge on a road scene. A false negative is an unredacted face or plate.
  Dedicated face/plate boxes allow the privacy detector to make that trade locally instead of
  masking a proportional part of an entire vehicle box.
* Redaction is a **mosaic**, not a Gaussian. A Gaussian is a convolution and is partially
  invertible given the kernel; downsampling to a handful of samples destroys the information
  outright. It also *looks* redacted, which matters when the reviewer's job is to trust the tool.

**The honest limits, because a privacy control that overstates itself is worse than none:**

1. **Recall is the privacy detector's recall.** A face or plate it misses is marked privacy-unverified
   by the ingest path and must not be published as a verified thumbnail.
2. **The privacy cache has its own thresholds and model provenance.** It must never silently reuse
   the retrieval-metadata cache.
3. **nuScenes already blurs faces and plates**, imperfectly, as any automated pass does. This is a
   second independent layer over that, not a replacement for it.
4. Only what the UI displays is redacted: the thumbnails, at `THUMB_WIDTH`. Nothing else is served.

    python scripts/anonymise.py --dataroot ../data/nuscene/trainval        # regenerate thumbnails
    python scripts/anonymise.py --dataroot ... --report-only               # measure, write nothing
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from _console import use_utf8  # noqa: E402, F401 -- console encoding; imported for effect

# Dedicated privacy detectors return face and licence-plate boxes. These margins are deliberately
# small and bounded in pixels so a large truck box can never become a large privacy mask.
FACE_MARGIN_PX = 3
PLATE_MARGIN_PX = 2

# COCO labels from the retrieval cache that contribute a region. `person` only: vehicle labels are
# what produced the semi-truck regression, and plates now come from a detector that locates them.
PERSON_LABELS = frozenset({"person"})

# Top fraction of a person box treated as "head". A standing adult's head is roughly an eighth of
# their height; 0.28 is far more than that on purpose, so a partially occluded or seated person —
# whose box is torso-up and whose head therefore sits lower in normalised terms — is still covered.
HEAD_FRACTION = 0.28

# Longest side, in samples, that a redacted region is reduced to before being scaled back up. Fixed
# rather than proportional so a close-up face and a distant one are destroyed equally: a 400 px face
# reduced to 6 samples carries no more recoverable detail than a 20 px one.
MOSAIC_SAMPLES = 6

# Width of the thumbnail every writer produces, and the only served image. One number here rather
# than a default repeated in three argparse blocks, because they must not diverge: two writers
# disagreeing would put two resolutions in one corpus, and the corpus is what gets published.
#
# It lives in this module rather than in `src/config.py` for a mechanical reason — `ingest_folder`
# and `promote_artifacts` run in the `ssv` research environment, which has open_clip and cv2 but no
# pydantic-settings, so importing `get_settings` here would break ingest where it actually runs.
#
# **Not a display setting.** `src/services/search/captions.py` captions the *thumbnail* at query
# time, so this width feeds caption quality, the caption verifier, and therefore the rejection band.
# 320 was inherited from nuScenes, whose source is 1600x900 and already blurred at source; on 1080p
# footage it discards most of the frame before anything looks at it. Raising it costs bytes in
# `thumbs.tar`, which the container fetches at Docker *build* time — measure against that budget
# (docs/deploy.md) before moving it again.
THUMB_WIDTH = 640

Box = tuple[float, float, float, float]


def _expand(box: Box, margin: float) -> Box:
    x1, y1, x2, y2 = box
    return x1 - margin, y1 - margin, x2 + margin, y2 + margin


def head_region(box: Box) -> Box:
    """The part of a person box that can contain a face, whichever way they are facing."""
    x1, y1, x2, y2 = box
    return (x1, y1, x2, y1 + (y2 - y1) * HEAD_FRACTION)


def regions_for(dets: list[dict]) -> list[Box]:
    """Every region to redact in one frame, from the **union** of that frame's detections.

    Callers pass privacy detections and retrieval detections concatenated, so the two signals meet
    here rather than in three separate call sites. Overlap between a `face` box and the `person`
    head band containing it is fine and expected: mosaicking the same pixels twice is idempotent,
    and the alternative — picking one — is how a turned-away pedestrian goes out unredacted.

    No minimum size. A distant box costs almost nothing to mosaic, and "too small to be
    identifiable" is exactly the judgement a privacy control should not be quietly making on the
    subject's behalf — especially when the same frame at full resolution may be shipped later.
    """
    out: list[Box] = []
    for det in dets:
        label = det.get("label")
        if label == "face":
            out.append(_expand(tuple(det["box"]), FACE_MARGIN_PX))
        elif label == "license_plate":
            out.append(_expand(tuple(det["box"]), PLATE_MARGIN_PX))
        elif label in PERSON_LABELS:
            out.append(head_region(tuple(det["box"])))
    return out


def redact(image, regions: list[Box]):
    """Mosaic every region, in place on a copy. Returns the image for chaining.

    Applied at **source** resolution, before the thumbnail downscale, so the destroyed information
    is never present in anything written to disk. Redacting the thumbnail instead would mean the
    unredacted pixels existed in the file that produced it.
    """
    from PIL import Image

    for x1, y1, x2, y2 in regions:
        left, top = max(0, int(x1)), max(0, int(y1))
        right, bottom = min(image.width, int(x2) + 1), min(image.height, int(y2) + 1)
        if right - left < 1 or bottom - top < 1:
            continue
        patch = image.crop((left, top, right, bottom))
        scale = max(1, max(patch.width, patch.height) // MOSAIC_SAMPLES)
        small = patch.resize((max(1, patch.width // scale), max(1, patch.height // scale)), Image.BILINEAR)
        image.paste(small.resize(patch.size, Image.NEAREST), (left, top))
    return image


def load_detections(cache_path: str, require_privacy: bool = False) -> dict[str, list[dict]]:
    """image basename → detections from a JSONL cache.

    `require_privacy` refuses a row that carries no `privacy` provenance block, and every caller
    loading a privacy cache passes it. The two caches share a schema — `image` plus `dets` — so a
    retrieval cache handed to the redaction path parses perfectly, contains no `face` or
    `license_plate` label, and therefore redacts **nothing**, while `privacy_unverified` stays 0 and
    every downstream check certifies full coverage. That is the 2026-08-03 incident reached by a
    different route, so the mismatch is an error at load time rather than an empty result later.
    """
    by_image: dict[str, list[dict]] = {}
    with open(cache_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                if require_privacy and not row.get("privacy"):
                    raise ValueError(
                        f"{cache_path}: row for {row.get('image')!r} has no privacy provenance — "
                        "this is not a dedicated privacy cache, and redacting from it would write "
                        "unredacted thumbnails while reporting full coverage"
                    )
                by_image[row["image"]] = row["dets"]
    return by_image


def source_index(dataroot: str, camera: str = "CAM_FRONT") -> dict[str, str]:
    """basename → full path, by scanning the dataroot.

    Scanned rather than read from the manifest, and rather than asked of the devkit: the manifest
    stores absolute paths captured when it was written and goes stale the moment the dataroot moves
    (`promote_artifacts.resolve_paths` documents that break), while the devkit would pull a 4 GB
    dependency into a script that only needs filenames.
    """
    folder = os.path.join(dataroot, "samples", camera)
    if not os.path.isdir(folder):
        sys.exit(f"no {folder} — is --dataroot right?")
    return {name: os.path.join(folder, name) for name in os.listdir(folder)}


def thumbnail(image, width: int):
    """Downscale to the display size, preserving aspect. Same settings as `promote_artifacts`."""
    from PIL import Image

    image = image.convert("RGB")
    image.thumbnail((width, width * image.height // image.width), Image.LANCZOS)
    return image


def redact_corpus(paths: dict, width: int, report_only: bool) -> dict:
    """Regenerate every thumbnail with redaction applied. Returns counts for the report.

    `paths` carries `frames`, `manifest`, `detections`, `dataroot` and `thumbs` — bundled because
    they travel together and the alternative is a six-argument function.

    **Driven by `frames.jsonl`, not by the manifest.** The manifest describes all of trainval, while
    the corpus is the 170 scenes actually selected; iterating the manifest happens to produce the
    right set only because no other blob is on disk, and it turns "this frame has no source image" —
    a real problem that would ship a stale thumbnail — into an expected count of 27,291 that nobody
    would ever read. Driven by the corpus, a missing source is unambiguously wrong.
    """
    dets_by_image = load_detections(paths["detections"], require_privacy=True)
    # The retrieval cache supplies `person` boxes for the head band. It is loaded without
    # `require_privacy` because it is not a privacy cache — and a missing one is fatal rather than
    # empty, since silently losing the head band is the failure this union exists to prevent.
    retrieval_by_image = load_detections(paths["retrieval"])
    sources = source_index(paths["dataroot"])
    # `frames` counts every frame with a source image, so `frames - privacy_unverified` is the
    # verified set. `with_region` is counted separately because most driving frames contain no face
    # and no plate: deriving "frames with a region" from the verified count would claim a redaction
    # on every one of them.
    stats = {
        "frames": 0,
        "privacy_unverified": 0,
        "with_region": 0,
        "regions": 0,
        "faces": 0,
        "plates": 0,
        "heads": 0,
        "missing_source": 0,
    }
    # image basename -> frame_id, for the frames this pass actually certified. The promoted
    # `frames.jsonl` carries no `image_path` and the manifest that resolves one is not shipped, so
    # without this the copied cache keys on source filenames that do not exist in the deploy and
    # nothing downstream can tell which corpus frame each row certifies.
    certified: dict[str, str] = {}

    with open(paths["manifest"], encoding="utf-8") as f:
        basename_of = {
            row["item_id"]: os.path.basename(row["image_path"].replace("\\", "/"))
            for row in (json.loads(line) for line in f if line.strip())
        }
    with open(paths["frames"], encoding="utf-8") as f:
        frame_ids = [json.loads(line)["frame_id"] for line in f if line.strip()]

    from PIL import Image

    for frame_id in frame_ids:
        source = sources.get(basename_of.get(frame_id, ""))
        if source is None:
            stats["missing_source"] += 1
            continue
        stats["frames"] += 1
        image_name = basename_of.get(frame_id, "")
        if image_name not in dets_by_image:
            stats["privacy_unverified"] += 1
            continue
        certified[image_name] = frame_id
        dets = dets_by_image[image_name] + retrieval_by_image.get(image_name, [])
        regions = regions_for(dets)
        stats["with_region"] += 1 if regions else 0
        stats["regions"] += len(regions)
        stats["faces"] += sum(1 for d in dets if d.get("label") == "face")
        stats["plates"] += sum(1 for d in dets if d.get("label") == "license_plate")
        stats["heads"] += sum(1 for d in dets if d.get("label") in PERSON_LABELS)
        if report_only:
            continue
        with Image.open(source) as im:
            im = im.convert("RGB")
            redact(im, regions)
            thumbnail(im, width).save(
                os.path.join(paths["thumbs"], f"{frame_id}.jpg"), "JPEG", quality=80, optimize=True
            )
    stats["certified"] = certified
    return stats


def stamp_provenance(artifacts_dir: str, stats: dict, caches: dict) -> None:
    """Record the redaction pass beside the data, as `tag_scenes.py` does for scene tags.

    Without it, "are these thumbnails redacted?" is answerable only by looking at them — and the
    answer for a frame with nothing detected looks identical either way.

    The weights and the cache are written too, not just the counts. `promote_artifacts` already does
    this and this path did not, so regenerating thumbnails here left a corpus its own release gate
    rejected — and the obvious way to "fix" a gate that fails on freshly redacted thumbnails is to
    weaken the gate. A certificate that cannot name the model that produced the redactions is not a
    certificate.

    **That applied to the retrieval cache too, and did not hold until 2026-08-20.** The `source`
    line below named `detections_frcnn.jsonl` as a literal, whatever `--retrieval-cache` was
    actually passed. Person boxes supply the head bands and head bands are 89% of the redacted area,
    so the field that mattered most was the one hardcoded — and a certificate naming the wrong
    detector reads exactly like one naming the right detector. It is read from the cache in use now,
    which is why this takes the whole `paths` dict rather than one cache.
    """
    from privacy_detector import privacy_config_from_cache

    path = os.path.join(artifacts_dir, "provenance.json")
    with open(path, encoding="utf-8") as f:
        prov = json.load(f)
    prov["privacy"] = privacy_config_from_cache(caches["detections"])
    # Beside the artifacts it certifies: the gate reads the cache from the promoted directory, and
    # the research run it came from is not shipped. Rows are re-keyed to `frame_id` and rows for
    # images outside this corpus are dropped, so the shipped certificate describes exactly the
    # frames that were redacted — not whatever else the research run happened to detect on.
    certified = stats["certified"]
    with (
        open(caches["detections"], encoding="utf-8") as src,
        open(os.path.join(artifacts_dir, "privacy_detections.jsonl"), "w", encoding="utf-8") as dst,
    ):
        for line in src:
            if not line.strip():
                continue
            row = json.loads(line)
            frame_id = certified.get(row["image"])
            if frame_id is None:
                continue
            dst.write(json.dumps({**row, "frame_id": frame_id}) + "\n")
    prov["anonymisation"] = {
        "geometry": f"dedicated face/plate boxes expanded by <= {FACE_MARGIN_PX}px, "
        f"unioned with person box top {HEAD_FRACTION:.2f} (head)",
        "method": f"mosaic to <= {MOSAIC_SAMPLES} samples per side, at source resolution",
        "source": f"{os.path.basename(caches['detections'])} (face, licence plate) "
        f"unioned with person boxes from {os.path.basename(caches['retrieval'])}",
        "heads": stats["heads"],
        "frames_with_a_region": stats["with_region"],
        "frames_privacy_verified": stats["frames"] - stats["privacy_unverified"],
        "privacy_unverified": stats["privacy_unverified"],
        "faces": stats["faces"],
        "plates": stats["plates"],
        "frames": stats["frames"],
        "regions": stats["regions"],
        "limit": "coverage is the union of person-box recall and dedicated detector recall; "
        "unverified frames must not be published",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prov, f, indent=2)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataroot", default=os.path.join(ROOT, "..", "data", "nuscene", "trainval"))
    ap.add_argument("--research-root", default=os.path.join(ROOT, "experiments", "m1", "runs", "trainval_9_10"))
    ap.add_argument("--privacy-cache", help="JSONL privacy cache; defaults to the research run cache")
    ap.add_argument("--retrieval-cache", help="JSONL retrieval cache supplying person boxes for the head band")
    ap.add_argument("--thumbs", default=os.path.join(ROOT, "data", "thumbs"))
    ap.add_argument("--thumb-width", type=int, default=THUMB_WIDTH)
    ap.add_argument("--report-only", action="store_true", help="measure coverage, write nothing")
    args = ap.parse_args()

    paths = {
        "frames": os.path.join(ROOT, "data", "artifacts", "frames.jsonl"),
        "manifest": os.path.join(args.research_root, "artifacts/dataset/manifest.jsonl"),
        "detections": args.privacy_cache
        or os.path.join(args.research_root, "artifacts/metadata/privacy_detections.jsonl"),
        "retrieval": args.retrieval_cache
        or os.path.join(args.research_root, "artifacts/metadata/detections_frcnn.jsonl"),
        "dataroot": args.dataroot,
        "thumbs": args.thumbs,
    }
    os.makedirs(args.thumbs, exist_ok=True)
    stats = redact_corpus(paths, args.thumb_width, args.report_only)

    covered = stats["frames"] - stats["privacy_unverified"]
    print(f"frames            {stats['frames']}" + ("  [report only — nothing written]" if args.report_only else ""))
    print(f"  privacy checked {covered} ({covered / max(1, stats['frames']):.1%})")
    print(f"  with a region   {stats['with_region']} ({stats['with_region'] / max(1, stats['frames']):.1%})")
    print(f"  privacy unverified {stats['privacy_unverified']}")
    print(
        f"regions           {stats['regions']}  "
        f"({stats['faces']} faces, {stats['plates']} plates, {stats['heads']} person heads)"
    )
    if stats["missing_source"]:
        # Every corpus frame must have a source image. Any count here means thumbnails were left
        # unredacted, so it is an error rather than a note.
        sys.exit(
            f"\nFAILED: {stats['missing_source']} corpus frames had no source image under --dataroot;"
            " their thumbnails are unchanged and therefore unredacted"
        )
    if not args.report_only and stats["privacy_unverified"]:
        sys.exit("\nFAILED: privacy-unverified frames exist; refusing to publish an unverified corpus")
    if not args.report_only:
        stamp_provenance(os.path.join(ROOT, "data", "artifacts"), stats, paths)
        print("\nprovenance.json records the pass; republish thumbs.tar or the deploy serves the old set")
    print("\nCoverage is the dedicated privacy detector's recall; review representative frames before release.")


if __name__ == "__main__":
    main()
