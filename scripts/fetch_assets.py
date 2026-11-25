"""Fetch the corpus assets that are too large to commit, from the companion HF dataset.

Two classes of file live outside git, for the same reason and with different consequences:

| asset | lands in | size | missing means |
|---|---|---|---|
| index (`vectors.npy`, `caption_vectors.npy`) | `data/artifacts/` | 32 MB | **fatal** — `/status` 503, no search |
| thumbnails (`thumbs.tar`) | `data/thumbs/` | 274 MB | degraded — search works, images 404 |

`docs/guide/chapter-09.md` requires no committed file over 10 MB, and `vectors.npy` alone is 21 MB.
The four small artifacts — `frames.jsonl`, `metadata.jsonl`, `captions.jsonl`, `provenance.json` —
stay in git at 4.1 MB, so the repo still records *what* the corpus is; only the matrices derived
from it are fetched.

That asymmetry is why the index is fatal here and in the Dockerfile while thumbnails are not. A
service with no index cannot answer anything and should say so loudly; a service with no thumbnails
answers correctly and merely looks unfinished, which is worth degrading to rather than failing on.

Idempotent, and with `--if-missing` it makes no network call at all once the files are present —
that is what lets `make run` and `make test` depend on it without adding latency to every command.

No credential needed: the dataset is public.

**The revision is pinned, and that is the difference between a release that names a build and one
that names only some code.** The corpus is most of this product and none of it is in git, so an
unpinned fetch means `docker build` on an unchanged commit produces a different product the moment
the dataset is republished — which is a thing that happens here deliberately and often: 640 px
thumbnails on 08-07, and again whenever the corpus changes. `release/v1.0` freezing the code would
have frozen nothing that a user sees.

So `REVISION` below is the single source of truth, and the Dockerfile does not repeat it — the same
reasoning its torch-pin step gives for reading versions out of `requirements.txt` rather than
restating them. **`scripts/publish_assets.py` does not update it**, because a publish and a release
are different decisions: republishing makes new assets available, bumping this line is choosing to
ship them.

    python scripts/fetch_assets.py                  # index + thumbnails, at the pinned revision
    python scripts/fetch_assets.py --what index     # just what the service cannot start without
    python scripts/fetch_assets.py --revision main  # whatever is newest, for local experiments
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

REPO_ID = "P-057-RisingStar/scenesearch-assets"
# The dataset commit every build resolves to. Bump this — deliberately, as a reviewed change —
# when a republished corpus is meant to ship.
# 2026-08-21: re-redacted from `resnet50_v2` person boxes. 3,145 of 6,858 frames carry a region
# (was 2,616) and 7,344 head bands (was 4,924), which closes 599 frames where nuScenes' own
# annotations confirm a visible pedestrian and the published thumbnail carried no redaction at all.
# Both the tarball and the 6,858 loose copies were republished: the loose set is browsable on the
# Hub, so updating only `thumbs.tar` would have left those 599 public.
# 2026-08-06: the 640 px redacted nuScenes set, 6,858 frames, certified by `provenance.json`.
REVISION = "43f8cbf1933ce3a9c06b3b7548b50374f55583d1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS = os.path.join(ROOT, "data", "artifacts")
THUMBS = os.path.join(ROOT, "data", "thumbs")
INDEX_FILES = ("vectors.npy", "caption_vectors.npy")
TARBALL = "thumbs.tar"


def index_is_present() -> bool:
    """Both matrices on disk and non-empty. Shape is not checked — `Corpus.load` does that properly."""
    paths = [os.path.join(ARTIFACTS, f) for f in INDEX_FILES]
    return all(os.path.exists(p) and os.path.getsize(p) > 0 for p in paths)


def thumbs_are_present() -> bool:
    """As many thumbnails as provenance says there are frames, so a half-finished pull re-runs."""
    p = os.path.join(ARTIFACTS, "provenance.json")
    if not os.path.exists(p) or not os.path.isdir(THUMBS):
        return False
    with open(p, encoding="utf-8") as f:
        want = int(json.load(f).get("n_frames", 0))
    return len([x for x in os.listdir(THUMBS) if x.endswith(".jpg")]) >= want > 0


def fetch_index(repo: str, revision: str) -> None:
    """Download the two matrices into `data/artifacts/`, beside the committed small artifacts."""
    from huggingface_hub import hf_hub_download

    os.makedirs(ARTIFACTS, exist_ok=True)
    for name in INDEX_FILES:
        # One file at a time rather than a snapshot: this repo also holds 6,858 thumbnails, and a
        # snapshot with the wrong allow_patterns would drag every one of them into data/artifacts/.
        hf_hub_download(
            repo_id=repo, repo_type="dataset", filename=f"artifacts/{name}", revision=revision, local_dir=ARTIFACTS
        )
        # The download preserves the repo-side `artifacts/` prefix; the service expects the file
        # directly in data/artifacts/, so flatten it.
        nested = os.path.join(ARTIFACTS, "artifacts", name)
        if os.path.exists(nested):
            os.replace(nested, os.path.join(ARTIFACTS, name))
    stale = os.path.join(ARTIFACTS, "artifacts")
    if os.path.isdir(stale) and not os.listdir(stale):
        os.rmdir(stale)
    print(f"[index]   {', '.join(INDEX_FILES)} -> data/artifacts/")


def _unpack(tar_path: str) -> int:
    """Extract the JPEGs from a downloaded tarball into `data/thumbs/`, and count them.

    Every member is checked before it is written, because this is remote content and `tarfile` will
    otherwise happily honour an absolute path, a `../` prefix or a symlink pointing anywhere on the
    host. Three conditions, all required: a regular file (which excludes links and devices), a bare
    basename (no separator survives `os.path.basename`, so a crafted path cannot escape), and a
    `.jpg` suffix — `data/thumbs/` is served over HTTP by `frame_thumb`, so anything else landing
    there would be a file the archive was never meant to publish.

    `filter="data"` applies the stdlib's own equivalent checks underneath. Both are kept: they fail
    independently, and the belt-and-braces argument in `src/api/routes.py:frame_thumb` applies here
    for the same reason.
    """
    import tarfile

    os.makedirs(THUMBS, exist_ok=True)
    with tarfile.open(tar_path, "r:") as tar:
        safe = [m for m in tar if m.isfile() and m.name == os.path.basename(m.name) and m.name.endswith(".jpg")]
        tar.extractall(THUMBS, members=safe, filter="data")
    return len(safe)


def fetch_thumbs(repo: str, revision: str) -> None:
    """Download the thumbnail tarball and unpack it into `data/thumbs/`.

    One request, not 6,858. Fetching the JPEGs individually is what an unauthenticated caller gets
    rate-limited for: CI run 30736156566 took a 429 at ~490 files after four and a half minutes, and
    the Docker build makes the same call on the way to a deploy that has a fixed date. A tarball is
    also the shape the receiving end wants — it either arrives whole or not at all, where a partial
    snapshot leaves a directory that looks populated and is not.

    Uncompressed on purpose. Measured over 200 of these thumbnails, gzip -6 saves 2.1%: JPEG is
    already DCT-compressed, so the compression would cost build time to save nothing.
    """
    from huggingface_hub import hf_hub_download

    data = os.path.dirname(THUMBS)
    tar_path = hf_hub_download(repo_id=repo, repo_type="dataset", filename=TARBALL, revision=revision, local_dir=data)
    try:
        n = _unpack(tar_path)
    finally:
        # The tarball is scaffolding, and in the image it would otherwise sit in the layer forever
        # at 274 MB. Removed whether or not the extraction succeeded.
        os.remove(tar_path)
        state = os.path.join(data, ".cache")
        if os.path.isdir(state):
            shutil.rmtree(state, ignore_errors=True)
    print(f"[thumbs]  {n} jpgs -> data/thumbs/")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--what", choices=["all", "index", "thumbs"], default="all")
    ap.add_argument("--repo", default=REPO_ID)
    ap.add_argument(
        "--revision", default=REVISION, help="dataset commit to fetch; pass `main` for the newest published assets"
    )
    ap.add_argument(
        "--if-missing", action="store_true", help="no-op, with no network call, when the files are already present"
    )
    args = ap.parse_args()

    want_index = args.what in ("all", "index")
    want_thumbs = args.what in ("all", "thumbs")

    if args.if_missing:
        want_index = want_index and not index_is_present()
        want_thumbs = want_thumbs and not thumbs_are_present()
        if not want_index and not want_thumbs:
            return

    if want_index:
        try:
            fetch_index(args.repo, args.revision)
        except OSError as exc:
            sys.exit(f"could not fetch the index from {args.repo}: {exc}")
    if want_thumbs:
        try:
            fetch_thumbs(args.repo, args.revision)
        except OSError as exc:
            # Deliberately not fatal, and deliberately loud: this is the degraded case, not failure.
            print(f"WARNING: thumbnails not fetched from {args.repo} ({exc}) — search works, images will 404")


if __name__ == "__main__":
    main()
