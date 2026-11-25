"""Moving a selected keyframe off the wiper blade, instead of deleting it.

**What was wrong.** `quality.py`'s occlusion arm cannot fire on a wiper, by arithmetic rather than
by mistuning. `OCCLUSION_FLOOR` is 0.60 — more than 60% of the scene region dark *and* locally flat
— while a blade covers 5–15% of the frame. Measured on clip01_hanoi's 59 selected frames: median
occlusion 0.099, maximum 0.317, so nothing reaches half the floor and `is_transient` never runs.
The gate rejected exactly one frame of that clip and it is solid black, not a blade. Reviewed by
eye, roughly half the clip's keyframes carry a visible wiper.

The statistic does not even *rank* blades. `clip01_hanoi_f05696` scores 0.0914 — below its own clip
median — with a blade straight across the right half, while the lowest-detail frame in the clip has
no blade at all. `quality.py`'s own docstring already says this arm is "effectively inert"; this
module is what actually addresses the wiper, and the gate is left alone.

**Why rejection was the wrong shape of answer.** Two previous attempts fitted an absolute threshold
on a photometric statistic and both had to be widened until they stopped firing, because tree
canopy, underpasses and night are dark and flat too — measured, the magnitudes overlap completely.
A third statistic fails the same way: a black-hat shape detector scored a *clean* frame highest
(0.359) and the three largest blades lowest (0.081–0.092), because black-hat suppresses structures
fatter than its kernel and a rain scene is full of thin dark ones — wires, railings, wet road.

So this module does not try to decide "is this frame usable". It asks the much weaker question
**"is there a clearer frame a few hundred milliseconds away"**, and moves the selection there. Two
frames 0.5 s apart from the same clip show the same scene, so the comparison has no scene-content
confound — which is precisely what defeated every absolute threshold.

**Why substitution makes the false positives affordable.** The test here is a per-pixel temporal
one: a blade makes a pixel much darker than that pixel's own recent median. On 20 hand-labelled
clip01 frames it separates cleanly (11 blades ≥ 0.064, 9 clean ≤ 0.049) — but on the confounder
clips it also fires on **footbridges, overpasses and tunnel interiors**, because a car passes under
a footbridge in about 0.4 s, the same timescale as a wiper sweep. `clip09_hanoi_f06656` is inside a
tunnel; `clip04_hanoi_f13576` is a pedestrian bridge overhead.

Under rejection that would repeat the exact regression `1b126b3` was written to undo — deleting the
best intersection in the corpus. Under substitution it costs a timestamp nudge of under 0.6 s: a
tunnel frame is replaced by a tunnel frame. The failure mode degrades from *losing a scene* to
*seeing it a third of a second later*.

**The one cost that is not free**, and the reason `SWAP_WINDOW_S` is small: a frame chosen because
of a distinctive overhead landmark can be nudged off it. `clip09_hanoi_f11832` frames the VINACONEX
overpass sign. Picking the *nearest* acceptable frame rather than the *clearest* one keeps that
drift as small as the window allows.

Swaps are recorded, never silent — `swaps.json` beside the sidecar, for the same reason
`rejected.json` exists: a corpus whose selection moved for unexplained reasons cannot be defended
at review, and these constants were fitted on one city's rain.
"""

from __future__ import annotations

from collections import deque

import cv2
import numpy as np

from src.services.ingest.keyframing import scene_region
from src.services.ingest.models import ExtractedKeyframe

# How much darker than its own temporal median a pixel must be to count as covered, in 8-bit
# luminance. A blade is near-black over ground that was road or sky a moment earlier; 28 is well
# clear of exposure drift and compression noise, which move a handful of levels.
DARKER_BY = 28

# How far either side to look for a clearer frame. Wiper cadence on the first-release footage is
# roughly one sweep per second, so 0.6 s reaches past a blade without reaching a different street.
# Every one of the 11 labelled clip01 blade frames had a clean neighbour inside this window.
SWAP_WINDOW_S = 0.6

# Rate the window is sampled at, matching the extractor's own `--sample-fps 15`: the selected frame
# then lands exactly on the grid, and a blade cannot hide between two samples.
SAMPLE_HZ = 15.0

# Below this the frame is clear enough to leave alone. From the labelled clip01 set: every clean
# frame scored at or under 0.049, every blade frame at or over 0.064.
ACT_ABOVE = 0.05

# And a swap must actually be an improvement, not jitter. Halving is a wide margin deliberately —
# the cost of *not* swapping is one blade frame, and the cost of swapping needlessly is scene drift.
IMPROVE_FACTOR = 0.5

# Fewer samples than this and a temporal median is not a summary of anything, so no swap is offered.
# Reached at the very start and end of a clip, where the window is clipped.
MIN_WINDOW = 5

_GRID = (192, 108)  # comparison resolution; a blade is hundreds of pixels wide at source


def _scene_grey(frame: np.ndarray, bottom_crop: float) -> np.ndarray:
    """The downscaled grey scene region this comparison runs on.

    Cropped to the scene for the same reason `quality.py` crops: the bonnet is identical in every
    frame, so it can never differ from its own temporal median and only dilutes the fraction.
    """
    grey = cv2.cvtColor(scene_region(frame, bottom_crop), cv2.COLOR_BGR2GRAY)
    return cv2.resize(grey, _GRID, interpolation=cv2.INTER_AREA).astype(np.int16)


def blade_scores(greys: list[np.ndarray]) -> list[float]:
    """Per-frame covered fraction across one window: how much of each frame went suddenly dark.

    The median over the window is the reference, not the neighbouring frame, because a sweep spans
    two consecutive samples at 15 Hz and a pairwise difference would cancel across them.
    """
    stack = np.stack(greys)
    median = np.median(stack, axis=0)
    return [float(np.mean((median - g) > DARKER_BY)) for g in stack]


def _window_of(buffer: deque[tuple[int, np.ndarray]], centre: int, span: int) -> list[tuple[int, float]]:
    """Score the buffered samples lying within `span` frames of `centre`."""
    rows = [(index, grey) for index, grey in buffer if abs(index - centre) <= span]
    if len(rows) < MIN_WINDOW:
        return []
    scores = blade_scores([grey for _, grey in rows])
    return list(zip([index for index, _ in rows], scores, strict=True))


def _choose(scores: list[tuple[int, float]], frame_idx: int, taken: set[int]) -> tuple[int, float, float] | None:
    """`(index, score before, score after)` of the frame to move to, or `None` to stay put.

    The **nearest** acceptable frame, not the clearest. Both are clear; the nearest is the one that
    has drifted least from the scene the selector actually chose, which is what keeps a distinctive
    overhead landmark in frame when the test misfires on it.
    """
    here = dict(scores).get(frame_idx)
    if here is None or here < ACT_ABOVE:
        return None
    better = [
        (index, score)
        for index, score in scores
        if score < ACT_ABOVE and score <= here * IMPROVE_FACTOR and index not in taken
    ]
    if not better:
        return None
    index, score = min(better, key=lambda row: abs(row[0] - frame_idx))
    return index, here, score


class BladeAvoider:
    """Re-picks selected keyframes that a wiper crossed, from the source footage either side.

    Needs the video: the selected keyframes are seconds apart and cannot show what the windscreen
    looked like 0.3 s earlier. With no video there is nothing to compare against and every frame is
    kept exactly as selected — the same resolution `QualityGate.is_transient` reaches, for the same
    reason.
    """

    def __init__(self, bottom_crop: float = 0.0, video_path: str | None = None) -> None:
        self.bottom_crop = bottom_crop
        self.video_path = video_path

    def window_scores(self, frame_idx: int, fps: float) -> list[tuple[int, float]]:
        """`(frame index, blade score)` for each sampled frame around `frame_idx`, including it.

        Bounded by distance from `frame_idx`, not by a frame count taken from a clamped start. The
        difference bites at the head of a clip: reading a fixed count forward from frame 0 built a
        window running to +1.2 s with nothing before the centre, so the first frames of every clip
        were judged against footage that came only *after* them. Measured on clip01, that alone
        moved one selection 0.40 s instead of 0.13 s.
        """
        if not self.video_path or fps <= 0:
            return []
        step, half = self._grid(fps)
        span = half * step
        start = max(0, frame_idx - span)
        buffer: deque[tuple[int, np.ndarray]] = deque()
        capture = cv2.VideoCapture(self.video_path)
        try:
            if not capture.isOpened():
                return []
            capture.set(cv2.CAP_PROP_POS_FRAMES, start)
            for offset in range(2 * span + 1):
                index = start + offset
                if index > frame_idx + span:
                    break
                ok, frame = capture.read()
                if not ok:
                    break
                # Phase the grid on `frame_idx` itself, so clamping `start` at 0 cannot shift the
                # sampling off the very frame being judged.
                if (index - frame_idx) % step == 0:
                    buffer.append((index, _scene_grey(frame, self.bottom_crop)))
        finally:
            capture.release()
        return _window_of(buffer, frame_idx, span)

    def _grid(self, fps: float) -> tuple[int, int]:
        """`(sampling step, half-window)` in source frames, for this clip's rate."""
        step = max(1, int(round(fps / SAMPLE_HZ)))
        return step, max(1, int(round(SWAP_WINDOW_S * fps / step)))

    def all_windows(self, wanted: set[int], fps: float) -> dict[int, list[tuple[int, float]]]:
        """Window scores for every selected frame, in **one sequential pass** over the video.

        The obvious implementation seeks to each keyframe and reads its window, and it is what this
        module did first: 24 clips projected to 6-8 hours. Seeking an H.264 stream re-decodes from
        the nearest I-frame, so a 19-frame window costs far more than 19 frames, and the extractor
        pays it once per selection. Streaming the clip once and carrying a rolling buffer costs one
        decode of the video and is ~20x faster; `grab()` skips the colour conversion on the three
        frames in four that are never sampled.
        """
        if not self.video_path or fps <= 0 or not wanted:
            return {}
        step, half = self._grid(fps)
        span, pending, out = half * step, sorted(wanted), {}
        buffer: deque[tuple[int, np.ndarray]] = deque()
        capture = cv2.VideoCapture(self.video_path)
        try:
            index = 0
            while capture.grab():
                if index % step == 0 or index in wanted:
                    ok, frame = capture.retrieve()
                    if ok:
                        buffer.append((index, _scene_grey(frame, self.bottom_crop)))
                while pending and index >= pending[0] + span:
                    out[pending[0]] = _window_of(buffer, pending[0], span)
                    pending.pop(0)
                while buffer and pending and buffer[0][0] < pending[0] - span:
                    buffer.popleft()
                index += 1
        finally:
            capture.release()
        # Selections whose window runs past the end of the clip still get scored, on what exists.
        for centre in pending:
            out[centre] = _window_of(buffer, centre, span)
        return out

    def replacement(self, frame_idx: int, fps: float, taken: set[int] | None = None) -> tuple[int, float, float] | None:
        """One frame's verdict, read by seeking. For inspecting a single selection.

        `refine` does not use this — it scores every selection in one sequential pass instead. The
        two paths must agree, and a test asserts they do on the same footage.
        """
        return _choose(self.window_scores(frame_idx, fps), frame_idx, taken or set())

    def _read(self, frame_idx: int) -> np.ndarray | None:
        """One frame at source resolution. Read singly: a window at full size is ~85 MB."""
        capture = cv2.VideoCapture(self.video_path or "")
        try:
            if not capture.isOpened():
                return None
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = capture.read()
            return frame if ok else None
        finally:
            capture.release()

    def refine(
        self, keyframes: list[ExtractedKeyframe], fps: float = 0.0
    ) -> tuple[list[ExtractedKeyframe], list[dict]]:
        """Move blade-crossed selections onto clear footage. Returns `(keyframes, swap records)`.

        `taken` is not bookkeeping for its own sake: `event` keyframes can be a fifth of a second
        apart (clip09 selects f11832 and f11840), so two of them can want the same replacement and
        collapse into one duplicated frame in the corpus.

        The result is re-sorted for the same reason. Two selections closer together than the window
        can cross when one moves back and the other does not, and the sidecar would then list a
        frame before its own predecessor. Measured over the 24-clip corpus: 9 such inversions in 5
        clips, every one of them a single 0.067 s sample step. `ingest_folder` reads this list in
        order, and a corpus whose timestamps run backwards is wrong in a way nothing downstream
        checks.
        """
        out: list[ExtractedKeyframe] = []
        swaps: list[dict] = []
        taken = {kf.frame_idx for kf in keyframes}
        windows = self.all_windows(taken.copy(), fps)
        for kf in keyframes:
            chosen = _choose(windows.get(kf.frame_idx, []), kf.frame_idx, taken)
            frame = self._read(chosen[0]) if chosen else None
            if chosen is None or frame is None:
                out.append(kf)
                continue
            index, before, after = chosen
            taken.discard(kf.frame_idx)
            taken.add(index)
            swaps.append(
                {
                    "file": f"{kf.frame_id}.jpg",
                    "from_frame_idx": kf.frame_idx,
                    "to_frame_idx": index,
                    "shift_s": round((index - kf.frame_idx) / fps, 3),
                    "selected_as": kf.reason,
                    "blade_before": round(before, 4),
                    "blade_after": round(after, 4),
                }
            )
            out.append(
                kf.model_copy(
                    update={
                        "frame_id": f"{kf.video_id}_f{index:05d}",
                        "frame_idx": index,
                        "timestamp_s": round(index / fps, 3),
                        "image_array": frame,
                    }
                )
            )
        return sorted(out, key=lambda kf: kf.frame_idx), swaps
