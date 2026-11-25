"""Redacted moment clips: the routes, and the two refusals that matter more than the routes.

**An unverified manifest must not load.** `build_moment_clips.py` decodes its own encoded output and
re-runs the face and plate detectors on it; when that still finds something it writes
`verified: false` and says the clips must not be used. That refusal has to survive someone pointing
a server at the directory anyway, which is what these tests hold in place.

**An id off a URL must not become a path.** Same posture as `/thumb`: the manifest is a whitelist,
and `path_of` re-checks the resolved path against the store's own directory.
"""

from __future__ import annotations

import json
import os

import pytest

from src.services.search import moments as moments_module
from src.services.search.moments import load_moments

FRAME = "abc_CAM_FRONT"
CLIP = {
    "id": "m01",
    "video_id": "clip06_hanoi",
    "query": "a motorbike cutting into our lane",
    "frame_id": FRAME,
    "keyframe_timestamp_s": 107.107,
    "window_s": [103.107, 109.107],
    "fps": 10,
    "media_file": "m01_clip06_hanoi.mp4",
    "sha256": "0" * 64,
    "bytes": 12,
    "deep_link": "https://www.youtube.com/watch?v=bd9YW84zLmE&t=107",
    "events": [[5.7, 8.7, "cut_in"]],
    "verified": True,
    "camera_h_m": 1.31,
    "tracks": [
        {
            "label": "motorcycle",
            "closest_m": 2.0,
            "distances": [4.8, 3.1, 2.0],
            "closest_at": 2,
            "lateral_m": 0.08,
            "ground_plane_m": 2.6,
            "frames": [3, 5],
            "at": [3, 4, 5],
            "boxes": [[0.3, 0.5, 0.4, 0.7], [0.32, 0.5, 0.42, 0.72], [0.34, 0.5, 0.45, 0.75]],
        }
    ],
}


def build_dir(tmp_path, verified: bool = True, clips=None) -> str:
    """A moments directory with a manifest and the media file it names.

    `verified` sets it on the clip, not on the manifest: that is where the build writes it and where
    the loader reads it, because one boolean over a whole file let four marginal clips block six
    clean ones.
    """
    directory = tmp_path / "moments"
    directory.mkdir()
    (directory / CLIP["media_file"]).write_bytes(b"not-a-real-mp4")
    rows = clips if clips is not None else [{**CLIP, "verified": verified}]
    manifest = {"corpus": "hanoi", "verified": verified, "clips": rows}
    (directory / "moments.json").write_text(json.dumps(manifest), encoding="utf-8")
    return str(directory)


class TestLoading:
    def test_a_missing_directory_is_empty_not_an_error(self, tmp_path):
        """No box has these clips and none is meant to."""
        assert not load_moments(str(tmp_path / "nothing-here"))

    def test_a_verified_manifest_loads(self, tmp_path):
        store = load_moments(build_dir(tmp_path))
        assert store and set(store.clips) == {"m01"}

    def test_an_unverified_clip_does_not_load(self, tmp_path):
        """The build already said "do not use them". Serving one anyway is the failure this stops —
        and it is the shape of a `--force`, which `publish_assets.py` deliberately does not have."""
        assert not load_moments(build_dir(tmp_path, verified=False))

    def test_a_clip_with_no_verified_key_is_refused_rather_than_assumed_good(self, tmp_path):
        """A manifest written before per-clip verification existed serves nothing, not everything."""
        directory = build_dir(tmp_path, clips=[{k: v for k, v in CLIP.items() if k != "verified"}])
        assert not load_moments(directory)

    def test_one_bad_clip_does_not_block_the_good_ones(self, tmp_path):
        """The reason verification moved onto the clip. The real build produced 6 clean clips and 4
        with a marginal box each; a single manifest-level flag let the 4 suppress the 6."""
        good = {**CLIP, "id": "m02", "verified": True}
        bad = {**CLIP, "id": "m11", "verified": False}
        store = load_moments(build_dir(tmp_path, clips=[good, bad]))
        assert set(store.clips) == {"m02"}


class TestPathResolution:
    def test_a_known_id_resolves_to_the_file_the_manifest_names(self, tmp_path):
        directory = build_dir(tmp_path)
        assert load_moments(directory).path_of("m01") == os.path.realpath(os.path.join(directory, CLIP["media_file"]))

    @pytest.mark.parametrize("moment_id", ["m99", "../../etc/passwd", "", "m01/../../x"])
    def test_an_id_that_is_not_in_the_manifest_resolves_to_nothing(self, tmp_path, moment_id):
        """The lookup is a whitelist: an id the build never produced cannot name a path at all."""
        assert load_moments(build_dir(tmp_path)).path_of(moment_id) is None

    def test_a_manifest_naming_a_file_outside_the_directory_is_refused(self, tmp_path):
        """The belt to the whitelist's brace. A crafted manifest still cannot escape."""
        escaping = {**CLIP, "media_file": "../../../../etc/passwd"}
        assert load_moments(build_dir(tmp_path, clips=[escaping])).path_of("m01") is None

    def test_a_manifest_row_whose_file_is_gone_resolves_to_nothing(self, tmp_path):
        directory = build_dir(tmp_path)
        os.remove(os.path.join(directory, CLIP["media_file"]))
        assert load_moments(directory).path_of("m01") is None


@pytest.mark.asyncio
class TestRoutes:
    @pytest.fixture
    def served(self, tmp_path, monkeypatch):
        """Point the process at a built moments directory for one test."""
        from src.config import get_settings

        monkeypatch.setenv("MOMENTS_DIR", build_dir(tmp_path))
        get_settings.cache_clear()
        moments_module.reset()
        yield
        get_settings.cache_clear()
        moments_module.reset()

    @pytest.fixture
    def nothing_built(self, tmp_path, monkeypatch):
        """Point the process at a directory with no build in it.

        Pointed explicitly rather than left to the default, which is how this test broke: it read
        `data/moments/` and passed only while nobody on that machine had run the build. The day the
        real one landed it started failing, having asserted a property of the developer's disk
        rather than of the code. Same shape as `conftest._no_operator_token`.
        """
        from src.config import get_settings

        monkeypatch.setenv("MOMENTS_DIR", str(tmp_path / "no-build-here"))
        get_settings.cache_clear()
        moments_module.reset()
        yield
        get_settings.cache_clear()
        moments_module.reset()

    async def test_a_service_with_no_clips_lists_none_rather_than_failing(self, client, nothing_built):
        res = await client.get("/api/v1/moments")
        assert res.status_code == 200
        assert res.json() == []

    async def test_it_lists_what_was_built_with_a_url_the_client_does_not_have_to_construct(self, client, served):
        body = (await client.get("/api/v1/moments")).json()
        assert [c["id"] for c in body] == ["m01"]
        assert body[0]["video_url"] == "/api/v1/moments/m01/video"
        assert body[0]["deep_link"] == CLIP["deep_link"]

    async def test_it_streams_the_clip_and_advertises_range(self, client, served):
        res = await client.get("/api/v1/moments/m01/video")
        assert res.status_code == 200
        assert res.headers["content-type"] == "video/mp4"
        # Seeking in a `<video>` element depends on this; `FileResponse` sets it, which is why the
        # route does not parse a byte range itself.
        assert res.headers.get("accept-ranges") == "bytes"

    async def test_a_range_request_is_served_as_a_partial(self, client, served):
        res = await client.get("/api/v1/moments/m01/video", headers={"Range": "bytes=0-3"})
        assert res.status_code == 206
        assert res.content == b"not-"

    async def test_the_detail_route_carries_the_boxes_the_list_deliberately_does_not(self, client, served):
        """The split is the point: a list of ten clips must not ship a few hundred rectangles."""
        listed = (await client.get("/api/v1/moments")).json()[0]
        assert "tracks" not in listed

        body = (await client.get("/api/v1/moments/m01")).json()
        assert body["id"] == "m01"
        assert [t["label"] for t in body["tracks"]] == ["motorcycle"]
        assert body["tracks"][0]["boxes"][0] == [0.3, 0.5, 0.4, 0.7]
        # One distance per box, so a tag can show the frame being played rather than the minimum.
        assert body["tracks"][0]["distances"] == [4.8, 3.1, 2.0]
        assert len(body["tracks"][0]["distances"]) == len(body["tracks"][0]["at"])
        # Boxes are fractions of the frame, so an overlay scales with the player.
        assert all(0.0 <= v <= 1.0 for box in body["tracks"][0]["boxes"] for v in box)
        # Published so a reader can see how much to trust the metres.
        assert body["camera_h_m"] == 1.31

    async def test_a_clip_annotated_before_the_tracks_existed_reports_none_not_nothing_came_near(
        self, client, tmp_path, monkeypatch
    ):
        """An empty overlay and an unmeasured one are different claims, and only one is honest."""
        from src.config import get_settings

        older = {k: v for k, v in CLIP.items() if k not in ("tracks", "camera_h_m")}
        monkeypatch.setenv("MOMENTS_DIR", build_dir(tmp_path, clips=[older]))
        get_settings.cache_clear()
        moments_module.reset()
        try:
            body = (await client.get("/api/v1/moments/m01")).json()
            assert body["tracks"] == []
            assert body["camera_h_m"] is None
        finally:
            get_settings.cache_clear()
            moments_module.reset()

    async def test_an_unknown_moment_detail_is_404_not_500(self, client, served):
        assert (await client.get("/api/v1/moments/../secrets")).status_code == 404
        assert (await client.get("/api/v1/moments/m99")).status_code == 404

    async def test_an_unknown_moment_is_404_not_500(self, client, served):
        assert (await client.get("/api/v1/moments/m99/video")).status_code == 404


class TestTheJoinToSearchResults:
    """`for_frame` is what lets one result card offer both the clip and the original.

    A moment is cut around one keyframe, so at most one clip can claim a frame. Everything else is
    the ordinary case: almost no frame has a clip, and the card renders without one.
    """

    def test_the_frame_a_clip_was_cut_around_finds_it(self, tmp_path):
        assert load_moments(build_dir(tmp_path)).for_frame(FRAME)["id"] == "m01"

    def test_any_other_frame_finds_nothing(self, tmp_path):
        """Ten clips against 2,211 frames, so this is the answer almost every time."""
        assert load_moments(build_dir(tmp_path)).for_frame("some_other_CAM_FRONT") is None

    def test_an_unverified_manifest_offers_no_join_either(self, tmp_path):
        """The privacy refusal has to hold on every path out of the store, not just the route."""
        assert load_moments(build_dir(tmp_path, verified=False)).for_frame(FRAME) is None

    def test_a_hit_carries_the_clip_and_the_events_inside_it(self, tmp_path, monkeypatch):
        """The card's two affordances at once: ours-and-redacted, plus the original as evidence."""
        from src.config import get_settings
        from src.services.search.service import moment_ref

        monkeypatch.setenv("MOMENTS_DIR", build_dir(tmp_path))
        get_settings.cache_clear()
        moments_module.reset()
        try:
            ref = moment_ref(moments_module.get_moments(), FRAME)
            assert ref.id == "m01"
            assert ref.video_url == "/api/v1/moments/m01/video"
            # Clip-relative, and a human's reading rather than a detection.
            assert ref.events == [[5.7, 8.7, "cut_in"]]
            # The headline number rides the hit; the boxes behind it do not.
            assert ref.closest_m == 2.0
            assert moment_ref(moments_module.get_moments(), "nope_CAM_FRONT") is None
        finally:
            get_settings.cache_clear()
            moments_module.reset()
