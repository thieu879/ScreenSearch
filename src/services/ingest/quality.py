"""Rejecting keyframes the camera could not see through — rain on the glass, and the wiper.

**Read this first: the wiper is handled in `reselect.py`, not here.** Everything below about blades
is the record of an approach that did not work, kept because it is the reason the other one exists.
The occlusion arm was widened until it could no longer fire on a wiper at all (see `OCCLUSION_FLOOR`
and the measurement further down), and what survives in this module is a blackout detector and a
sharpness floor. `BladeAvoider` addresses wipers by *moving* the selection a few hundred
milliseconds rather than deleting it, which is what makes its false positives — footbridges,
tunnels, the same confounders named below — affordable instead of fatal.

**Why there was nothing here before.** The selector has exactly two outcomes, `event` and
`heartbeat`, and neither can refuse a frame; the only thing that removes one is stage 3, which
removes it for being too *similar*. So an unusable frame has never had a way out of the corpus. That
was survivable on nuScenes, which is dry, and is not on footage shot through a wet windscreen.

**The two failure modes are opposites, which is why one test does not cover both.**

*The wiper* is a large, fast, high-contrast change — precisely what a Bhattacharyya distance over
`hist_diff_threshold` fires on. Wiper frames are therefore selected *preferentially*, and
`_eliminate_lmske_redundancy` keeps `filtered[0]` unconditionally, so the first one always survives.
Measured on clip01 at t=134s: a blade across the view scores `occlusion` 0.310 against a clip median
of 0.113, while its `detail` is 95 against a median of 126 — the sharp parts of the frame stay
sharp, so **no sharpness test detects a wiper.**

*Droplet accumulation* is gradual, so it never trips `event` at all. Those frames arrive on the 5 s
heartbeat, and `reason == "heartbeat"` skips the redundancy check entirely, so they are admitted
with nothing looked at. They are the opposite signal: `detail` collapses, `occlusion` does not move.

**Why the thresholds are relative to the clip and not absolute.** This was measured the wrong way
round first, and the wrong way round is worth recording because it is the tempting one. An absolute
sharpness floor fitted to catch clip01's streaming-windscreen frames (`detail` 16-24) also rejects
**every frame of clip12**, whose median is 29 — because clip12 is a hazy overcast clip end to end,
not an occluded one. And it rejects a sunny, pin-sharp clip03 frame scoring 239, because half of
that frame is featureless sky. A global sharpness statistic measures *scene contrast*, which varies
by clip, far more strongly than it measures *whether the glass is clear*, which is what we want.

Occlusion by water or by a blade is a **transient event within a clip**; haze, dusk and overcast are
properties of a whole clip. So the test asks whether a frame is much worse than its own clip
normally is. That also fixes night footage for free: clip11 has a median `occlusion` of 0.524 — half
the frame is legitimately dark and flat — and an absolute cut would delete the entire clip, while a
relative one leaves it alone.

**And a per-clip median still was not enough for occlusion, which is the expensive lesson here.**
The first version of this gate rejected on `occlusion > max(0.28, 2 x clip median)` and it deleted
**15 frames of clip04 and 28 of clip09** — a busy intersection full of motorbikes with readable
plates, and the mouth of an underpass. Both are dark and locally flat over a large area, and neither
has anything to do with the windscreen. The magnitudes do not separate at all: genuine wipers on
clip01 score 0.29-0.32, clip04's tree canopy 0.29-0.41, clip09's underpass 0.42. **No threshold on
this statistic can tell them apart.**

What separates them is time. A blade is a spike with clear footage on *both* sides; canopy, tunnels
and shadow persist for seconds. Hence `is_transient`, which compares against the source video either
side, and takes the **worst** neighbour so that entering a tunnel — clear on one side, dark on the
other — reads as the scene transition it is.

Even that is not free of confusion: a *short* underpass is bright again a second later and looks
transient. So the occlusion test was narrowed to the unambiguous cases only — `OCCLUSION_FLOOR` 0.60
means "more than 60% of the visible scene is dark and featureless", which is the brief's "mostly
covered, hard to see" rather than "a bit gloomy".

**What that narrowing actually did, once somebody looked at the output.** Over the full 24-clip run
it fired **once in 2,214 frames**, and that frame is solid black rather than a wiper. It also missed
a plainly visible blade across the top third of clip24 at t=66.5s. Treat this arm as **effectively
inert**: it is retained because it costs nothing and would still catch a total blackout, not because
it removes wipers. It does not.

The lesson generalises past the constant that was tuned. Both arms were fitted by re-scoring the
frames they *rejected* and checking the magnitudes moved the right way, and both passed that check
while still being wrong — because the thing being predicted ("can a person see through this?") is
not a function of either statistic. The 33 rejections were only understood after being written back
out as JPEGs and opened. **Re-score to tune a constant; open the images to decide whether the test
works at all.** `scripts/review_rejected_frames.py` exists so the second step is cheap.

`detail` also catches blown-out frames — the tunnel-exit frames on clip09 where auto-exposure
saturates and the scene is unreadable. Not what it was built for, correct anyway, and after the
retune to 0.05 it is most of what this arm still does.

**Why this runs after selection, not during it.** The gate reads a few hundred selected frames
rather than the 684,000 the first-release corpus decodes, so its cost is noise. `is_transient` seeks
the source video, but only for the handful of frames that clear the floor.
"""

from __future__ import annotations

import cv2
import numpy as np

from src.services.ingest.keyframing import scene_region
from src.services.ingest.models import ExtractedKeyframe

# A frame is rejected below this share of its own clip's median detail.
#
# 0.05, not the 0.25 first fitted, and the correction came from *looking at the frames* rather than
# from re-reading the scores. At 0.25 this arm deleted 33 frames of the first-release corpus, and
# review of them found roughly four in five were good: two lit tunnel interiors on clip09, the West
# Lake pagoda on clip16, a night street on clip23. Variance of the Laplacian measures how much
# *texture a scene contains*, and a concrete tunnel bore is a low-texture scene that is perfectly
# legible — the same confusion `occlusion` makes, one statistic along.
#
# The ratios do not separate the two classes at any cut. Ranked over all 33, the genuine rejects sit
# at 0.000 (a black frame), 0.033/0.036 (tunnel-exit blowout), 0.186/0.192 (sun flare) and 0.243 (a
# real wiper) — while good frames sit at 0.052-0.075, *below* the flare, and again at 0.160-0.248,
# around and above it. 0.05 is the one defensible line: below it are only frames with essentially no
# image left, and every frame it drops was confirmed unusable by eye.
#
# The cost is explicit: the sun-flare pair and the one real wiper now stay in the corpus. Three
# unusable frames in ~2,200 is cosmetic; two tunnels and a landmark are not.
DETAIL_RATIO = 0.05

# A frame only becomes a *candidate* for occlusion rejection above whichever is larger: this multiple
# of the clip's median, or the floor. Neither is sufficient on its own -- see `is_transient`.
#
# The floor is 0.60, not the 0.28 first tried: at 0.28 this rejected a busy intersection and an
# underpass mouth, because tree canopy and tunnels are dark and flat over large areas too. 0.60 is
# "more than 60% of the visible scene is dark and featureless", which is the brief's "mostly
# covered" rather than "somewhat gloomy".
OCCLUSION_RATIO = 2.0
OCCLUSION_FLOOR = 0.60

# A candidate is only rejected if its occlusion is this multiple of the worst of its neighbours.
# Measured: a wiper scores 2.2-7.4x, an underpass 0.9-1.2x, tree canopy 0.9-1.0x. Set at 3.0 rather
# than in the gap, because a *short* underpass is bright again a second later and reads as transient
# at 1.8 -- so the margin buys the tunnel frames back at the cost of the weaker wiper frames.
TRANSIENT_RATIO = 3.0

# Where to look for "either side", in seconds. Two spacings rather than one because wiper cadence
# varies: a single offset can land on the return sweep and make a blade look persistent.
NEIGHBOUR_OFFSETS_S = (0.5, 1.0)

# Below this many keyframes a median is not a summary of anything, so the gate stands down rather
# than fitting itself to noise.
MIN_SAMPLE = 10

_DARK = 60  # 8-bit luminance below which a pixel is "dark"
_FLAT = 12.0  # local standard deviation below which its neighbourhood is "flat"


def detail_score(frame: np.ndarray, bottom_crop: float = 0.0) -> float:
    """Variance of the Laplacian over the scene region — how much edge detail survives.

    Measured on the scene region rather than the whole frame: the bonnet is a smooth glossy
    surface, so including it drags the variance down by a constant that has nothing to do with
    whether the road ahead is visible.
    """
    grey = cv2.cvtColor(scene_region(frame, bottom_crop), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def occlusion_score(frame: np.ndarray, bottom_crop: float = 0.0) -> float:
    """Fraction of the scene region that is both dark and locally flat — i.e. the wiper blade.

    The conjunction is the point. Darkness alone condemns every night frame; flatness alone
    condemns an overcast sky. A blade sweeping the glass is reliably both.
    """
    grey = cv2.cvtColor(scene_region(frame, bottom_crop), cv2.COLOR_BGR2GRAY)
    small = cv2.resize(grey, (160, 120), interpolation=cv2.INTER_AREA).astype("float32")
    mean = cv2.blur(small, (9, 9))
    local_sd = np.sqrt(np.maximum(cv2.blur(small * small, (9, 9)) - mean * mean, 0.0))
    return float(np.mean((small < _DARK) & (local_sd < _FLAT)))


def assess(frame: np.ndarray, bottom_crop: float = 0.0) -> dict[str, float]:
    """Both scores for one frame, as the sidecar records them."""
    return {
        "detail": round(detail_score(frame, bottom_crop), 2),
        "occlusion": round(occlusion_score(frame, bottom_crop), 4),
    }


class QualityGate:
    """Splits one clip's selected keyframes into keepers and rejects, and says why for each reject.

    Scoped to a clip because its cut points are derived from that clip's own median — see the module
    docstring. Pointing it at two clips at once would let a hazy clip raise the bar for a clear one.

    Rejects are returned, never dropped silently. The thresholds are fitted on one city's footage,
    so the next corpus is exactly when somebody needs to see what was thrown away.
    """

    def __init__(self, bottom_crop: float = 0.0, video_path: str | None = None):
        self.bottom_crop = bottom_crop
        self.video_path = video_path

    def cutoffs(self, scores: list[dict[str, float]]) -> tuple[float, float]:
        """`(min_detail, max_occlusion)` for this clip, from its own distribution."""
        detail = float(np.median([s["detail"] for s in scores]))
        occlusion = float(np.median([s["occlusion"] for s in scores]))
        return detail * DETAIL_RATIO, max(OCCLUSION_FLOOR, occlusion * OCCLUSION_RATIO)

    def neighbour_occlusion(self, frame_idx: int, fps: float) -> float | None:
        """Worst occlusion in the source footage either side of this frame.

        The **worst**, not the mean or the nearest. A wiper is a spike with clear footage on *both*
        sides, so taking the max is what distinguishes it from entering a tunnel — where one side is
        clear and the other is not, and the frame is a legitimate scene transition worth keeping.
        """
        if not self.video_path or fps <= 0:
            return None
        cap = cv2.VideoCapture(self.video_path)
        try:
            if not cap.isOpened():
                return None
            worst = 0.0
            seen = False
            for offset_s in NEIGHBOUR_OFFSETS_S:
                for direction in (-1, 1):
                    idx = frame_idx + direction * int(round(offset_s * fps))
                    if idx < 0:
                        continue
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        continue
                    worst = max(worst, occlusion_score(frame, self.bottom_crop))
                    seen = True
            return worst if seen else None
        finally:
            cap.release()

    def is_transient(self, kf: ExtractedKeyframe, occlusion: float, fps: float) -> bool:
        """Is this occlusion a passing blade, or is it what the street actually looks like?

        Without a source video there is nothing to compare against, and the honest answer is "do not
        know" — which resolves to *keep*. Deleting a frame on a test that could not be run is the
        expensive direction: the frames this caught wrongly were a busy intersection and an underpass
        mouth, both of them exactly what the archive is for.
        """
        neighbour = self.neighbour_occlusion(kf.frame_idx, fps)
        if neighbour is None:
            return False
        return occlusion >= TRANSIENT_RATIO * neighbour

    def apply(self, keyframes: list[ExtractedKeyframe], fps: float = 0.0) -> tuple[list[ExtractedKeyframe], list[dict]]:
        """Partition one clip's selected keyframes. Returns `(kept, rejected_records)`."""
        scored = [(kf, assess(kf.image_array, self.bottom_crop)) for kf in keyframes if kf.image_array is not None]
        if len(scored) < MIN_SAMPLE:
            return keyframes, []

        min_detail, max_occlusion = self.cutoffs([s for _, s in scored])
        kept: list[ExtractedKeyframe] = []
        rejected: list[dict] = []
        for kf, scores in scored:
            reason = None
            if scores["occlusion"] > max_occlusion and self.is_transient(kf, scores["occlusion"], fps):
                reason = "wiper_or_occluded"
            elif scores["detail"] < min_detail:
                reason = "no_detail"
            if reason is None:
                kept.append(kf)
            else:
                rejected.append(
                    {
                        "file": f"{kf.frame_id}.jpg",
                        "timestamp_s": kf.timestamp_s,
                        "frame_idx": kf.frame_idx,
                        "selected_as": kf.reason,
                        "rejected_for": reason,
                        "min_detail": round(min_detail, 2),
                        "max_occlusion": round(max_occlusion, 4),
                        **scores,
                    }
                )
        return kept, rejected
