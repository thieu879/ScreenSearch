from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from privacy_detector import (  # noqa: E402
    PrivacyConfig,
    _canonical_label,
    config_from_environment,
    load_cache,
    privacy_config_from_cache,
)


def test_canonical_labels_are_privacy_specific():
    assert _canonical_label("face", "face") == "face"
    assert _canonical_label("license plate", "license_plate") == "license_plate"
    assert _canonical_label("truck", "license_plate") == ""


def test_model_paths_are_required(monkeypatch):
    monkeypatch.delenv("SCENESEARCH_PRIVACY_FACE_MODEL", raising=False)
    monkeypatch.delenv("SCENESEARCH_PRIVACY_PLATE_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="privacy model is not configured"):
        config_from_environment()


def test_cache_is_rejected_when_configuration_changes(tmp_path):
    config = PrivacyConfig("face-a.pt", "plate-a.pt")
    path = tmp_path / "privacy.jsonl"
    path.write_text(
        json.dumps(
            {
                "image": "000001.jpg",
                "dets": [],
                "privacy": config.as_dict(),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert load_cache(str(path), config) == {"000001.jpg": []}
    assert load_cache(str(path), PrivacyConfig("face-b.pt", "plate-a.pt")) == {}
    assert privacy_config_from_cache(str(path)) == config.as_dict()


def test_empty_cache_has_no_provenance(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    assert privacy_config_from_cache(str(path)) is None


def test_a_cache_mixing_two_configurations_is_refused(tmp_path):
    """`detect_to_cache` appends, so one file can hold rows from two model configurations while
    `load_detections` reads all of them. Reporting the first row's config would stamp provenance
    certifying weights that produced only part of the corpus."""
    path = tmp_path / "mixed.jsonl"
    path.write_text(
        "".join(
            json.dumps(
                {
                    "image": name,
                    "dets": [],
                    "privacy": config.as_dict(),
                }
            )
            + "\n"
            for name, config in [
                ("0001.jpg", PrivacyConfig("face-a.pt", "plate-a.pt")),
                ("0002.jpg", PrivacyConfig("face-b.pt", "plate-a.pt")),
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mixes 2 privacy configurations"):
        privacy_config_from_cache(str(path))
