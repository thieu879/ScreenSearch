"""The source-video manifest: the join a result uses to name the footage it came from.

Two things are worth asserting here and neither is the JSON parsing. The first is that **a corpus
without a manifest degrades silently** — that is what keeps the served nuScenes corpus behaving
exactly as it did, and a loader that raised on a missing file would take the product down for a
feature it cannot use. The second is the **separator**, which is the one way a deep link can look
right and seek nowhere.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

from src.services.search.artifacts import Corpus
from src.services.search.service import source_clip
from src.services.search.videos import VideoManifest, load_manifest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HANOI = os.path.join(REPO, "data/staging/hanoi/artifacts")

CLIP = {
    "webpage_url": "https://www.youtube.com/watch?v=cgosbZZmns4",
    "title": "Hà Nội ơi (195) Mưa",
    "uploader": "Hong Xuan",
    "license": "Creative Commons Attribution license (reuse allowed)",
}


class TestManifestAbsence:
    """A corpus that kept no source video is a complete corpus, not a broken one."""

    def test_a_missing_manifest_loads_as_empty_rather_than_raising(self, tmp_path):
        assert load_manifest(str(tmp_path)).clips == {}

    def test_an_empty_manifest_is_falsy_so_callers_can_branch_on_it(self):
        assert not VideoManifest()
        assert VideoManifest(clips={"a": CLIP})

    def test_an_empty_manifest_offers_no_link(self):
        assert VideoManifest().deep_link("a", 1.0) is None

    def test_the_served_nuscenes_corpus_has_no_manifest(self):
        """Not an oversight to be fixed later: the source blobs were pruned after extraction."""
        assert not load_manifest(os.path.join(REPO, "data/artifacts"))


class TestDeepLink:
    def test_it_appends_the_start_time_to_an_existing_query_string(self):
        assert VideoManifest({"c": CLIP}).deep_link("c", 257.4) == f"{CLIP['webpage_url']}&t=257"

    def test_it_opens_a_query_string_when_the_url_has_none(self):
        """`videos.json` declares the template with `&` because every clip in it is a watch URL. A
        manifest built from a bare URL would otherwise produce `…mp4&t=257`, which seeks nowhere."""
        bare = VideoManifest({"c": {"webpage_url": "https://example.org/clip.mp4"}})
        assert bare.deep_link("c", 12.0) == "https://example.org/clip.mp4?t=12"

    @pytest.mark.parametrize("video_id,ts", [("unknown", 1.0), ("c", -1.0)])
    def test_it_returns_none_rather_than_guessing(self, video_id, ts):
        assert VideoManifest({"c": CLIP}).deep_link(video_id, ts) is None

    def test_a_clip_with_no_url_yields_no_link(self):
        assert VideoManifest({"c": {"title": "x"}}).deep_link("c", 1.0) is None


class TestCredit:
    def test_it_carries_the_attribution_cc_by_requires(self):
        assert VideoManifest({"c": CLIP}).credit("c") == {
            "title": CLIP["title"],
            "uploader": CLIP["uploader"],
            "license": CLIP["license"],
        }

    def test_it_omits_what_the_manifest_does_not_hold_rather_than_emitting_blanks(self):
        assert VideoManifest({"c": {"webpage_url": "u", "title": ""}}).credit("c") == {}


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(HANOI)


@pytest.mark.skipif(not os.path.exists(HANOI), reason="data/staging/hanoi not ingested")
class TestTheRealHanoiManifest:
    """Against the corpus this feature exists for. Skipped where the staging corpus is not present."""

    def test_every_clip_can_be_linked_and_credited(self, manifest):
        assert len(manifest.clips) == 24
        assert all(manifest.deep_link(v, 0.0) for v in manifest.clips)
        assert all("Creative Commons Attribution" in manifest.credit(v)["license"] for v in manifest.clips)

    def test_every_frame_lands_inside_the_clip_it_claims(self, manifest):
        """A timestamp past the video's duration links to a moment that does not exist. Clip-relative
        is the assumption the whole affordance rests on, so it is asserted rather than trusted."""
        with open(os.path.join(HANOI, "frames.jsonl"), encoding="utf-8") as f:
            frames = [json.loads(line) for line in f if line.strip()]
        overruns = [
            r for r in frames if r["timestamp_s"] < 0 or r["timestamp_s"] > manifest.clips[r["video_id"]]["duration"]
        ]
        assert overruns == [], f"{len(overruns)} of {len(frames)} frames fall outside their clip"


class TestSourceClip:
    """The join itself: corpus frame -> manifest clip -> a link and a credit.

    Every way this returns None is ordinary — a frame with no `video_id`, a clip the manifest does
    not name, or no manifest at all — and none of them may cost the caller a result.
    """

    @staticmethod
    def corpus_of(video_of: dict[str, str], timestamp_of: dict[str, float]) -> Corpus:
        ids = list(video_of)
        zeros = np.zeros((len(ids), 4), dtype="float32")
        return Corpus(
            frame_ids=ids,
            vectors=zeros,
            caption_vectors=zeros,
            scene_of=dict.fromkeys(ids, "s0"),
            timestamp_of=timestamp_of,
            metadata_of={},
            caption_of={},
            provenance={},
            video_of=video_of,
        )

    def test_it_links_the_frame_to_its_own_second_of_footage(self):
        corpus = self.corpus_of({"f0": "c"}, {"f0": 257.4})
        clip = source_clip(corpus, VideoManifest({"c": CLIP}), "f0")
        assert clip.url == f"{CLIP['webpage_url']}&t=257"
        assert clip.uploader == CLIP["uploader"]
        assert "Creative Commons Attribution" in clip.license

    @pytest.mark.parametrize(
        "video_of,manifest",
        [
            ({"f0": ""}, VideoManifest({"c": CLIP})),  # the corpus records no source clip
            ({"f0": "other"}, VideoManifest({"c": CLIP})),  # the manifest does not name it
            ({"f0": "c"}, VideoManifest()),  # the corpus kept no footage — nuScenes
        ],
    )
    def test_it_returns_none_rather_than_a_link_it_cannot_stand_behind(self, video_of, manifest):
        assert source_clip(self.corpus_of(video_of, {"f0": 1.0}), manifest, "f0") is None

    def test_an_older_corpus_with_no_video_of_costs_the_link_not_the_result(self):
        """`video_of` defaults to empty, so a `Corpus` built before this existed still answers."""
        corpus = Corpus(
            frame_ids=["f0"],
            vectors=np.zeros((1, 4), dtype="float32"),
            caption_vectors=np.zeros((1, 4), dtype="float32"),
            scene_of={"f0": "s0"},
            timestamp_of={"f0": 1.0},
            metadata_of={},
            caption_of={},
            provenance={},
        )
        assert source_clip(corpus, VideoManifest({"c": CLIP}), "f0") is None
