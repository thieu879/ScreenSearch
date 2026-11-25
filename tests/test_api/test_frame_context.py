"""`/frames/{id}/context` — the keyframe strip behind a hit.

These use the real corpus rather than a fixture, because the property under test IS the corpus's
temporal layout: that scene neighbours exist at ~2 Hz and that the window stops at a scene boundary.
A synthetic corpus would let the endpoint pass while the served one has nothing to preview.
"""

from __future__ import annotations

import pytest

from src.services.search.context import MAX_WINDOW_S, preceding_frames
from src.services.search.density import MIN_STRIP_FRAMES, corpus_density


@pytest.mark.asyncio
class TestFrameContext:
    async def test_returns_the_anchor_and_its_lead_in_in_time_order(self, client, corpus):
        """The strip ends on the frame that was asked about, and runs forwards to it."""
        frame_id = _frame_with_history(corpus)
        res = await client.get(f"/api/v1/frames/{frame_id}/context?before=3")
        assert res.status_code == 200
        body = res.json()

        assert body["frame_id"] == frame_id
        assert body["frames"][-1]["frame_id"] == frame_id, "the anchor must be last"
        assert body["frames"][-1]["offset_s"] == 0.0
        offsets = [f["offset_s"] for f in body["frames"]]
        assert offsets == sorted(offsets), "frames must be in time order"
        assert all(o <= 0 for o in offsets), "only preceding frames"
        assert len(body["frames"]) > 1, "a mid-scene frame has history"

    async def test_never_crosses_a_scene_boundary(self, client, corpus):
        """Two scenes are unrelated moments; splicing them would fake continuous footage."""
        frame_id = _frame_with_history(corpus)
        res = await client.get(f"/api/v1/frames/{frame_id}/context?before={MAX_WINDOW_S}")
        scene = corpus.scene_of[frame_id]
        assert all(corpus.scene_of[f["frame_id"]] == scene for f in res.json()["frames"])

    async def test_a_scene_opener_is_marked_incomplete_rather_than_empty(self, client, corpus):
        """2.5% of frames have no predecessor. Return the anchor and say the window is short."""
        frame_id = _scene_opener(corpus)
        body = (await client.get(f"/api/v1/frames/{frame_id}/context?before=3")).json()
        assert body["frames"] == [
            {
                "frame_id": frame_id,
                "timestamp_s": corpus.timestamp_of[frame_id],
                "offset_s": 0.0,
                "thumb_url": f"/api/v1/frames/{frame_id}/thumb",
            }
        ]
        assert body["complete"] is False

    async def test_an_unknown_or_malformed_id_is_404_not_500(self, client):
        """Same posture as the thumb route: an id the corpus cannot hold is simply not found."""
        assert (await client.get("/api/v1/frames/../../etc/passwd/context")).status_code in (307, 404)
        assert (await client.get(f"/api/v1/frames/{'0' * 32}_CAM_FRONT/context")).status_code == 404

    async def test_the_window_is_bounded(self, client, corpus):
        """An unbounded window would let one request return a whole scene."""
        frame_id = _frame_with_history(corpus)
        assert (await client.get(f"/api/v1/frames/{frame_id}/context?before=999")).status_code == 422
        assert (await client.get(f"/api/v1/frames/{frame_id}/context?before=0")).status_code == 422

    async def test_every_returned_frame_is_one_the_corpus_already_serves(self, client, corpus):
        """The privacy argument in one assertion: this endpoint publishes nothing new."""
        frame_id = _frame_with_history(corpus)
        body = (await client.get(f"/api/v1/frames/{frame_id}/context?before=3")).json()
        assert all(f["frame_id"] in corpus.scene_of for f in body["frames"])


@pytest.mark.asyncio
class TestItSaysWhenItCouldNotBuildAStrip:
    """The guard added 2026-08-27, and the served corpus is the wrong place to see it work.

    On nuScenes almost every request is a real strip — that is what `mode: "strip"` asserts here.
    The case worth catching is the other one: at the staged Hanoi corpus's 5.00 s spacing a 3 s
    window returns the anchor alone, and the response used to be indistinguishable from a scene
    opener on a dense corpus. `mode` is computed from what the window returned rather than from a
    corpus-wide label, so a scene opener reports `sparse` on nuScenes too — which is correct and is
    asserted below, because it is the property that makes the field right on a mixed corpus.
    """

    async def test_a_real_strip_says_so_and_reports_the_spacing_behind_it(self, client, corpus):
        body = (await client.get(f"/api/v1/frames/{_frame_with_history(corpus)}/context?before=3")).json()
        assert body["mode"] == "strip"
        assert len(body["frames"]) >= MIN_STRIP_FRAMES
        assert body["median_gap_s"] == pytest.approx(corpus_density(corpus).median_gap_s, abs=1e-3)

    async def test_a_window_that_returned_only_the_anchor_is_not_called_a_strip(self, client, corpus):
        """One frame is the result already on screen. Calling that a moment is the whole defect."""
        body = (await client.get(f"/api/v1/frames/{_scene_opener(corpus)}/context?before=3")).json()
        assert len(body["frames"]) == 1
        assert body["mode"] == "sparse"

    async def test_complete_and_mode_are_different_claims(self, client, corpus):
        """`complete: false` says this scene ran out of history; `sparse` says the corpus never had
        the resolution. A dense corpus produces the first without the second, which is why one field
        could not carry both — on Hanoi the old response was `complete: false` with one frame, and
        read as a boundary case rather than as "this corpus cannot do strips"."""
        frame_id = _frame_with_history(corpus)
        body = (await client.get(f"/api/v1/frames/{frame_id}/context?before={MAX_WINDOW_S}")).json()
        assert body["mode"] == "strip"
        assert body["complete"] is False, "a ~20 s scene cannot supply a 10 s lead-in everywhere"

    async def test_the_served_corpus_offers_no_source_clip_and_says_so(self, client, corpus):
        """nuScenes pruned its source blobs after extraction. Null, not a fabricated URL."""
        body = (await client.get(f"/api/v1/frames/{_frame_with_history(corpus)}/context?before=3")).json()
        assert body["source"] is None

    async def test_status_reports_the_density_it_derived(self, client, corpus):
        """Derived from the loaded frames, so unlike the band it cannot disagree with the corpus."""
        body = (await client.get("/api/v1/status")).json()
        assert body["temporal_density"]["is_dense"] is True
        assert body["temporal_density"]["median_gap_s"] == pytest.approx(0.5, abs=0.05)
        assert body["source_clips"] == 0


def test_preceding_frames_is_empty_for_an_unknown_id(corpus):
    """The service says "nothing", and the route is what turns that into a 404."""
    assert preceding_frames(corpus, "not-a-frame", 3.0) == []


def _frame_with_history(corpus) -> str:
    """A frame at least 3 s into its scene, so it has a full lead-in."""
    for frame_id, t in corpus.timestamp_of.items():
        if t >= 3.0:
            return frame_id
    raise AssertionError("no frame 3s into a scene")


def _scene_opener(corpus) -> str:
    """The first frame of some scene — nothing precedes it."""
    earliest: dict[str, tuple[float, str]] = {}
    for frame_id, t in corpus.timestamp_of.items():
        scene = corpus.scene_of[frame_id]
        if scene not in earliest or t < earliest[scene][0]:
            earliest[scene] = (t, frame_id)
    return next(iter(earliest.values()))[1]
