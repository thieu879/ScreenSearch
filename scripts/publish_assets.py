"""Publish the corpus assets that cannot be committed, to a Hugging Face dataset repo.

Two things live outside git, for two different reasons that happen to have the same fix:

- **Thumbnails.** `M2_DESIGN.md` §4 says not to store frame images: the coordinate is the fact, the
  pixels are derivable. `frames.jsonl` carries `video_id` + `timestamp_s`, so a thumbnail is a
  *cache*. At 404 frames committing them was tolerable; at 6,858 they are 85 MB.
- **The index.** `vectors.npy` is 21 MB and `caption_vectors.npy` 10.5 MB, and
  `docs/guide/chapter-09.md` requires no committed file over 10 MB. The four small artifacts stay in
  git, so the repo still records *what* the corpus is — only the matrices derived from it move.

Both still have to reach the container. The split that works:

    ingest (local, GPU)  ->  this script, once  ->  HF dataset repo
                                                        |
                                          Dockerfile pulls at BUILD time
                                                        |
                                          runtime serves from local disk, unchanged

`src/api/routes.py:frame_thumb` needs no change at all, there is no fetch on the request path, and
no credential lives in the running container — the dataset is public, so the build reads it
anonymously.

Authentication comes from the CLI's cached credential (`hf auth login`), never from an argument or
an environment variable in this repo. A token pasted into a shell command ends up in history, and
this project's pre-push hook ships prompts to a grading server.

    python scripts/publish_assets.py --thumbs data/thumbs    # one tarball, one request to fetch
    python scripts/publish_assets.py --thumbs DIR --per-file # ...plus the loose, browsable copies
    python scripts/publish_assets.py --index                 # just the two matrices
    python scripts/publish_assets.py --card-only             # just the dataset card
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

REPO_ID = "P-057-RisingStar/scenesearch-assets"
# The org's namespace, not its display name: whoami() reports name="P-057-RisingStar" and
# fullname="AI20K-Build-Phase-Cohort-3-P-057-RisingStar". Repo ids use the former.

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD = os.path.join(ROOT, "docs", "reference", "assets-dataset-card.md")
# Version-controlled here and uploaded as the repo's README.md, rather than written inline: the
# published card states the nuScenes CC BY-NC-SA 4.0 terms this derivative inherits, and a licence
# notice that only exists on a remote server is one nobody can review in a diff.

INDEX_FILES = ("vectors.npy", "caption_vectors.npy")
TARBALL = "thumbs.tar"
# Thumbnails are published as one tarball as well as loose files. The loose copies make the dataset
# browsable; the tarball is what anything automated reads, because 6,858 individual requests is what
# the Hub rate-limits an unauthenticated caller for — it 429'd CI at ~490 files, and the Docker
# build on the way to a dated deploy makes exactly the same call.


def require_login() -> str:
    """Fail early and helpfully if there is no cached credential."""
    from huggingface_hub import HfApi
    from huggingface_hub.errors import LocalTokenNotFoundError

    try:
        return HfApi().whoami()["name"]
    except (LocalTokenNotFoundError, KeyError):
        sys.exit(
            "not logged in — run `hf auth login` in a real terminal first "
            "(it needs interactive input, so it cannot run through an agent shell)"
        )


def count_thumbs(folder: str) -> int:
    """How many JPEGs are about to be published, failing if the folder is wrong."""
    if not os.path.isdir(folder):
        sys.exit(f"no such folder: {folder}")
    n = sum(1 for f in os.listdir(folder) if f.endswith(".jpg"))
    if not n:
        sys.exit(f"{folder} holds no .jpg files — is that the thumbs directory?")
    return n


def ensure_repo(repo_id: str, private: bool) -> None:
    """Create the dataset repo if it does not exist. Idempotent.

    Public by default and deliberately: the Dockerfile pulls this at build time, and a private repo
    would mean a read token inside the image build — a credential to manage, rotate and leak, for
    thumbnails derived from a public dataset.
    """
    from huggingface_hub import HfApi

    HfApi().create_repo(repo_id=repo_id, repo_type="dataset", private=private, exist_ok=True)
    print(f"[repo]    {repo_id} ready (private={private})")


def upload_card(repo_id: str) -> None:
    """Publish the dataset card as the repo's README.md.

    Separate from the asset uploads and done first, so a public repo is never briefly readable
    without its licence terms attached.
    """
    from huggingface_hub import HfApi

    if not os.path.isfile(CARD):
        sys.exit(f"dataset card missing: {CARD}")
    HfApi().upload_file(
        path_or_fileobj=CARD,
        path_in_repo="README.md",
        repo_id=repo_id,
        repo_type="dataset",
        commit_message="docs: dataset card with nuScenes attribution",
    )
    print(f"[card]    {os.path.relpath(CARD, ROOT)} -> README.md")


def upload_index(repo_id: str, artifacts: str) -> None:
    """Publish the two vector matrices under an `artifacts/` prefix.

    Prefixed because thumbnails sit at the repo root — moving 6,858 files server-side to gain a
    matching prefix would cost a full re-upload for cosmetics. The card documents the layout.
    """
    from huggingface_hub import HfApi

    api = HfApi()
    for name in INDEX_FILES:
        path = os.path.join(artifacts, name)
        if not os.path.isfile(path):
            sys.exit(f"missing {path} — promote the corpus first")
        api.upload_file(
            path_or_fileobj=path,
            path_in_repo=f"artifacts/{name}",
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=f"feat: {name}",
        )
        print(f"[index]   artifacts/{name} ({os.path.getsize(path) / 1e6:.1f} MB)")


def require_privacy_clearance(artifacts: str, thumbs: str) -> dict:
    """Refuse to upload a thumbnail directory the privacy gate has not cleared.

    This is the only moment that matters. `verify_privacy_assets` run by hand proves the corpus was
    clean when someone remembered to run it; run here it proves the corpus was clean at the instant
    it became public. The two are the same check and a very different guarantee — the unredacted set
    currently on the Hub was published by a path that simply never asked.

    There is deliberately no `--force`. A flag to publish unverified faces is a flag that gets used
    at 2 a.m. before a demo; regenerating the thumbnails is minutes of GPU time.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from verify_privacy_assets import verify

    try:
        return verify(artifacts, thumbs)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        sys.exit(
            f"[privacy] REFUSING TO PUBLISH — {thumbs} is not cleared: {exc}\n"
            "          Run scripts/privacy_detector.py, then scripts/anonymise.py, then re-publish."
        )


def build_tarball(folder: str, dest: str) -> str:
    """Pack a thumbnail directory into one flat, uncompressed tar and return its path.

    Flat: each member is stored under its bare filename, so unpacking cannot depend on where the
    directory happened to live on the machine that published it.

    Uncompressed: measured over 200 of these thumbnails, gzip -6 saves 2.1%. JPEG is already
    DCT-compressed, so compressing would cost time on every build to save nothing.
    """
    import tarfile

    with tarfile.open(dest, "w:") as tar:
        for name in sorted(f for f in os.listdir(folder) if f.endswith(".jpg")):
            tar.add(os.path.join(folder, name), arcname=name)
    print(f"[tar]     {dest} ({os.path.getsize(dest) / 1e6:.0f} MB)")
    return dest


def upload_tarball(repo_id: str, tar_path: str) -> None:
    """Publish the tarball, which is what `scripts/fetch_assets.py` and the Docker build read.

    The loose JPEGs stay in the repo alongside it so the dataset is still browsable on the Hub, but
    they are no longer on anyone's critical path: pulling them one at a time is what earns a 429.
    """
    from huggingface_hub import HfApi

    HfApi().upload_file(
        path_or_fileobj=tar_path,
        path_in_repo=TARBALL,
        repo_id=repo_id,
        repo_type="dataset",
        commit_message="feat: thumbnails as a single tarball",
    )
    print(f"[thumbs]  {TARBALL} -> https://huggingface.co/datasets/{repo_id}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--thumbs", help="directory of <frame_id>.jpg files")
    ap.add_argument("--index", action="store_true", help="upload the two vector matrices")
    ap.add_argument(
        "--artifacts", default=os.path.join(ROOT, "data", "artifacts"), help="where the matrices are read from"
    )
    ap.add_argument("--repo", default=REPO_ID)
    ap.add_argument(
        "--private", action="store_true", help="make the dataset private; the Docker build then needs a read token"
    )
    ap.add_argument(
        "--card-only", action="store_true", help="update the dataset card and stop, without re-uploading assets"
    )
    ap.add_argument(
        "--per-file", action="store_true", help="also push the loose JPEGs, so the dataset stays browsable on the Hub"
    )
    args = ap.parse_args()

    user = require_login()
    print(f"[auth]    {user}")

    if args.card_only:
        upload_card(args.repo)
        return
    if not args.thumbs and not args.index:
        sys.exit("nothing to do — pass --thumbs, --index or --card-only")

    ensure_repo(args.repo, args.private)
    upload_card(args.repo)

    if args.index:
        upload_index(args.repo, args.artifacts)

    if args.thumbs:
        cleared = require_privacy_clearance(args.artifacts, args.thumbs)
        print(
            f"[privacy] cleared {cleared['frames']} frames against "
            f"{cleared['privacy']['face_model']} / {cleared['privacy']['plate_model']}"
        )
        n = count_thumbs(args.thumbs)
        size = sum(os.path.getsize(os.path.join(args.thumbs, f)) for f in os.listdir(args.thumbs))
        print(f"[thumbs]  {n} files, {size / 1e6:.0f} MB from {args.thumbs}")

        tar_path = os.path.join(tempfile.gettempdir(), TARBALL)
        try:
            upload_tarball(args.repo, build_tarball(args.thumbs, tar_path))
        finally:
            if os.path.exists(tar_path):
                os.remove(tar_path)

        if args.per_file:
            from huggingface_hub import upload_large_folder

            # upload_large_folder, not upload_folder: it commits in batches and keeps a local resume
            # state, so 6,858 files over a domestic connection survives an interruption.
            upload_large_folder(repo_id=args.repo, folder_path=args.thumbs, repo_type="dataset")

    print(f"\npublished -> https://huggingface.co/datasets/{args.repo}")
    print("the Dockerfile pulls this at build time; nothing fetches it at runtime")


if __name__ == "__main__":
    main()
