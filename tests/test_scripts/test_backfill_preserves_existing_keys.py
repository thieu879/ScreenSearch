"""`backfill_instances.py` must never drop a field it did not produce.

On 2026-08-12 it did. The migration rebuilt each record from `record_from_detections` and wrote that
record alone, so every key written by a *later* pass disappeared: `scene`, produced by
`scripts/tag_scenes.py`, vanished from all 6,858 frames (2,877 day / 3,981 night → nothing).

Nothing failed. The guard compared `objects` and `relations`, found them bit-identical, and said so
truthfully — it had never been told a third key existed. Downstream, `filters.py:satisfies` reads an
absent tag as *passes*, by the deliberate `meta.get("scene", {}).get(key, val)` default, so a
`time=night` constraint stopped excluding anything instead of excluding everything. A 58%-night
corpus went unfiltered for two days with no error, no empty result, and no log line.

Both halves are tested here because either one alone still loses the data:

- `merged` carries forward what the rebuild does not produce.
- `drifted` compares the record that will actually be **written** against what is on disk, over
  every existing key rather than a named pair.

The second test is the one that reproduces the bug: it feeds `drifted` the un-merged rebuild and
asserts it now refuses. On the original guard that call returned no drift, which is precisely how
the write got through.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
)

backfill = pytest.importorskip("backfill_instances")


def _on_disk() -> dict[str, dict]:
    """A promoted record as it exists before the migration — tagged, per §11.2."""
    return {
        "f1": {"frame_id": "f1", "objects": ["car"], "relations": {"car": ["front_left"]}, "scene": {"time": "night"}},
    }


def _rebuilt() -> dict[str, dict]:
    """What `record_from_detections` returns: the additive keys, and no `scene`."""
    return {
        "f1": {
            "frame_id": "f1",
            "objects": ["car"],
            "relations": {"car": ["front_left"]},
            "instances": [{"category": "car"}],
            "camera": {"hfov": 66.0},
        },
    }


def test_merge_keeps_the_tag_and_adds_the_new_keys() -> None:
    """The written row is the union: `scene` survives, `instances`/`camera` arrive."""
    row = backfill.merged(_on_disk()["f1"], _rebuilt()["f1"])
    assert row["scene"] == {"time": "night"}, "the scene tag was dropped by the merge"
    assert "instances" in row and "camera" in row, "the migration's own additions are missing"


def test_guard_refuses_a_rebuild_that_would_drop_the_tag() -> None:
    """The exact 08-12 write, and it must now be refused.

    `drifted` is given the un-merged rebuild — the record the old code wrote. The original guard
    returned `[]` here.
    """
    bad = backfill.drifted(_on_disk(), _rebuilt())
    assert bad, "a rebuild that drops `scene` was accepted"
    assert "scene" in bad[0], f"the refusal does not name the dropped key: {bad[0]}"


def test_guard_passes_the_merged_record() -> None:
    """The fixed path writes cleanly — otherwise the guard would block the migration forever."""
    disk = _on_disk()
    written = {fid: backfill.merged(disk[fid], _rebuilt()[fid]) for fid in disk}
    assert backfill.drifted(disk, written) == []


def test_guard_still_catches_a_moved_measurement() -> None:
    """The original protection is intact: a changed `relations` is a drift, not an addition."""
    moved = _rebuilt()
    moved["f1"]["relations"] = {"car": ["front_right"]}
    written = {"f1": backfill.merged(_on_disk()["f1"], moved["f1"])}
    bad = backfill.drifted(_on_disk(), written)
    assert bad and "relations" in bad[0], "a changed relation no longer refuses the write"
