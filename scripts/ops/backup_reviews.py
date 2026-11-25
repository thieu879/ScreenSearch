"""Snapshot the review database, which is the only state on a deployed box that cannot be rebuilt.

The code comes from git, the index and thumbnails from the Hub, the weights from the image. Human
verdicts exist only where they were typed, and `docs/deploy.md` has said so since the volume was
added — while providing nothing that actually copies them anywhere.

**Not `cp`, and not `docker compose cp`.** Those read the file while the service may be writing it,
and sqlite's on-disk format is only consistent between transactions: a copy taken mid-write can be
a database that opens fine and is missing its last rows, or one that will not open at all. The
online backup API takes a read lock per step and produces a snapshot that is consistent by
construction, from a *live* database, with no need to stop the container.

The snapshot is then opened and counted before the old ones are pruned, so a backup that silently
produced an unreadable file cannot evict the good copies that came before it.

Usage on the box, from the repository root:

    docker compose -f deploy/docker-compose.prod.yml exec -T api \\
        python scripts/ops/backup_reviews.py --out-dir data/backups

`deploy/scenesearch-backup.timer` runs exactly that, daily. See `docs/deploy.md`.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python < 3.11
    UTC = timezone.utc  # noqa: UP017

# Sorting these lexicographically has to equal sorting them by age, because that is how retention
# picks what to delete. UTC and a fixed-width, zero-padded stamp are what make that true; a local
# timestamp would also reorder itself twice a year.
_STAMP = "%Y%m%dT%H%M%SZ"
PREFIX = "reviews-"
SUFFIX = ".db"


def _snapshot(source: str, target: str) -> None:
    """Copy a live database to `target` using sqlite's online backup API."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _verify(path: str) -> int:
    """Return the row count, having first checked the snapshot is a readable database.

    `integrity_check` rather than a bare `SELECT COUNT(*)`: a truncated file can still answer a
    query against a page that happens to be intact, and the whole point of verifying here is to
    refuse to prune good backups in favour of a bad one.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        status = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if status != "ok":
            raise sqlite3.DatabaseError(f"integrity_check returned {status!r}")
        return conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    finally:
        conn.close()


def _unused_path(out_dir: str, stamp: str) -> str:
    """A snapshot path for `stamp` that no existing snapshot occupies.

    The stamp is second-resolution, so a manual run in the same second as the timer's would
    otherwise write straight over the timer's file. That is one destroyed backup at exactly the
    moment someone is nervous enough about the data to be taking one by hand.

    The separator is `_`, and that is not cosmetic. Retention deletes the lexicographically
    smallest names, so the suffix must sort *after* the bare `.db` of the same second. `-` (0x2D)
    sorts before `.` (0x2E) and inverted the order within a second: a first run followed by three
    more left the oldest snapshot on disk and pruned the three newer ones. `_` (0x5F) sorts after
    `.`, which restores "lexicographic order equals age" across both cases.
    """
    for n in range(100):
        path = os.path.join(out_dir, f"{PREFIX}{stamp}{'' if n == 0 else f'_{n:02d}'}{SUFFIX}")
        if not os.path.exists(path):
            return path
    raise OSError(f"100 snapshots already exist for {stamp} — is something looping?")


def _prune(out_dir: str, keep: int) -> list[str]:
    """Delete all but the newest `keep` snapshots. Returns what was removed."""
    existing = sorted(name for name in os.listdir(out_dir) if name.startswith(PREFIX) and name.endswith(SUFFIX))
    stale = existing[: max(0, len(existing) - keep)]
    for name in stale:
        os.remove(os.path.join(out_dir, name))
    return stale


def backup(db: str, out_dir: str, keep: int = 14) -> dict:
    """Write one verified snapshot of `db` into `out_dir`, then prune to `keep` of them."""
    if not os.path.exists(db):
        # A box that has taken no verdicts yet has no database, because ReviewStore creates it
        # lazily. That is not an error worth waking anyone for — but it must not be reported as a
        # successful backup either, or the first thing anyone learns about a misconfigured path is
        # that there is nothing to restore.
        return {"ok": False, "reason": "no database at that path", "db": db}

    os.makedirs(out_dir, exist_ok=True)
    target = _unused_path(out_dir, datetime.now(UTC).strftime(_STAMP))
    _snapshot(db, target)
    rows = _verify(target)
    return {
        "ok": True,
        "db": db,
        "backup": target,
        "rows": rows,
        "bytes": os.path.getsize(target),
        "pruned": _prune(out_dir, keep),
    }


def main() -> None:  # pragma: no cover - CLI wrapper
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=os.environ.get("REVIEW_DB", "data/reviews.db"),
        help="source database; defaults to REVIEW_DB so it matches the running service",
    )
    parser.add_argument("--out-dir", default="data/backups")
    parser.add_argument(
        "--keep",
        type=int,
        default=14,
        help="snapshots to retain (default 14 — two weeks of daily runs, a few hundred KB)",
    )
    args = parser.parse_args()
    try:
        result = backup(args.db, args.out_dir, args.keep)
    except (OSError, sqlite3.Error) as exc:
        sys.exit(f"review backup FAILED: {exc}")
    print(json.dumps(result, indent=2))
    # A missing database exits non-zero so the systemd timer records a failure rather than a run
    # that did nothing. Nobody checks a log that always says the same thing.
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
