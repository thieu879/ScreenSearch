"""The devkit-free ingest path — M2_DESIGN §10.5.

Only the pure parts are tested here: id derivation, the sidecar contract, and the FOV guard. The
stages themselves need a detector, a captioner and 400 MB of weights, and they are unchanged code
imported from `run_ingest.py` — testing them here would test torchvision.

The id test is the one that earns its place. `api/routes.py:_FRAME_ID` is a whitelist that doubles
as the thumbnail endpoint's path-traversal defence, so a corpus whose ids do not match it ingests
perfectly and then 404s on every image — at demo time, on someone else's footage.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
)

from ingest_folder import (  # noqa: E402
    MIN_FOV_DEG,
    SCENE_BUCKET_S,
    build_rows,
    by_frame_id,
    check_fov,
    frame_id_for,
    resolve_video,
    write_empty_captions,
    write_metadata,
    write_provenance,
)
from scenesearch.metadata.extract import drop_ego_boxes  # noqa: E402

from src.api.routes import _FRAME_ID  # noqa: E402


class TestFrameIds:
    def test_a_derived_id_is_one_the_api_will_serve(self):
        """The whole reason ids are derived rather than taken from filenames."""
        assert _FRAME_ID.match(frame_id_for("clip-01", "000001.jpg"))

    def test_ids_survive_filenames_the_api_would_reject(self):
        for filename in ("frame 0001.jpg", "../etc/passwd", "ẢNH.jpg", "a" * 300 + ".png"):
            assert _FRAME_ID.match(frame_id_for("clip", filename)), filename

    def test_the_same_frame_gets_the_same_id_every_run(self):
        """Ids key thumbnails and review verdicts; instability orphans both."""
        assert frame_id_for("clip-01", "000001.jpg") == frame_id_for("clip-01", "000001.jpg")

    def test_different_videos_cannot_collide_on_a_frame_number(self):
        assert frame_id_for("clip-01", "000001.jpg") != frame_id_for("clip-02", "000001.jpg")


class TestFovGuard:
    def test_a_field_of_view_that_would_silently_disable_the_filter_is_refused(self):
        """§10.5: at <= 60 deg the ±30 deg bands leave the frame and every object becomes `front`,
        while precision stays ~96%. A warning cannot be the control for an error that looks fine."""
        for hfov in (40.0, 55.0, MIN_FOV_DEG):
            with pytest.raises(SystemExit) as exit_info:
                check_fov(hfov)
            assert "M2_DESIGN 10.5" in str(exit_info.value)

    def test_a_usable_field_of_view_passes(self):
        for hfov in (64.8, 90.0, 120.0):
            check_fov(hfov)


class TestBuildRows:
    @staticmethod
    def _folder(tmp_path, names, sidecar=None):
        for name in names:
            (tmp_path / name).write_bytes(b"")
        if sidecar is not None:
            (tmp_path / "frames.json").write_text(json.dumps(sidecar), encoding="utf-8")
        return str(tmp_path)

    def test_without_a_sidecar_frames_are_lexical_and_evenly_spaced(self, tmp_path):
        rows = build_rows(self._folder(tmp_path, ["b.jpg", "a.jpg", "c.jpg"]), "clip", fps=2.0)
        assert [os.path.basename(r["image_path"]) for r in rows] == ["a.jpg", "b.jpg", "c.jpg"]
        assert [r["timestamp_s"] for r in rows] == [0.0, 0.5, 1.0]

    def test_the_sidecar_wins_because_it_knows_the_real_timestamps(self, tmp_path):
        """A non-uniform extractor would otherwise have its frames evenly respaced and misplaced."""
        sidecar = {
            "video_id": "from-sidecar",
            "frames": [{"file": "a.jpg", "timestamp_s": 0.0}, {"file": "b.jpg", "timestamp_s": 7.5}],
        }
        rows = build_rows(self._folder(tmp_path, ["a.jpg", "b.jpg"], sidecar), "ignored", fps=2.0)
        assert [r["timestamp_s"] for r in rows] == [0.0, 7.5]
        assert {r["video_id"] for r in rows} == {"from-sidecar"}

    def test_non_images_are_ignored(self, tmp_path):
        rows = build_rows(self._folder(tmp_path, ["a.jpg", "notes.txt", "b.png"]), "clip", fps=1.0)
        assert len(rows) == 2

    def test_scene_id_buckets_time_so_diversity_has_groups_on_one_clip(self, tmp_path):
        """§4 anticipated this: on continuous footage the right grouping is a time bucket, not the
        clip — one group would make §7's cap a no-op."""
        sidecar = {
            "video_id": "clip",
            "frames": [
                {"file": "a.jpg", "timestamp_s": 0.0},
                {"file": "b.jpg", "timestamp_s": SCENE_BUCKET_S - 0.1},
                {"file": "c.jpg", "timestamp_s": SCENE_BUCKET_S + 0.1},
            ],
        }
        rows = build_rows(self._folder(tmp_path, ["a.jpg", "b.jpg", "c.jpg"], sidecar), "clip", fps=1.0)
        assert rows[0]["scene_id"] == rows[1]["scene_id"]
        assert rows[2]["scene_id"] != rows[0]["scene_id"]

    def test_an_empty_folder_is_refused_rather_than_ingested(self, tmp_path):
        with pytest.raises(SystemExit):
            build_rows(self._folder(tmp_path, []), "clip", fps=1.0)


class TestSkipCaptions:
    """`--skip-captions` drops 83% of ingest wall clock and moves captioning into the query path.

    The pairing tested here is the dangerous one: blank captions and zero vectors are indistinguishable
    from a corpus whose captions were lost, and a zero vector scores 0.0, which `classify` reads as
    "nothing in this archive matches". Provenance is what makes the two cases distinguishable, so the
    flag and the blanks have to be written together or not at all.
    """

    @staticmethod
    def _rows(n=3):
        return [
            {
                "item_id": f"id{i}",
                "video_id": "clip",
                "scene_id": "clip#0000",
                "hfov_deg": 90.0,
                "bonnet_top": 1.0,
                "timestamp_s": float(i),
                "image_path": f"{i}.jpg",
            }
            for i in range(n)
        ]

    def test_deferred_provenance_marks_the_corpus_so_the_service_can_tell(self, tmp_path):
        out = tmp_path / "provenance.json"
        write_provenance(self._rows(), str(out), captions_deferred=True)
        assert json.loads(out.read_text(encoding="utf-8"))["captions"]["deferred"] is True

    def test_a_normal_ingest_is_not_marked_deferred(self, tmp_path):
        out = tmp_path / "provenance.json"
        write_provenance(self._rows(), str(out))
        assert json.loads(out.read_text(encoding="utf-8"))["captions"]["deferred"] is False

    def test_the_flag_is_the_one_corpus_load_reads(self, tmp_path):
        """Written by ingest, read by `Corpus.captions_deferred` — asserted against each other so
        renaming one side cannot quietly disarm the gate."""
        from src.services.search.artifacts import Corpus

        out = tmp_path / "provenance.json"
        write_provenance(self._rows(), str(out), captions_deferred=True)
        corpus = Corpus(
            frame_ids=[],
            vectors=None,
            caption_vectors=None,
            scene_of={},
            timestamp_of={},
            metadata_of={},
            caption_of={},
            provenance=json.loads(out.read_text(encoding="utf-8")),
        )
        assert corpus.captions_deferred

    def test_blank_captions_are_written_for_every_frame(self, tmp_path):
        """`Corpus.load` compares row counts across all three artifacts before serving any of them,
        so an omitted captions file fails the corpus rather than deferring it."""
        out = tmp_path / "captions.jsonl"
        write_empty_captions(self._rows(4), str(out))
        rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(rows) == 4
        assert all(r["caption"] == "" for r in rows)


class TestSeveralVideosInOneCorpus:
    """A second clip must *add* to the archive without contaminating the first.

    The dangerous failure is not a crash. `DetectionStore` and `CaptionRetrievalEncoder` key their
    caches by `os.path.basename`, and `extract_keyframes.py` numbers every clip from `000001.jpg`, so
    two videos sharing a workdir produce a corpus where the second clip carries the first clip's
    boxes and captions — and every log line says the ingest succeeded.
    """

    @staticmethod
    def _row(video_id, filename, hfov=90.0):
        return {
            "item_id": frame_id_for(video_id, filename),
            "video_id": video_id,
            "image_path": os.path.join("x", filename),
            "hfov_deg": hfov,
            "bonnet_top": 1.0,
            "scene_id": f"{video_id}#0000",
            "timestamp_s": 0.0,
        }

    def test_identical_filenames_in_two_videos_do_not_collide(self):
        """Both clips have a `000001.jpg`; only the derived id keeps them apart."""
        a, b = self._row("clip-a", "000001.jpg"), self._row("clip-b", "000001.jpg")
        assert a["item_id"] != b["item_id"]

    def test_a_cache_is_rekeyed_onto_ids_before_anything_merges(self):
        """`by_frame_id` is the translation step. Without it the merged dict would have one
        `000001.jpg` key and the second video would silently win."""
        rows = [self._row("clip-a", "000001.jpg")]
        assert by_frame_id(rows, {"000001.jpg": ["boxes-a"]}) == {rows[0]["item_id"]: ["boxes-a"]}

    def test_two_videos_keep_their_own_detections_after_merging(self):
        rows_a = [self._row("clip-a", "000001.jpg")]
        rows_b = [self._row("clip-b", "000001.jpg")]
        merged = {**by_frame_id(rows_a, {"000001.jpg": ["a"]}), **by_frame_id(rows_b, {"000001.jpg": ["b"]})}
        assert merged[rows_a[0]["item_id"]] == ["a"]
        assert merged[rows_b[0]["item_id"]] == ["b"]

    def test_a_missing_entry_is_empty_not_a_key_error(self):
        rows = [self._row("clip-a", "000001.jpg")]
        assert by_frame_id(rows, {}) == {rows[0]["item_id"]: []}

    def test_each_video_keeps_its_own_field_of_view(self, tmp_path):
        """Two cameras, two FOVs. One number for the corpus would describe all but one wrongly.

        **This asserted the opposite of what it asserts now, and the change is the point.** Until
        2026-08-20 it demanded that the same box under two declared FOVs produce *different*
        relations, because the band was cut in bearing and bearing is `fx`, which is `hfov`. The
        re-band cuts image offset at the outer thirds instead, so a box in the right third is on the
        right whatever lens is declared — and the declared FOV, which nobody measured, can no longer
        move a user-visible answer. What it still must do is reach the record, so the parts of it
        that remain a camera fact are checked here instead: the recorded bearing and the camera
        block.
        """
        narrow = tmp_path / "narrow.jpg"
        from PIL import Image

        Image.new("RGB", (1280, 720)).save(narrow)
        rows = [
            {**self._row("clip-a", "000001.jpg", hfov=70.0), "image_path": str(narrow)},
            {**self._row("clip-b", "000001.jpg", hfov=120.0), "image_path": str(narrow)},
        ]
        out = tmp_path / "metadata.jsonl"
        # A box in the right third of the frame, and so `front_right` under either declared FOV.
        dets = {r["item_id"]: [{"label": "car", "score": 0.9, "box": [900.0, 300.0, 1100.0, 500.0]}] for r in rows}
        write_metadata(rows, dets, str(out))
        records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert records[0]["relations"] == records[1]["relations"] == {"car": ["front_right"]}, (
            "the band is an image fact now — a declared FOV must not move it"
        )
        assert records[0]["camera"]["hfov_deg"] != records[1]["camera"]["hfov_deg"], (
            "each video must still carry its own declared FOV"
        )
        assert records[0]["instances"][0]["angle"] != records[1]["instances"][0]["angle"], (
            "bearing is still a camera fact and must still follow the declared FOV"
        )

    def test_provenance_records_a_field_of_view_per_video(self, tmp_path):
        rows = [self._row("clip-a", "000001.jpg", hfov=70.0), self._row("clip-b", "000001.jpg", hfov=120.0)]
        out = tmp_path / "provenance.json"
        write_provenance(rows, str(out))
        prov = json.loads(out.read_text(encoding="utf-8"))
        assert prov["intrinsics"]["hfov_deg"] == {"clip-a": 70.0, "clip-b": 120.0}
        assert prov["video_ids"] == ["clip-a", "clip-b"]

    def test_the_sidecar_supplies_the_fov_per_directory(self, tmp_path):
        """With several videos there is no single `--fov` to fall back on, so each sidecar carries it."""
        d = tmp_path / "clip-a"
        d.mkdir()
        (d / "frames.json").write_text(
            json.dumps({"video_id": "clip-a", "hfov_deg": 110.0, "fps": 2.0, "frames": []}), encoding="utf-8"
        )

        class Args:
            fov = None
            video_id = None
            fps = 2.0
            bonnet_top = None

        assert resolve_video(str(d), Args()) == {
            "video_id": "clip-a",
            "hfov_deg": 110.0,
            "fps": 2.0,
            "bonnet_top": 1.0,
        }

    def test_a_sidecar_without_a_bonnet_line_disables_the_ego_filter(self, tmp_path):
        """A corpus extracted before the filter existed must behave exactly as it did.

        `bonnet_top` 1.0 means "this camera sees no bodywork", which is true of nuScenes CAM_FRONT
        and of every folder ingested before `drop_ego_boxes`. Defaulting it to the first-release
        corpus's 0.75 instead would silently delete wide close-up vehicles from older corpora.
        """
        d = tmp_path / "clip-a"
        d.mkdir()
        (d / "frames.json").write_text(
            json.dumps({"video_id": "clip-a", "hfov_deg": 110.0, "fps": 2.0, "frames": []}), encoding="utf-8"
        )

        class Args:
            fov = None
            video_id = None
            fps = 2.0
            bonnet_top = None

        assert resolve_video(str(d), Args())["bonnet_top"] == 1.0

    def test_a_directory_with_no_fov_anywhere_is_refused(self, tmp_path):
        d = tmp_path / "clip-a"
        d.mkdir()

        class Args:
            fov = None
            video_id = None
            fps = 2.0
            bonnet_top = None

        with pytest.raises(SystemExit) as exit_info:
            resolve_video(str(d), Args())
        assert "10.5" in str(exit_info.value)


class TestTheEgoVehicleIsNotTraffic:
    """`drop_ego_boxes` — the camera's own bonnet must not enter the index as a car.

    Measured on the first-release corpus (`scripts/measure/probe_hanoi_frames.py`, 30 frames, 5 clips): a
    COCO detector calls the bonnet a vehicle in 23-27% of frames, and because those boxes touch a
    border, `box_angle`'s clipped-box rule files them under `front_left` / `front_right` — the two
    rarest bands. The filter removed 7 of 256 boxes on `mobilenet_v3` and 9 of 413 on `resnet50_v2`,
    every one of them bodywork, with no real vehicle lost.
    """

    SIZE = (1440, 1080)

    @staticmethod
    def _det(box, label="car"):
        return {"label": label, "score": 0.9, "box": box}

    def test_a_wide_box_along_the_bottom_edge_is_the_car_you_are_sitting_in(self):
        """The real shape, from clip03: full width, bottom-anchored, centred in the bonnet band."""
        dets = [self._det([0, 866, 1427, 1073])]
        assert drop_ego_boxes(dets, self.SIZE, 0.75) == []

    def test_a_motorbike_a_metre_ahead_survives(self):
        """Low in frame but narrow. On Hanoi footage this is most of what the corpus is for, so a
        rule that used the bonnet line alone would delete the subject of the demo."""
        dets = [self._det([592, 746, 652, 832], "motorcycle")]
        assert drop_ego_boxes(dets, self.SIZE, 0.75) == dets

    def test_a_lorry_filling_the_frame_survives(self):
        """Wide, but its box reaches well above the bonnet line — so it is something on the road."""
        dets = [self._det([40, 210, 1400, 900], "truck")]
        assert drop_ego_boxes(dets, self.SIZE, 0.75) == dets

    def test_bonnet_top_of_one_disables_the_filter(self):
        """nuScenes CAM_FRONT shows no bodywork, and neither does any corpus ingested before this
        existed. Both must be unaffected."""
        dets = [self._det([0, 866, 1427, 1073])]
        assert drop_ego_boxes(dets, self.SIZE, 1.0) == dets
