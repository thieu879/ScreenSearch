"""Dedicated privacy detection for faces and licence plates.

The retrieval detector is deliberately not reused here. Object boxes describe vehicles and
pedestrians; they do not locate the privacy-sensitive pixels inside those objects. This module
keeps the privacy model and its cache separate from retrieval metadata.

The runtime backend is Ultralytics because it can load either a face detector or a licence-plate
detector from a local, pinned weight file. The model paths are explicit inputs so a corpus records
exactly which weights produced its redactions:

    python scripts/privacy_detector.py --frames ... --out ... \
        --face-model models/face.pt --plate-model models/license-plate.pt
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any

PRIVACY_LABELS = frozenset({"face", "license_plate"})
FACE_LABELS = frozenset({"face", "person_face", "head"})
PLATE_LABELS = frozenset({"license_plate", "licence_plate", "plate", "number_plate"})
DEFAULT_THRESHOLD = 0.35

# Plates get a lower default than faces, and the asymmetry is structural rather than a taste for
# caution. A missed *face* is usually still redacted, because `anonymise.py` unions the dedicated
# detector with a head band derived from every `person` box in the retrieval cache -- that union is
# where ~89% of redacted area comes from. **A missed plate has no second source.** Nothing else in
# the pipeline knows where a plate is, so whatever this model does not score above threshold ships
# as-is.
#
# Fitted on the two misses review found after the imgsz fix: a motorbike plate on clip13 scores 0.21
# and the green cart's plate on clip17 scores 0.20. Both sat under a 0.25 cut. 0.15 clears both with
# margin.
#
# **Not lower, and the reason is what the obligation actually is.** The first attempt at this
# constant was 0.10, reasoning that headroom is cheap because plate boxes are small. That optimises
# the wrong quantity: the duty is to stop a vehicle being *identified*, and at this camera's working
# distance most plates in this corpus resolve as a bright rectangle with no legible characters. A
# smudge nobody can read is not personal data, so mosaicking it buys no privacy and spends corpus
# quality -- these thumbnails are the served images. Detectability is the proxy; legibility is the
# thing. Where the two disagree, follow legibility.
DEFAULT_PLATE_THRESHOLD = 0.15

# Inference resolution, and the single most important number in this file.
#
# Ultralytics defaults to 640. A 1440x1080 frame letterboxed to 640 loses a factor of 2.25, so a
# motorbike plate ~20px wide in the source is ~9px at inference -- around the stride-8 floor, where
# a nano detector cannot resolve it at any confidence. Measured on five Hanoi frames where review
# found readable plates left unblurred:
#
#     imgsz  640: 1 plate found (conf 0.35), 2 (conf 0.25)
#     imgsz 1280: 11 plates (conf 0.35), 13 (conf 0.25)
#     imgsz 1920: 14 plates (conf 0.25), at 1.8x the time for one extra plate
#
# Sweeping confidence at 640 never gets there: dropping to 0.05 still yields 3. **The plates were
# not being scored low, they were not being seen.** This was invisible on nuScenes, which is
# 1600x900 and blurred at source, so the gap only appeared on the first unblurred corpus.
#
# 1280 costs ~111 ms/frame against ~80 at 960 -- about 2.6 extra minutes over a 2,200-frame corpus.
DEFAULT_IMGSZ = 1280


@dataclass(frozen=True)
class PrivacyConfig:
    face_model: str
    plate_model: str
    face_threshold: float = DEFAULT_THRESHOLD
    plate_threshold: float = DEFAULT_PLATE_THRESHOLD
    imgsz: int = DEFAULT_IMGSZ

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": "ultralytics",
            "face_model": self.face_model,
            "plate_model": self.plate_model,
            "face_threshold": self.face_threshold,
            "plate_threshold": self.plate_threshold,
            "imgsz": self.imgsz,
        }


def _required_model(value: str | None, env_name: str) -> str:
    model = value or os.environ.get(env_name, "")
    if not model:
        cli_name = {
            "SCENESEARCH_PRIVACY_FACE_MODEL": "--face-model",
            "SCENESEARCH_PRIVACY_PLATE_MODEL": "--plate-model",
        }.get(env_name, env_name.lower().replace("_", "-"))
        raise RuntimeError(f"privacy model is not configured; pass {cli_name} or set {env_name}")
    return model


def config_from_environment(
    face_model: str | None = None,
    plate_model: str | None = None,
    face_threshold: float | None = None,
    plate_threshold: float | None = None,
    imgsz: int | None = None,
) -> PrivacyConfig:
    """Build an explicit privacy configuration from CLI values or environment variables."""
    return PrivacyConfig(
        face_model=_required_model(face_model, "SCENESEARCH_PRIVACY_FACE_MODEL"),
        plate_model=_required_model(plate_model, "SCENESEARCH_PRIVACY_PLATE_MODEL"),
        face_threshold=float(
            face_threshold
            if face_threshold is not None
            else os.environ.get("SCENESEARCH_PRIVACY_FACE_THRESHOLD", DEFAULT_THRESHOLD)
        ),
        plate_threshold=float(
            plate_threshold
            if plate_threshold is not None
            else os.environ.get("SCENESEARCH_PRIVACY_PLATE_THRESHOLD", DEFAULT_PLATE_THRESHOLD)
        ),
        imgsz=int(imgsz if imgsz is not None else os.environ.get("SCENESEARCH_PRIVACY_IMGSZ", DEFAULT_IMGSZ)),
    )


def _canonical_label(label: str, expected: str) -> str:
    normalized = label.lower().replace("-", "_").replace(" ", "_")
    if expected == "face" and normalized in FACE_LABELS:
        return "face"
    if expected == "license_plate" and normalized in PLATE_LABELS:
        return "license_plate"
    # A dedicated one-class model is allowed to call its only class "0" or "object".
    if normalized in {"0", "object", "target"}:
        return expected
    return ""


class PrivacyDetector:
    """Run the configured face and plate models and write a resumable JSONL cache."""

    def __init__(self, config: PrivacyConfig, device: str | None = None):
        self.config = config
        self.device = device
        self._face = None
        self._plate = None

    def _load(self):
        try:
            from ultralytics import YOLO
        except ImportError as exc:  # pragma: no cover - environment guard
            raise RuntimeError(
                "privacy detection requires the optional 'ultralytics' package; install it in the research environment"
            ) from exc
        if self._face is None:
            self._face = YOLO(self.config.face_model)
        if self._plate is None:
            self._plate = YOLO(self.config.plate_model)

    def _model_detections(self, model, image_path: str, expected: str, threshold: float) -> list[dict]:
        """Run one model over one frame. `imgsz` and device come from the instance, not the caller —
        a per-call inference size is how two frames of one corpus end up detected differently."""
        kwargs: dict[str, Any] = {"conf": threshold, "verbose": False, "imgsz": self.config.imgsz}
        if self.device:
            kwargs["device"] = self.device
        result = model.predict(image_path, **kwargs)[0]
        names = result.names
        out: list[dict] = []
        if result.boxes is None:
            return out
        for box, score, cls in zip(result.boxes.xyxy, result.boxes.conf, result.boxes.cls):
            raw_label = names[int(cls)] if isinstance(names, (list, tuple)) else names[int(cls)]
            label = _canonical_label(str(raw_label), expected)
            if not label:
                continue
            out.append(
                {
                    "label": label,
                    "score": round(float(score), 4),
                    "box": [round(float(v), 1) for v in box.tolist()],
                }
            )
        return out

    def detect(self, image_path: str) -> list[dict]:
        self._load()
        return self._model_detections(
            self._face, image_path, "face", self.config.face_threshold
        ) + self._model_detections(self._plate, image_path, "license_plate", self.config.plate_threshold)

    def detect_to_cache(self, image_paths: list[str], cache_path: str) -> dict[str, list[dict]]:
        """Detect only missing basenames and atomically append complete cache rows."""
        cached = load_cache(cache_path, self.config)
        todo = [path for path in image_paths if os.path.basename(path) not in cached]
        if todo:
            self._load()
            os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
            with open(cache_path, "a", encoding="utf-8") as handle:
                for path in todo:
                    name = os.path.basename(path)
                    detections = self.detect(path)
                    handle.write(
                        json.dumps(
                            {
                                "image": name,
                                "dets": detections,
                                "privacy": self.config.as_dict(),
                            }
                        )
                        + "\n"
                    )
                    cached[name] = detections
        return {os.path.basename(path): cached[os.path.basename(path)] for path in image_paths}


def load_cache(cache_path: str, config: PrivacyConfig | None = None) -> dict[str, list[dict]]:
    """Read only privacy-cache rows; reject caches produced by another detector configuration."""
    if not os.path.exists(cache_path):
        return {}
    cached: dict[str, list[dict]] = {}
    wanted = config.as_dict() if config else None
    with open(cache_path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if wanted is not None and row.get("privacy") != wanted:
                continue
            cached[row["image"]] = row.get("dets", [])
    return cached


def privacy_config_from_cache(cache_path: str) -> dict[str, Any] | None:
    """Return the one configuration every cache row shares, or None for an empty cache.

    Reading only the first row would be wrong: ``detect_to_cache`` **appends**, so a cache can
    legitimately hold rows from two model configurations, and ``load_detections`` reads all of them.
    Taking the first row's config would then stamp provenance certifying weights that produced only
    part of the corpus. A mixed cache is refused instead.
    """
    if not os.path.exists(cache_path):
        return None
    configs: list[dict[str, Any] | None] = []
    with open(cache_path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                config = json.loads(line).get("privacy")
                if config not in configs:
                    configs.append(config)
    if not configs:
        return None
    if len(configs) > 1:
        raise ValueError(
            f"{cache_path} mixes {len(configs)} privacy configurations; no single set of weights "
            "describes this corpus. Re-run detection into a fresh cache."
        )
    return configs[0]


def main() -> None:  # pragma: no cover - thin CLI wrapper
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--face-model")
    ap.add_argument("--plate-model")
    ap.add_argument("--face-threshold", type=float)
    ap.add_argument("--plate-threshold", type=float)
    ap.add_argument(
        "--imgsz",
        type=int,
        help=f"inference resolution (default {DEFAULT_IMGSZ}); lowering it to the "
        "ultralytics default of 640 stops small plates being found at all",
    )
    ap.add_argument("--device")
    args = ap.parse_args()
    config = config_from_environment(
        args.face_model, args.plate_model, args.face_threshold, args.plate_threshold, args.imgsz
    )
    paths = [
        p
        for directory in args.frames
        for p in sorted(
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.lower().endswith((".jpg", ".jpeg", ".png"))
        )
    ]
    PrivacyDetector(config, args.device).detect_to_cache(paths, args.out)
    print(f"[privacy] {len(paths)} frames -> {args.out}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
