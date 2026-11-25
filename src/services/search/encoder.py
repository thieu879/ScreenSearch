"""Query-side text encoders.

Only the **text** towers run here. Images were embedded and captioned during ingest, so a request
never touches SigLIP2's vision tower, Florence-2, or the detector — see M2_DESIGN §3. That is what
keeps a query at tens of milliseconds while ingest is measured in CPU-hours.

Two encoders because the query is asked in two different spaces, and they are not interchangeable:

  * **SigLIP2** — matched against image embeddings. Chosen on M1's measurement: mAP-lift +0.277
    single / +0.271 multi, against CLIP's +0.179 / +0.167.
  * **MiniLM** — matched against *caption* embeddings, for the §6.1 rejection check only. It never
    ranks anything.

Both are loaded lazily and then cached for the process. Loading is slow (hundreds of MB), so it
happens at startup via `warmup()` rather than inside the first request — M1 hit exactly this and
reported a query at 774 ms against its true 11 ms because a lazily-loaded model loaded inside the
timed section.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np


class SiglipTextEncoder:
    """SigLIP2 text tower, via open_clip. Vectors are L2-normalised onto the cosine scale.

    SigLIP2 trains with a sigmoid pairwise loss rather than CLIP's softmax-over-batch contrastive
    loss, so its raw logits are not comparable to CLIP's — normalising is what puts queries and the
    stored corpus vectors on the one scale the index assumes.
    """

    def __init__(self, model_name: str, pretrained: str, device: str = "cpu"):
        import open_clip
        import torch

        self.torch = torch
        self.name = f"openclip:{model_name}:{pretrained}"
        self.device = device
        model, _, _ = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
        self.tokenizer = open_clip.get_tokenizer(model_name)
        self.model = model.eval().to(device)
        # The sigmoid loss above is trained *with* an affine transform, and the checkpoint carries
        # it. Read once: these are constants of the weights, not of a request. CLIP-family models
        # have no `logit_bias`, so a 0.0 default keeps this class usable if the encoder is swapped.
        with torch.no_grad():
            self.logit_scale = float(model.logit_scale.exp().cpu())
            bias = getattr(model, "logit_bias", None)
            self.logit_bias = float(bias.cpu()) if bias is not None else 0.0

    def encode(self, text: str) -> np.ndarray:
        """One query string → a single L2-normalised vector."""
        tok = self.tokenizer([text]).to(self.device)
        with self.torch.no_grad():
            f = self.model.encode_text(tok)
            f = f / f.norm(dim=-1, keepdim=True)
        return f.cpu().numpy().astype("float32")[0]


class CaptionTextEncoder:
    """MiniLM sentence encoder, for scoring a query against cached captions."""

    def __init__(self, model_name: str, device: str = "cpu"):
        from sentence_transformers import SentenceTransformer

        self.name = model_name
        self.model = SentenceTransformer(model_name, device=device)

    def encode(self, text: str) -> np.ndarray:
        return self.model.encode([text], normalize_embeddings=True, convert_to_numpy=True).astype("float32")[0]


# `get_settings` is imported inside the factories, not at module scope, so the two encoder *classes*
# stay importable without the app's settings stack. `scripts/tag_scenes.py` needs SigLIP2's text
# tower at ingest and runs in the research environment, which has open_clip but no pydantic-settings.
# The alternative was a second copy of the text tower for ingest — and ingest and query writing
# vectors into different spaces is the one failure this module exists to prevent.


@lru_cache(maxsize=1)
def get_query_encoder() -> SiglipTextEncoder:
    from src.config import get_settings

    s = get_settings()
    return SiglipTextEncoder(s.siglip_model, s.siglip_pretrained)


@lru_cache(maxsize=1)
def get_caption_encoder() -> CaptionTextEncoder:
    from src.config import get_settings

    return CaptionTextEncoder(get_settings().caption_text_model)


def sigmoid_probability(cosine: float, logit_scale: float, logit_bias: float) -> float:
    """SigLIP2's trained pairwise calibration: `sigmoid(scale * cos + bias)`.

    Pure, so it is testable without loading several hundred MB of weights.
    """
    return float(1.0 / (1.0 + math.exp(-(logit_scale * cosine + logit_bias))))


def calibrated_match_probability(cosine: float) -> float | None:
    """Cosine → the match probability SigLIP2 was actually trained to emit. None if uncalibrated.

    A raw cosine is *not* a score on a 0–1 scale, and presenting it as a percentage is the bug this
    exists to fix: measured on this corpus, the single best frame of 6,858 for "pedestrian in the
    rain" scores 0.164, which reads as "16%" while being the 99.985th percentile. Meanwhile
    meaningless input still scores 0.09. The whole usable range is ~0.09–0.17, and it moves per
    query — so the raw number cannot be compared across two searches, let alone read as a percent.

    Under the sigmoid loss the cosine is the *input* to a learned affine transform, and those two
    parameters ship inside the checkpoint. Applying them puts that same frame at 0.85 and the
    meaningless input at 0.001. The transform is strictly monotonic, so **ranking is unchanged** —
    this is a display concern and cannot alter retrieval.

    Returns None when the tower has not been loaded, which is deliberate: `build_hits` runs in
    tests that never load a model, and paying that load to decorate a score would be a bad trade.
    """
    if get_query_encoder.cache_info().currsize == 0:
        return None
    encoder = get_query_encoder()
    return sigmoid_probability(cosine, encoder.logit_scale, encoder.logit_bias)


def warmup() -> None:
    """Load both towers and run one forward pass, so the first real request is not the slow one."""
    get_query_encoder().encode("warmup")
    get_caption_encoder().encode("warmup")
