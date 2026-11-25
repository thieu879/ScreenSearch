"""Captioning at query time, so ingest does not have to — the live-ingest path.

**This is the one place a vision model runs inside a request, and it is opt-in.** Everywhere else
M2_DESIGN §3's split holds absolutely: ingest writes, query reads, and `encoder.py` loads text towers
only. That split is why a query is 76 ms. Nothing here changes the default path — a corpus ingested
normally never reaches this module, because `Corpus.captions_deferred` is False and
`service.verify` does not call in.

**Why it exists.** §6.1 chose option B over option C on precisely this argument: rejection only has
to judge the frames it is about to return, so captioning is O(k) per query rather than O(N) across
the archive. On the nuScenes corpus that stayed theoretical — every frame was captioned at ingest
anyway, so the runtime path was a lookup. Taking option B literally is what makes ingest fast enough
to run in front of an audience. Measured on 834 frames, Quadro P2000, 2026-08-03:

    full ingest       18m 03s     (captioner 15m 05s of it)
    --skip-captions    4m 25s     detect 2m04 + embed 54s + thumbs/metadata/tags

Against ~7 min of source video that is 4×, and it crosses the line from slower than the footage to
faster than it.

**The cost, and it is worse than the ingest-side arithmetic suggests.** Measured on the serving
environment (`.venv`, **CPU** — `torch` there has no CUDA, unlike the research env that does the
ingest), a query whose head is uncaptioned spent **33.8 s** captioning 5 frames, or **~6.8 s/frame**;
the very first query additionally pays ~20 s to load Florence-2. The second identical query took
**18 ms**. So the shape is: slow once per *frame*, never again — but "once" is tens of seconds on
CPU, not the ~1.1 s/frame the GPU ingest would suggest. On a CPU-served demo, pre-warm the queries
you intend to run, or serve from a machine with the GPU. Retrieval, ranking, relations and scene
tags are untouched throughout and still land in ~100 ms, so results are on screen while the verdict
resolves.

**Captions come from the thumbnail, not the original.** The originals are not in the deployed
container — the Dockerfile pulls artifacts and thumbnails from the Hugging Face dataset and nothing
else — so captioning them would work on the demo laptop and fail in production, which is the exact
shape of failure §10.5 is about. Thumbnails are also already redacted, so no generative model ever
sees an unblurred face or plate.

**That cost is now measured, and it moves verdicts.** Same 834 frames, same vectors, same queries —
only the caption source differs (1280 px at ingest vs 320 px thumbnail here):

    query                          full-res      thumbnail
    "a truck on the highway"       0.737 high    0.659 high
    "a pedestrian on the street"   0.530 high    0.458 low     <- crossed tau_confident

Two queries is an indication, not a calibration, but the direction is consistent and the size (~0.08)
is enough to cross a band boundary. A corpus ingested this way therefore needs its band re-fit
(§10.3) more urgently than one that merely changed domain, and until then a `low` on this path should
be read as "unverified", not as "probably wrong".
"""

from __future__ import annotations

import json
import os
import threading

from src.services.search.artifacts import Corpus

# Must match `experiments/m1/scenesearch/pipelines/caption_retrieval.py` exactly. A caption written
# here is compared against captions written there by the same threshold, so a different prompt or
# beam count would put the two populations on different scales while looking identical in the file.
CAPTIONER = "florence-community/Florence-2-base"
CAPTION_PROMPT = "<DETAILED_CAPTION>"
MAX_NEW_TOKENS = 128
NUM_BEAMS = 3

# Captions filled in after ingest, beside the artifacts they belong to. Text only: the caption is the
# expensive thing worth persisting, while re-embedding it with MiniLM costs milliseconds and avoids
# a cache that could disagree with the encoder the service is currently running.
DEFERRED_CACHE = "captions_deferred.jsonl"

_lock = threading.Lock()


def _strip_pad(caption: str) -> str:
    """Drop `<pad>` runs left by decoding — the same normalisation the ingest cache applies."""
    return caption.replace("<pad>", "").strip()


class ImageCaptioner:
    """Florence-2 `<DETAILED_CAPTION>` over one image at a time.

    Batching is deliberately absent: this captions at most `verify_top_k` frames, and a batch of 5
    would hold five decoded sequences in VRAM to save a fraction of a second on a path that is
    already the slow one by choice.
    """

    def __init__(self, model_name: str = CAPTIONER, device: str | None = None):
        import torch
        from transformers import AutoProcessor, Florence2ForConditionalGeneration

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.name = model_name
        # Native transformers implementation, NOT `trust_remote_code` — the bundled remote code
        # predates transformers v5 and dies on the moved `forced_bos_token_id`. Same load as
        # `scenesearch/pipelines/caption_retrieval.py`, which is what makes a caption written here
        # comparable to one written at ingest; a different code path would be a different
        # distribution scored against the same threshold.
        self._processor = AutoProcessor.from_pretrained(model_name)
        self._model = (
            Florence2ForConditionalGeneration.from_pretrained(model_name, dtype=torch.float32).eval().to(self.device)
        )

    def caption(self, image_path: str) -> str:
        """One image file → its detailed caption. Returns "" if the file is missing."""
        from PIL import Image

        if not os.path.exists(image_path):
            return ""
        with Image.open(image_path) as im:
            image = im.convert("RGB")
        inputs = self._processor(text=CAPTION_PROMPT, images=image, return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            ids = self._model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, num_beams=NUM_BEAMS, do_sample=False)
        decoded = self._processor.batch_decode(ids, skip_special_tokens=False)[0]
        parsed = self._processor.post_process_generation(decoded, task=CAPTION_PROMPT, image_size=image.size)
        return _strip_pad(parsed[CAPTION_PROMPT])


_captioner: ImageCaptioner | None = None


def get_captioner() -> ImageCaptioner:
    """Process-wide captioner, loaded on first use.

    Not `lru_cache`d like the text encoders: those are warmed at startup because every request needs
    them, while this one must stay unloaded on a normally-ingested corpus — its weights are ~500 MB
    that such a deployment has no reason to hold.
    """
    global _captioner
    if _captioner is None:
        _captioner = ImageCaptioner()
    return _captioner


def thumb_path(frame_id: str) -> str:
    """Where the redacted thumbnail for a frame lives — the only image the service is guaranteed."""
    from src.config import get_settings

    return os.path.join(get_settings().thumbs_dir, f"{frame_id}.jpg")


def read_cache(artifacts_dir: str) -> dict[str, str]:
    """frame_id → caption, for captions written after ingest. Absent file means none yet."""
    path = os.path.join(artifacts_dir, DEFERRED_CACHE)
    if not os.path.exists(path):
        return {}
    out: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                out[row["frame_id"]] = row["caption"]
    return out


def append_cache(artifacts_dir: str, frame_id: str, caption: str) -> None:
    """Persist one caption. Appended, so an interrupted demo keeps what it already paid for."""
    os.makedirs(artifacts_dir, exist_ok=True)
    with open(os.path.join(artifacts_dir, DEFERRED_CACHE), "a", encoding="utf-8") as f:
        f.write(json.dumps({"frame_id": frame_id, "caption": caption}, ensure_ascii=False) + "\n")


def ensure_captions(corpus: Corpus, frame_ids: list[str]) -> int:
    """Give these frames a caption vector, captioning and embedding whatever is still missing.

    Returns how many frames were newly captioned — 0 on the second identical query, which is what
    makes a demo feel slow once rather than slow always. Mutates `corpus` in place: the dataclass is
    frozen against rebinding attributes, not against filling in a row of an array it already owns.
    """
    from src.config import get_settings
    from src.services.search.encoder import get_caption_encoder

    missing = [f for f in frame_ids if not corpus.caption_of.get(f)]
    if not missing:
        return 0

    artifacts_dir = get_settings().artifacts_dir
    encoder = get_caption_encoder()
    position = {fid: n for n, fid in enumerate(corpus.frame_ids)}
    captioned = 0

    # One lock for the whole fill rather than one per frame: FastAPI runs sync handlers in a
    # threadpool, so two concurrent queries can want the same frame, and the wasteful outcome is two
    # threads captioning it simultaneously on one GPU rather than one waiting.
    with _lock:
        for frame_id in missing:
            if corpus.caption_of.get(frame_id) or frame_id not in position:
                continue  # filled while this thread waited, or not part of this corpus
            caption = get_captioner().caption(thumb_path(frame_id))
            if not caption:
                continue  # no thumbnail: leave the row zeroed rather than assert a caption
            append_cache(artifacts_dir, frame_id, caption)
            corpus.caption_of[frame_id] = caption
            corpus.caption_vectors[position[frame_id]] = encoder.encode(caption).astype("float32")
            captioned += 1
    return captioned


def embed_cached(corpus: Corpus) -> int:
    """Embed captions that are known but whose vector row is still zero — the post-restart path.

    A restart reloads cached caption *text* but not the vectors, because embedding is the service's
    job and doing it at load time would put MiniLM in the startup path of every deployment. Cheap
    enough to do lazily: MiniLM is milliseconds, and the expensive half was already paid for.
    """
    from src.services.search.encoder import get_caption_encoder

    rows = [
        (n, f)
        for n, f in enumerate(corpus.frame_ids)
        if corpus.caption_of.get(f) and not corpus.caption_vectors[n].any()
    ]
    if not rows:
        return 0
    encoder = get_caption_encoder()
    for n, frame_id in rows:
        corpus.caption_vectors[n] = encoder.encode(corpus.caption_of[frame_id]).astype("float32")
    return len(rows)


def coverage(corpus: Corpus) -> dict[str, int]:
    """How much of the corpus can currently be rejection-checked. For `/status` and the demo."""
    have = sum(1 for f in corpus.frame_ids if corpus.caption_of.get(f))
    return {"captioned": have, "total": len(corpus.frame_ids), "missing": len(corpus.frame_ids) - have}


# The zeros a deferred ingest writes into `caption_vectors.npy` are not a neutral placeholder: a zero
# row scores 0.0 against every query, and `classify` reads 0.0 as `no_match`. That is safe only
# because `captions_deferred` gates this module in. If the flag and the zeros ever disagree — a
# deferred corpus served by a build that ignores the flag — the service refuses every query while
# looking entirely healthy. `ingest_folder.write_provenance` writes both, in one function, for that
# reason. `CAPTION_DIM` there must stay equal to this.
CAPTION_DIM = 384
