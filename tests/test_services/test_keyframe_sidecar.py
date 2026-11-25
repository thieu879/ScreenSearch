"""The Module 1 → Module 2 handoff: `frames.json` and the FOV gate.

Both were carried by `scripts/extract_keyframes.py`, which PR #35 removed when LMSKE replaced the
fixed-rate extractor. LMSKE is the better selector and stays; these two are not part of *selecting*
frames, and losing them breaks the stage downstream rather than this one.

**Adaptive extraction makes the sidecar mandatory rather than merely useful.** Without it,
`ingest_folder` falls back to lexical order at a fixed `--fps` and invents evenly spaced timestamps.
For a 2 Hz extractor that fallback was very nearly right. LMSKE selects on shot boundaries and
redundancy, so its output is deliberately *un*evenly spaced — the fallback would then be wrong on
every frame, and wrong silently: the corpus ingests, searches, and returns frames whose reported
position in the source video does not exist.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

import numpy as np
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_run_keyframing():
    """Import the CLI by path — `scripts/ingest/` is not a package."""
    path = os.path.join(REPO_ROOT, "scripts", "ingest", "run_keyframing.py")
    spec = importlib.util.spec_from_file_location("run_keyframing_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rk = _load_run_keyframing()

from src.services.ingest.models import ExtractedKeyframe, VideoMetadata  # noqa: E402

# Deliberately uneven, which is the whole point — 0.0, 3.7, 4.1, 19.4 is what adaptive selection
# looks like and what evenly spaced fallback timestamps would destroy.
TIMESTAMPS = [0.0, 3.7, 4.1, 19.4]


def keyframes() -> list[ExtractedKeyframe]:
    """Four frames whose spacing no fixed `--fps` could reproduce."""
    return [
        ExtractedKeyframe(
            frame_id=f"clip_f{i:05d}",
            video_id="clip",
            timestamp_s=t,
            frame_idx=i * 37,
            reason="event" if i else "heartbeat",
        )
        for i, t in enumerate(TIMESTAMPS)
    ]


def args_for(tmp_path, fov: float = 120.0, strategy: str = "lmske") -> argparse.Namespace:
    """The parsed CLI, as `write_sidecar` receives it.

    Every flag the sidecar records has to appear here. The sidecar is the Module 1 -> Module 2
    contract and it now carries *how* the selection was made, not only what it selected, so a flag
    missing from this fixture is a field silently absent from the contract.
    """
    return argparse.Namespace(
        video=str(tmp_path / "clip.mp4"),
        fov=fov,
        strategy=strategy,
        sample_fps=None,
        bottom_crop=0.0,
        quality_gate=False,
        avoid_wiper=False,
    )


def meta() -> VideoMetadata:
    return VideoMetadata(video_id="clip", fps=29.97, total_frames=600, width=1920, height=1080)


@pytest.fixture
def in_tmp_cwd(tmp_path, monkeypatch):
    """`_out_dir` is relative to the working directory, as the CLI intends."""
    monkeypatch.chdir(tmp_path)
    os.makedirs(rk._out_dir("clip", "lmske"), exist_ok=True)
    return tmp_path


class TestTheSidecar:
    def test_carries_the_decoders_timestamps_not_even_spacing(self, in_tmp_cwd):
        """The one that matters: uneven spacing must survive the round trip verbatim."""
        rk.write_sidecar(keyframes(), meta(), args_for(in_tmp_cwd))
        payload = json.loads((in_tmp_cwd / "data/extracted_keyframes/clip/frames.json").read_text())

        assert [f["timestamp_s"] for f in payload["frames"]] == TIMESTAMPS

    def test_records_the_declared_fov(self, in_tmp_cwd):
        """It cannot be recovered from the pixels, so if it is not written here it is lost (§10.5)."""
        rk.write_sidecar(keyframes(), meta(), args_for(in_tmp_cwd, fov=100.0))
        payload = json.loads((in_tmp_cwd / "data/extracted_keyframes/clip/frames.json").read_text())

        assert payload["hfov_deg"] == 100.0

    def test_names_files_that_match_the_images_written(self, in_tmp_cwd):
        """`ingest_folder` resolves `file` against the frames directory; a mismatch ingests nothing."""
        rk.write_sidecar(keyframes(), meta(), args_for(in_tmp_cwd))
        payload = json.loads((in_tmp_cwd / "data/extracted_keyframes/clip/frames.json").read_text())

        assert [f["file"] for f in payload["frames"]] == [f"{kf.frame_id}.jpg" for kf in keyframes()]

    def test_carries_the_index_back_into_the_source_video(self, in_tmp_cwd):
        """`timestamp_s` is not a substitute. On variable-frame-rate footage a timestamp reseeks to
        a different frame than the one embedded, so the index is the only stable link back."""
        rk.write_sidecar(keyframes(), meta(), args_for(in_tmp_cwd))
        payload = json.loads((in_tmp_cwd / "data/extracted_keyframes/clip/frames.json").read_text())

        assert [f["frame_idx"] for f in payload["frames"]] == [kf.frame_idx for kf in keyframes()]

    def test_records_why_each_frame_was_selected(self, in_tmp_cwd):
        """The selector knows `event` from `heartbeat` and nothing downstream can recover it. E1
        (`keyframe-storage-design.md` §4) sweeps the near-duplicate threshold over exactly this
        split, and §5.3 makes a re-extraction a new corpus — so it is written now or not at all."""
        rk.write_sidecar(keyframes(), meta(), args_for(in_tmp_cwd))
        payload = json.loads((in_tmp_cwd / "data/extracted_keyframes/clip/frames.json").read_text())

        reasons = [f["reason"] for f in payload["frames"]]
        assert reasons == [kf.reason for kf in keyframes()]
        assert set(reasons) <= {"event", "heartbeat"}

    def test_records_how_the_selection_was_made_not_only_what_it_selected(self, in_tmp_cwd):
        """Every knob that changes *which pixels* end up under a given name has to be on the record.

        §5.3 makes a re-extraction a new corpus, so two runs differing only in these flags produce
        different frames under identical filenames — indistinguishable afterwards unless the sidecar
        says so. `avoid_wiper` is the sharpest case yet: it does not merely filter the selection, it
        **moves** `frame_idx` and `timestamp_s`, so a corpus built with it on and one built with it
        off disagree about where in the footage a frame came from.
        """
        rk.write_sidecar(keyframes(), meta(), args_for(in_tmp_cwd))
        payload = json.loads((in_tmp_cwd / "data/extracted_keyframes/clip/frames.json").read_text())

        for field in ("sample_fps", "compare_bottom_crop", "quality_gate", "avoid_wiper"):
            assert field in payload, f"the sidecar stopped recording {field}"
        assert payload["avoid_wiper"] is False

    def test_records_which_extractor_produced_it(self, in_tmp_cwd):
        """Two strategies ship; a corpus that cannot say which one built it cannot be compared."""
        rk.write_sidecar(keyframes(), meta(), args_for(in_tmp_cwd, strategy="hsv_heartbeat"))
        out = in_tmp_cwd / "data/extracted_keyframes/clip_hsv_heartbeat/frames.json"

        assert json.loads(out.read_text())["extractor"] == "hsv_heartbeat"

    def test_the_filename_matches_what_ingest_folder_reads(self):
        """Both sides name this string independently — asserting each against a literal would not
        catch them drifting apart, which is the only way this breaks."""
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        from ingest_folder import SIDECAR

        assert rk.SIDECAR == SIDECAR


class TestTheFovGate:
    @pytest.mark.parametrize("fov", [60.0, 45.0, 0.0])
    def test_refuses_a_field_of_view_that_makes_the_filter_a_no_op(self, fov):
        """At or below 60 deg the ±30 deg bands leave the frame, every object becomes `front`, and
        the filter does nothing while still reporting ~96% precision. Refused, never warned."""
        with pytest.raises(SystemExit):
            rk.check_fov(fov)

    @pytest.mark.parametrize("fov", [60.1, 100.0, 140.0])
    def test_accepts_a_plausible_dashcam_field_of_view(self, fov):
        assert rk.check_fov(fov) is None

    def test_is_the_same_check_the_ingest_side_runs(self):
        """One definition, imported by both — a second copy is a second thing to forget to update."""
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import ingest_folder

        assert rk.check_fov is ingest_folder.check_fov

    def test_the_cli_requires_it(self):
        """Defaulting the FOV is how it gets declared wrong: §10.5's failure is silent, so the only
        safe default is no default."""
        with pytest.raises(SystemExit):
            rk.parse_args(["--video", "x.mp4"])


class TestTheFolderHandedToModuleTwo:
    """The output folder must contain exactly the images the sidecar names."""

    def test_a_rerun_removes_images_the_new_selection_did_not_produce(self, in_tmp_cwd):
        """`--avoid-wiper` renames frames, so a re-run leaves the old names behind as orphans.

        Before frames could move, re-extraction overwrote the same filenames and was idempotent by
        accident. Now a swapped frame lands under a new index, and the stale image stays unless it
        is cleaned — measured at 76 JPEGs for 60 keyframes on the first clip re-run. `ingest_folder`
        falls back to lexical order when it cannot read the sidecar, which is where an orphan stops
        being harmless.
        """
        first = [
            ExtractedKeyframe(
                frame_id="clip_f00010",
                video_id="clip",
                timestamp_s=0.3,
                frame_idx=10,
                reason="event",
                image_array=np.zeros((8, 8, 3), dtype=np.uint8),
            )
        ]
        rk.save_keyframe_images(first, "clip")
        out = in_tmp_cwd / "data/extracted_keyframes/clip"
        assert (out / "clip_f00010.jpg").exists()

        # The same selection, moved off a blade by three frames.
        second = [
            ExtractedKeyframe(
                frame_id="clip_f00013",
                video_id="clip",
                timestamp_s=0.43,
                frame_idx=13,
                reason="event",
                image_array=np.zeros((8, 8, 3), dtype=np.uint8),
            )
        ]
        rk.save_keyframe_images(second, "clip")

        assert (out / "clip_f00013.jpg").exists()
        assert not (out / "clip_f00010.jpg").exists(), "the superseded frame is still on disk"
        assert sorted(p.name for p in out.glob("*.jpg")) == ["clip_f00013.jpg"]

    def test_a_rerun_leaves_the_sidecars_alone(self, in_tmp_cwd):
        """Only images are swept. `rejected.json` and `swaps.json` are the run's own record."""
        rk.save_keyframe_images([], "clip")
        out = in_tmp_cwd / "data/extracted_keyframes/clip"
        (out / "rejected.json").write_text("{}", encoding="utf-8")

        rk.save_keyframe_images([], "clip")

        assert (out / "rejected.json").exists()
