# ---- Stage 1: Frontend ----
#
# The image previously shipped the API alone, so the deployed "Live URL" was /docs and JSON. The
# frontend has to be built here rather than committed: FE/dist is a build artifact, and a stale one
# committed by hand is worse than none.
#
# Its own stage so node never reaches the runtime image. What survives is ~310 KB of bundled JS and
# CSS; node, npm and node_modules (~200 MB) are discarded with the stage.
FROM node:22-slim AS frontend

WORKDIR /fe
# package files first: this layer is cached unless dependencies actually change, so an edit to a
# component does not re-run npm ci.
COPY FE/package.json FE/package-lock.json ./
# `ci` not `install` — it installs exactly the lockfile and fails if the two have drifted, which is
# the check that caught the lockfile being out of sync in the first place.
#
# This was `npm install` between f36f92a and now, to work around optional dependencies resolving
# differently on Windows than in a Linux container. That cause was fixed separately: d4a0071 added
# the `@emnapi/*` peer entries the lockfile was missing, under the title "sync emnapi peer
# dependencies **for npm ci**". The workaround simply outlived it.
#
# Measured 2026-08-17 in this exact base image: `npm ci` exits 0 against the committed lockfile,
# while `npm install` rewrites it — 3,735 to 3,720 lines, dropping 15 `"peer": true` markers. That
# rewrite is metadata rather than versions, so the tree it built was not wrong; the cost was the
# missing check. Every dependency in FE/package.json is a `^` range, so `install` is free to resolve
# newer minors than CI ever tested, and nothing would fail. `ci` is what makes that impossible.
RUN npm ci
COPY FE/ ./
# **`VITE_` variables are consumed here, not at runtime.** `vite build` substitutes
# `import.meta.env.VITE_*` into the bundle as literals, so a value absent at this line is absent
# from the deployed site for the life of the image — and no amount of editing the box's `.env`
# afterwards changes it. That is why Google sign-in was broken on every deploy through v1.7: the
# stage had no ARG, `.dockerignore` excludes `.env`, so the client id compiled to `''` and the
# button showed a developer instruction to a visitor.
#
# Empty default on purpose: a build with no client id must still succeed, and the frontend hides
# the button rather than rendering one that cannot work. The client id is NOT a secret — it ships
# in the bundle by design. `GOOGLE_CLIENT_SECRET` is, and it stays a runtime backend variable that
# never reaches this stage.
ARG VITE_GOOGLE_CLIENT_ID=""
ENV VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID}
# `build` is `tsc -b && vite build`, so a type error fails the image build rather than shipping.
RUN npm run build

# ---- Stage 2: Python build ----
FROM python:3.11-slim AS builder

# A real virtualenv at /opt/venv rather than `pip install --user`.
#
# `--user` installs into /root/.local, which the production stage copies to /root/.local and puts on
# PATH — but that stage also switches to a non-root user, and /root is mode 0700. The application
# user cannot traverse it, so every import fails at container start. /opt/venv is world-readable, so
# the same multi-stage split survives a non-root runtime, which is the whole point of having one.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .

# Torch is architecture-sensitive and gets its own step.
#
# On linux/amd64 the default PyPI wheel bundles CUDA (~2.5 GB) for a service that never sees a GPU,
# so it comes from PyTorch's CPU index instead. On linux/arm64 the default PyPI wheel is already
# CPU-only and the CPU index does not reliably carry aarch64 builds, so forcing that index there
# would break the build to optimise the x86 one. TARGETARCH is provided by BuildKit; the fallback
# keeps a plain `docker build` working.
#
# **torch and torchvision are installed together, from one index.** Installing only torch here left
# `open_clip_torch` to pull torchvision from PyPI, built against a different torch build — which
# installs cleanly and then fails at *runtime* with `operator torchvision::nms does not exist`,
# because torchvision's compiled operators register against one exact torch build.
#
# The versions are *read out of requirements.txt* rather than repeated here. Two literals in two
# files do not stay equal because a comment asks them to: bump requirements.txt alone and this step
# would install the old pair from the CPU index, then `-r requirements.txt` would find the conflict
# and resolve it from PyPI — silently restoring the CUDA wheel and the runtime crash this whole step
# exists to prevent. One source of truth cannot drift from itself.
#
# `test -n` matters: if the grep ever stops matching (a rename, a moved pin, an editor writing CRLF),
# an unguarded `pip install` with no arguments succeeds and does nothing, and the failure resurfaces
# as a 2.5 GB image that crashes on first search. Fail at build time instead.
ARG TARGETARCH
RUN pip install --no-cache-dir --upgrade pip \
    && if [ "${TARGETARCH:-amd64}" = "amd64" ]; then \
         TORCH_SPEC="$(grep -E '^(torch|torchvision)==' requirements.txt | tr -d '\r' | tr '\n' ' ')" \
         && { [ -n "${TORCH_SPEC# }" ] || { echo "no torch pins found in requirements.txt" >&2; exit 1; }; } \
         && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu ${TORCH_SPEC}; \
       fi \
    && pip install --no-cache-dir -r requirements.txt

# ---- Stage 3: Production ----
FROM python:3.11-slim

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Security: run as non-root. The uid is pinned to 1000 rather than left to useradd's next-free
# choice because Hugging Face Spaces expects the container's user to be 1000 and mounts its writable
# paths for that uid; an unpinned uid works locally and then fails on the Space with permission
# errors that look like a code bug.
RUN useradd -m -u 1000 appuser

# Bake the two text towers into the image (~500 MB) instead of fetching them at startup.
#
# Otherwise they download on first use, so every cold start pulls half a gigabyte from the HF hub
# before the service can answer anything — long enough to trip a platform's startup timeout, and a
# hard dependency on an external host being reachable at boot. The ingest-side models (Florence-2,
# the detector) are deliberately NOT here: they never run inside a request.
ENV HF_HOME=/opt/models \
    HF_HUB_DISABLE_TELEMETRY=1
RUN python -c "\
import open_clip; \
open_clip.create_model_and_transforms('ViT-B-16-SigLIP2', pretrained='webli'); \
open_clip.get_tokenizer('ViT-B-16-SigLIP2'); \
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" \
    && chmod -R a+rX /opt/models

# The index and the thumbnails, pulled at BUILD time from the dataset repo rather than committed.
#
# Neither is in git. The two vector matrices are 32 MB and `docs/guide/chapter-09.md` allows no
# committed file over 10 MB; the thumbnails are 85 MB and M2_DESIGN §4 says not to store frame
# images at all. The four small artifacts — frames/metadata/captions/provenance, 4.1 MB — stay
# committed, so the repo still records what the corpus *is*.
#
# Fetching here rather than per request is the point: `routes.py:frame_thumb` keeps serving from
# local disk, and no external host sits on the request path, which is what §3 removed.
#
# The dataset is public, so this needs no token: a private one would mean a credential inside every
# image build, to manage and rotate, for data derived from a public dataset.
#
# `--what index` is FATAL and `--what thumbs` is not, and the asymmetry is deliberate. Without the
# index the service cannot answer anything, so an image built without it is worthless and should
# fail here rather than deploy and 503. Without thumbnails it answers correctly and looks
# unfinished — worth degrading to, and `frame_thumb` already returns 404 for a missing file.
#
# Placed BEFORE `COPY . .` and copying only the one script it needs, so editing a route does not
# invalidate a 117 MB download layer on every rebuild. The later `COPY . .` merges into these
# directories rather than replacing them, and .dockerignore excludes the host's own copies of both
# assets, so nothing here is overwritten by whatever happens to be on a developer's disk.
#
# The thumbnail pull is one request for a tarball, not 6,858 for loose JPEGs. That mattered here
# before it mattered anywhere else: the Hub 429s an unauthenticated caller partway through the
# per-file version, which on a CI runner meant a half-populated directory after four and a half
# minutes. This build is anonymous by design — a public dataset so no credential lives in the image
# — so it would have taken the same 429 on the way to a deploy with a fixed date. Measured
# unauthenticated: 23 s for the whole corpus, download and unpack together.
# The dataset *revision* is deliberately NOT an ARG here. It is pinned in `fetch_assets.py:REVISION`
# and this build inherits it, for the reason the torch step above gives: two literals in two files do
# not stay equal because a comment asks them to, and the one that drifts would be the one deciding
# which corpus ships. Bump it there, in a reviewed commit, when a republished corpus is meant to go
# out — a publish and a release are separate decisions.
#
# Without that pin this whole stage was reproducible in appearance only: the repo id resolves to
# whatever is newest, so an unchanged commit built before and after a republish yields two different
# products, and `release/v1.0` would name some code rather than a build.
ARG ASSETS_REPO=P-057-RisingStar/scenesearch-assets
COPY scripts/fetch_assets.py scripts/fetch_assets.py
RUN python scripts/fetch_assets.py --what index  --repo "${ASSETS_REPO}" \
 && python scripts/fetch_assets.py --what thumbs --repo "${ASSETS_REPO}"

# Application code, plus the four small committed artifacts (frames, metadata, captions,
# provenance). Merges into data/artifacts/ beside the matrices fetched above rather than replacing
# the directory.
COPY . .

# The built frontend, from stage 1. After `COPY . .` on purpose: .dockerignore excludes FE/dist so a
# stale local build cannot leak into the image, and copying it second means the only dist/ that can
# ever be served is the one this build produced.
COPY --from=frontend /fe/dist ./FE/dist

# A directory for the review database, and one beside it for its backups.
#
# The reviews are the one thing here a container restart must not destroy, and the obvious way to
# protect them — mounting a volume over `data/` — is wrong: the index and the thumbnails were
# fetched into that directory at build time, and a volume over it hides them, so the service comes
# up with no corpus at all. The buffer therefore gets its own subdirectory that a deploy can cover
# on its own, and `deploy/docker-compose.prod.yml` points REVIEW_DB into it.
#
# It is created HERE, in the image, rather than left to the volume, because Docker seeds a new
# named volume from whatever the image has at that path — including its ownership. With no such
# path in the image the volume is created root-owned, the non-root user above cannot write into it,
# and the first verdict of the session fails with a permission error. That failure is invisible in
# development, where the same mount is a host bind owned by the developer.
RUN mkdir -p /app/data/reviews /app/data/backups

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Which build this image is, reported by `/health` and shown in the UI. Passed in rather than read
# from git, because `.dockerignore` excludes `.git` — a container has no repository to ask.
#
#     docker compose ... build --build-arg RELEASE="$(git describe --tags)"
#
# Last of the build args on purpose: it changes every release and would otherwise bust the cache for
# every layer under it. Here it invalidates nothing but the ENV itself.
ARG RELEASE=unknown
ENV RELEASE=${RELEASE}

# Generous start-period: the container loads the corpus and warms both text towers before it is
# ready, and being killed mid-warmup would loop forever.
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# `--no-proxy-headers`: uvicorn's own X-Forwarded-For handling is on by default and rewrites the
# client address, which is the value the rate limiter charges. Its `*` mode reads the *first* entry
# in the header — the one a client writes — so leaving it on hands anyone a fresh identity per
# request. `src/api/ratelimit.py:client_key` makes that decision instead, from TRUST_PROXY_HEADERS,
# and takes the last entry. Nothing here reads request.url or the scheme, so there is nothing else
# the middleware was doing for us.
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
