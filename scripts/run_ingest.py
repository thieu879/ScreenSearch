"""Run the offline ingest over a chosen corpus, resumably, into an isolated workdir.

**Interpreter: `C:/Users/Precision/ssv`, not `.venv`.** It needs CUDA, the nuScenes devkit and the
`scenesearch` package in `experiments/m1/`, none of which `.venv` has — so an editor pointed at
`.venv` will underline the imports below in red. That is expected and does not mean this file is
dead. See `scripts/README.md` and `pyrightconfig.json`.

This is the **ingest** half of `experiments/M2_DESIGN.md` §3 driven end to end: manifest → detector →
captions → embeddings. `scripts/promote_artifacts.py --research-root <workdir>` then turns the
result into the six artifacts the service reads.

    C:/Users/Precision/ssv/Scripts/python.exe scripts/run_ingest.py \
        --dataroot ../data/nuscene/trainval --version v1.0-trainval \
        --scenes experiments/m1/corpus/trainval_9_10.txt \
        --workdir experiments/m1/runs/trainval_9_10

The scene list is generated, not hand-written: `audit_scenes.py --emit 9,10` derives it from the
same chunking `--parts` reports, so the corpus definition and the coverage table cannot disagree.
The file records its own coverage in a header comment.

**Promote to staging, never straight over `data/artifacts/`.** A new corpus moves every number in
`eval/results/report.md`, and the per-frame intrinsics fix changes labels on its own — 5 of mini's
404 frames. Those are re-measurements, not a drop-in replacement, so the run finishes by printing a
`--out <workdir>/promoted` command rather than one that overwrites what the service is serving.

**Why a separate workdir rather than reusing `experiments/m1/`.** The M1 caches and
`outputs/emb_*.npy` back the published experiments (`40095e80` and friends) and were computed on
CPU. Writing a new corpus over them would destroy the reproducibility of every number in
`RESULTS.md`, and *mixing* is worse than overwriting: mini is a strict subset of trainval with four
of its scenes inside parts 9 and 10, so ~160 frames would silently reuse CPU-computed cache entries
while the other ~6,700 were computed on GPU. Device changes floating-point orderings — fine within
one corpus computed one way, not fine across a corpus computed both ways.

**Resumability is already in the primitives, not added here.** `DetectionStore.detections_for` and
`CaptionRetrievalEncoder.captions_for` both append to a JSONL cache per batch and skip whatever is
already present, so an interrupted run continues rather than restarting. Image embeddings are the
exception: `load_or_encode` is all-or-nothing over the whole corpus. It is also the cheap stage
(~6 min of a ~2 h run), so it is left alone rather than rebuilt.

Measured stage costs on a Quadro P2000 at 6,858 frames — see `scenesearch/device.py`:

    detector      0.137 s/frame   ~16 min
    captions      0.76  s/frame   ~87 min      <- dominates
    SigLIP2       fast, batched   ~6 min
    MiniLM text   fast            ~1 min
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M1 = os.path.join(REPO, "experiments", "m1")
sys.path.insert(0, M1)
sys.path.insert(0, os.path.join(REPO, "scripts"))

from _console import use_utf8  # noqa: E402, F401 -- console encoding; imported for effect

# Without this, `--help` itself crashes: argparse prints this module's docstring, the docstring
# contains `→`, and a cp1252 console cannot encode it. A script whose help text raises
# UnicodeEncodeError reads as broken code rather than as a terminal setting.


def elapsed(t0: float) -> str:
    """Seconds since `t0` as `1h 23m 45s`, dropping leading zero units."""
    s = int(time.time() - t0)
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}h {m:02d}m {s:02d}s" if h else (f"{m}m {s:02d}s" if m else f"{s}s")


def build_or_load_manifest(dataroot: str, version: str, path: str) -> list[dict]:
    """Manifest for every keyframe in `dataroot`, built once and reused on resume."""
    from scenesearch.data.manifest import build_manifest

    if not os.path.exists(path):
        n = build_manifest(dataroot, path, version)
        print(f"[manifest] built {n} rows -> {path}")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def filter_scenes(rows: list[dict], spec: str | None, dataroot: str, version: str) -> list[dict]:
    """Restrict the manifest to the scenes named in `spec` (names or tokens, one per line)."""
    if not spec:
        return rows
    from scenesearch.data.nuscenes_loader import load_nuscenes

    nusc = load_nuscenes(dataroot, version)
    by_name = {s["name"]: s["token"] for s in nusc.scene}
    with open(spec, encoding="utf-8") as f:
        wanted = {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}
    unknown = [w for w in wanted if w not in by_name and w not in by_name.values()]
    if unknown:
        sys.exit(f"--scenes lists {len(unknown)} unknown scenes, first: {unknown[0]!r}")
    tokens = {by_name.get(w, w) for w in wanted}
    kept = [r for r in rows if r["scene_token"] in tokens]
    if not kept:
        sys.exit("--scenes matched no manifest rows")
    print(f"[scenes]   {len({r['scene_token'] for r in kept})} scenes, {len(kept)} of {len(rows)} frames")
    return kept


def check_images_present(rows: list[dict]) -> None:
    """Fail now, not two hours in, if the selected frames have no images on disk.

    The manifest is built from *metadata*, which describes all 850 trainval scenes regardless of
    which blobs were downloaded — 34,149 rows against the 6,858 frames parts 9 and 10 actually
    provide. Selecting scenes that were never extracted produces a manifest that looks fine and a
    run that dies partway through the detector, after the expensive part has started.
    """
    missing = [r for r in rows if not os.path.exists(r["image_path"])]
    if not missing:
        return
    scenes = {r["scene_token"] for r in missing}
    sys.exit(
        f"{len(missing)} of {len(rows)} selected frames have no image on disk, across "
        f"{len(scenes)} scenes.\nFirst: {missing[0]['image_path']}\n"
        "Those scenes belong to a blob that has not been extracted into this dataroot — check "
        "--scenes against what is present, or merge the missing blob in."
    )


def stage_detect(paths: list[str], cache: str, model: str | None = None) -> None:
    """Detector boxes -> JSONL cache. Appends per batch; skips what is already there.

    `model` is threaded through rather than left to the default. Not passing it is what let a run
    point `--detections` at another backbone's cache, read zero matching rows and append its own:
    2,304 `mobilenet_v3` rows into `detections_resnet50_v2.jsonl` on 2026-08-08, over a file that
    cost 63 GPU-minutes. `_read_cache` refuses that now, but the caller still has to say which
    backbone it wants, and the cache path still has to be named for it.
    """
    from scenesearch.metadata.extract import DEFAULT_DETECTOR, DetectionStore

    t0 = time.time()
    DetectionStore(cache_path=cache, model=model or DEFAULT_DETECTOR).detections_for(paths)
    print(f"[detect]   done in {elapsed(t0)}")


def stage_privacy(paths: list[str], cache: str, config, device: str | None = None) -> None:
    """Dedicated face/plate detections; kept separate from retrieval metadata."""
    from privacy_detector import PrivacyDetector

    t0 = time.time()
    PrivacyDetector(config, device).detect_to_cache(paths, cache)
    print(f"[privacy]  done in {elapsed(t0)}")


def stage_caption(paths: list[str], cache: str) -> None:
    """Florence-2 captions -> JSONL cache. The long pole; appends per batch."""
    from scenesearch.pipelines.caption_retrieval import CaptionRetrievalEncoder

    t0 = time.time()
    CaptionRetrievalEncoder(cache_path=cache).captions_for(paths)
    print(f"[caption]  done in {elapsed(t0)}")


def stage_embed(rows: list[dict], outputs: str, caption_cache: str, captions: bool = True) -> None:
    """SigLIP2 image vectors and MiniLM caption vectors, both via run_eval's cache.

    `captions=False` is the caption-deferred ingest (`ingest_folder.py --skip-captions`): with no
    caption cache to read, the MiniLM pass has nothing to embed and would fail rather than no-op.
    """
    from scenesearch.encoders.siglip import SiglipEncoder
    from scenesearch.evaluation.run_eval import load_or_encode
    from scenesearch.pipelines.caption_retrieval import CaptionRetrievalEncoder

    paths = [r["image_path"] for r in rows]
    ids = [r["item_id"] for r in rows]
    encoders = [SiglipEncoder()]
    if captions:
        encoders.append(CaptionRetrievalEncoder(cache_path=caption_cache))
    for encoder in encoders:
        t0 = time.time()
        emb, _ = load_or_encode(encoder, paths, ids, outputs)
        print(f"[embed]    {encoder.name} -> {emb.shape} in {elapsed(t0)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataroot", required=True)
    ap.add_argument("--version", default="v1.0-trainval")
    ap.add_argument("--scenes", metavar="FILE", help="restrict to these scenes, one per line")
    ap.add_argument("--workdir", required=True, help="isolated cache + output directory")
    ap.add_argument("--skip", default="", help="comma-separated stages to skip: detect,caption,embed")
    ap.add_argument("--privacy-face-model", help="dedicated face detector weights")
    ap.add_argument("--privacy-plate-model", help="dedicated licence-plate detector weights")
    ap.add_argument("--privacy-face-threshold", type=float)
    ap.add_argument("--privacy-plate-threshold", type=float)
    ap.add_argument("--privacy-device", help="privacy detector device, e.g. cuda:0 or cpu")
    args = ap.parse_args()

    from privacy_detector import config_from_environment

    privacy_config = config_from_environment(
        args.privacy_face_model,
        args.privacy_plate_model,
        args.privacy_face_threshold,
        args.privacy_plate_threshold,
    )

    from scenesearch.device import default_device

    work = os.path.abspath(args.workdir)
    art, outputs = os.path.join(work, "artifacts"), os.path.join(work, "outputs")
    for d in (os.path.join(art, "dataset"), os.path.join(art, "metadata"), os.path.join(art, "captions"), outputs):
        os.makedirs(d, exist_ok=True)

    print(f"device: {default_device()}   workdir: {work}\n")
    started = time.time()
    rows = build_or_load_manifest(args.dataroot, args.version, os.path.join(art, "dataset", "manifest.jsonl"))
    rows = filter_scenes(rows, args.scenes, args.dataroot, args.version)
    check_images_present(rows)
    paths = [r["image_path"] for r in rows]
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    detections = os.path.join(art, "metadata", "detections_frcnn.jsonl")
    privacy = os.path.join(art, "metadata", "privacy_detections.jsonl")
    captions = os.path.join(art, "captions", "florence2_base_detailed.jsonl")
    if "detect" not in skip:
        stage_detect(paths, detections)
    stage_privacy(paths, privacy, privacy_config, args.privacy_device)
    if "caption" not in skip:
        stage_caption(paths, captions)
    if "embed" not in skip:
        stage_embed(rows, outputs, captions)

    print(f"\ningest complete in {elapsed(started)}")
    staging = os.path.join(work, "promoted")
    print("\nnext — promote to a STAGING directory, not data/:\n")
    print(
        f"  promote_artifacts.py --dataroot {args.dataroot} --version {args.version} \\\n"
        f"      --research-root {work} \\\n"
        + (f"      --scenes {args.scenes} \\\n" if args.scenes else "")
        + f"      --out {staging}\n"
    )
    print("Then re-run the eval against it before swapping data/artifacts/. A new corpus moves every")
    print("number in eval/results/report.md, and the per-frame intrinsics fix alone changed 5 of")
    print("mini's 404 frames — those are re-measurements, not a drop-in replacement.")


if __name__ == "__main__":
    main()
