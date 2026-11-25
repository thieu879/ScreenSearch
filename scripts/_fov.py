"""The declared field of view, and the one check that must run before any of it is believed.

**Why this is its own module.** Two programs need this check and they cannot import it from each
other. `ingest_folder.py` runs in the research environment (`C:/Users/Precision/ssv`), which has
CUDA, the nuScenes devkit and `cv2` but **no pydantic**; `scripts/ingest/run_keyframing.py` reaches
into `src.services.ingest`, whose models are pydantic. Importing either direction breaks one of
them. Plain stdlib here, beside `_console.py`, keeps both working.

**Why the check exists at all — M2_DESIGN §10.5.** The FOV is *declared*, never measured: footage
from Pexels or YouTube carries no lens data, and on customer footage there is no ground truth, so
there is no mAP to fit it against. It defines where "left" begins rather than estimating anything.

That makes an under-declared FOV uniquely dangerous. With `cx = W/2`, the ±30° relation bands fall
outside the frame once the horizontal FOV drops to 60° or below, every object is classified `front`,
and the metadata filter silently does nothing — while still reporting ~96% precision, because the
frames it does return are genuinely front-facing. The measurement looks healthy and the feature is
gone. That is the failure mode `report.md` §2 was written to catch.

So it is refused, not warned about, and refused at *both* ends: at extraction, where a bad value
costs one decode, and again at ingest, where it would cost the whole pipeline.
"""

from __future__ import annotations

import sys

# Below this, no left/right relation is expressible — see the module docstring and §10.5.
MIN_FOV_DEG = 60.0


def check_fov(hfov_deg: float) -> None:
    """Refuse a field of view that would make the spatial filter a silent no-op (§10.5)."""
    if hfov_deg <= MIN_FOV_DEG:
        sys.exit(
            f"--fov {hfov_deg} is at or below {MIN_FOV_DEG:.0f} deg. With cx = W/2 the +/-30 deg "
            "relation bands then fall outside the frame, every object becomes 'front', and the "
            "metadata filter silently does nothing while still reporting ~96% precision "
            "(M2_DESIGN 10.5). Declare the camera's true horizontal FOV; most dashcams are 100-140."
        )
