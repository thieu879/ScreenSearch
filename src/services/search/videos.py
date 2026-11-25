"""The join from a result back to the footage it came from — a pointer, never the pixels.

`frames.jsonl` already knows almost everything a result needs to name its own source: `video_id`,
`scene_id` and `timestamp_s`, so any hit resolves to *"clip01_hanoi at 274.5 s"*. What no artifact
records is what `clip01_hanoi` **is**. `scripts/build_video_manifest.py` writes that join into
`videos.json` — id, URL, uploader, licence, `sha256` — and until now nothing in `src/` read it.

**This is a licence obligation before it is a feature.** All 24 Hanoi clips are Creative Commons
**Attribution**, which requires crediting the author. A result that links to the source without
naming the uploader and the licence is a worse answer than one that links to nothing, so
`SourceClip` carries the credit alongside the URL rather than leaving it to whoever renders it.

**A URL and a timestamp, never a re-hosted frame of video.** The source clips are unredacted street
video — faces and plates intact — and the whole privacy gate exists because frames are redacted
before publication. `publish_assets.py` refuses an uncleared thumbnail directory and has no
`--force`; a video path that shipped pixels would be that `--force` by another route. A pointer is
also the better answer: public, verifiable by anyone, and free to store.

**Absent manifest means absent feature, silently and by design.** The served nuScenes corpus has no
`videos.json` and can never have one — the source blobs were pruned after extraction — so
`get_manifest` returns an empty manifest there and every caller degrades to what it did before. That
is what keeps this change local to Hanoi.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache

from src.config import get_settings

MANIFEST_FILE = "videos.json"


@dataclass(frozen=True)
class VideoManifest:
    """`video_id` -> the yt-dlp record for the clip it came from. Empty when the corpus has none."""

    clips: dict[str, dict] = field(default_factory=dict)

    def __bool__(self) -> bool:
        """Truthy only when there is footage to point at, so callers can branch on the manifest."""
        return bool(self.clips)

    def deep_link(self, video_id: str, timestamp_s: float) -> str | None:
        """`{webpage_url}&t={timestamp_s:.0f}`, or None when this corpus cannot name its source.

        The separator is chosen rather than hardcoded: `videos.json` declares the template with `&`
        because every clip in it is a YouTube watch URL, which always carries `?v=`. A manifest built
        from a source whose URL has no query string would silently produce `…mp4&t=257`, a link that
        looks right and seeks nowhere.
        """
        clip = self.clips.get(video_id)
        url = (clip or {}).get("webpage_url")
        if not url or timestamp_s < 0:
            return None
        return f"{url}{'&' if '?' in url else '?'}t={timestamp_s:.0f}"

    def credit(self, video_id: str) -> dict:
        """Title, uploader and licence for one clip — the attribution CC BY requires, or `{}`."""
        clip = self.clips.get(video_id) or {}
        return {k: clip[k] for k in ("title", "uploader", "license") if clip.get(k)}


def load_manifest(artifacts_dir: str) -> VideoManifest:
    """Read `videos.json` if the corpus has one. A missing file is the normal case, not an error.

    Unlike `_read_jsonl` in `artifacts.py` this does **not** fail loudly on absence: a corpus without
    source footage is a complete corpus, and refusing to start over a missing pointer file would
    take the served product down for a feature it cannot use.
    """
    path = os.path.join(artifacts_dir, MANIFEST_FILE)
    if not os.path.exists(path):
        return VideoManifest()
    with open(path, encoding="utf-8") as f:
        return VideoManifest(clips=json.load(f).get("clips") or {})


@lru_cache(maxsize=1)
def get_manifest() -> VideoManifest:
    """Process-wide manifest for the served corpus, loaded once beside it."""
    return load_manifest(get_settings().artifacts_dir)
