"""Redacted moment clips held on local disk — the private-storage half of the temporal answer.

`videos.json` points at footage this project does not own, and its `redistribution` note is the
reason: the clips are unredacted street video and publishing them would make this project the
publisher of exactly what `publish_assets.py` refuses to release. **That note is about publishing,
and it stops applying the moment the footage is yours.** An enterprise searching its own dashcam
archive can hold the pixels, so this is what the product looks like on the other side of that line.

`scripts/moments/build_moment_clips.py` writes what this reads: ten six-second cuts at 10 fps, redacted at
source resolution and then **verified against the encoded output** — the mp4 is decoded back to
frames and the face and plate detectors are re-run on it, because a claim about the frames that went
*into* an encoder is not a claim about the file that comes out. Nothing here re-derives that. It
reads `verified` and refuses to serve a manifest that does not carry it.

**Absent manifest means absent feature, silently.** No box has these clips and none is meant to:
they are a local-branch artifact for the demo, `data/` is gitignored, and the deployed service will
simply report no moments. Same posture as `videos.py`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from src.config import get_settings

MANIFEST_FILE = "moments.json"


@dataclass(frozen=True)
class MomentStore:
    """`id` -> the record `build_moment_clips.py` wrote. Empty when nothing has been built."""

    clips: dict[str, dict] = field(default_factory=dict)
    directory: str = ""

    def __bool__(self) -> bool:
        return bool(self.clips)

    def for_frame(self, frame_id: str) -> dict | None:
        """The clip built around this frame, if one was. The join `/search` needs.

        A moment is cut around one keyframe, so at most one clip can claim a frame and the index is
        a plain dict. Built on demand rather than stored, because the store is tiny — ten clips —
        and a second index that can disagree with the first is not worth having at that size.
        """
        return next((c for c in self.clips.values() if c.get("frame_id") == frame_id), None)

    def path_of(self, moment_id: str) -> str | None:
        """The mp4 on disk, or None. Resolved and re-checked against the store's own directory.

        The id comes off a URL, so this is the `/thumb` route's argument in a second place: the
        lookup is a whitelist — only ids the manifest already names can resolve — and the realpath
        check is the belt to that brace, refusing anything that leaves the directory even if a
        crafted manifest tried to name it.
        """
        record = self.clips.get(moment_id)
        if not record:
            return None
        path = os.path.realpath(os.path.join(self.directory, record["media_file"]))
        if os.path.commonpath([path, os.path.realpath(self.directory)]) != os.path.realpath(self.directory):
            return None
        return path if os.path.exists(path) else None


def load_moments(directory: str) -> MomentStore:
    """Read the manifest if one has been built. Missing is the normal case, not an error.

    **Only clips that passed their own output scan load, and the filter is per clip.** The build
    sets `verified` on each record from its own scan; a clip that still shows something on
    unredacted pixels is left out here rather than served. Honouring that in the loader rather than
    trusting the operator is the point — the refusal has to survive someone pointing a server at the
    directory anyway.

    **Per clip and not per manifest, because the alternative was measured.** One boolean over the
    whole file meant four clips with a marginal box each blocked six that were clean. A missing
    `verified` key reads as false, so a manifest written before this existed serves nothing rather
    than everything.
    """
    path = os.path.join(directory, MANIFEST_FILE)
    if not os.path.exists(path):
        return MomentStore()
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)
    clips = {c["id"]: c for c in manifest.get("clips", []) if c.get("verified") is True}
    return MomentStore(clips=clips, directory=directory)


_CACHE: MomentStore | None = None


def get_moments() -> MomentStore:
    """Process-wide store, loaded once. Cleared by tests through `reset` rather than a cache handle."""
    global _CACHE
    if _CACHE is None:
        _CACHE = load_moments(get_settings().moments_dir)
    return _CACHE


def reset() -> None:
    """Drop the cached store — for tests that write a manifest after the process started."""
    global _CACHE
    _CACHE = None
