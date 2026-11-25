"""A signed-in engineer's recent searches — the query side of "your work follows your account".

**Why this exists at all.** The history used to be five rows in `localStorage`, which is a browser
profile rather than a person: it was invisible the moment an engineer opened the product on a second
machine, and shared by every account that signed in on one laptop. That is the same defect as the
reviewer id (`services/reviews.py:reviewer_identity`), in the half of the product that never reached
the server, and it is the half a login cannot fix on its own — an account gate over per-browser
state only makes the sharing harder to notice.

**It is a convenience list, not a record**, and every decision here follows from that:

- **Bounded, not archival.** `HISTORY_LIMIT` rows per user, trimmed on write, so the table cannot
  grow without limit and nobody has to decide later how much of it to keep. A search worth keeping
  is a review, and reviews have their own store.
- **One row per distinct query.** Re-running a search moves it to the top instead of adding a
  duplicate — the list answers "what have I been working on", and ten copies of the same query
  answers it worse. Case-insensitive, because `A Bus At Night` and `a bus at night` are the same
  search to the person who typed them.
- **`results_count` is stored with the query** because it is what makes a repeat worth running or
  not. A row saying a query returned nothing is more useful than the query alone.

Writes are best-effort at the call site: a history row that fails to save must never fail the search
it describes, so `api/history.py` records it on a separate request the frontend does not wait for.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.db.models import SearchHistoryEntry
from src.models.schemas import HistoryWrite

# Five was the `localStorage` cap, and it was arbitrary — small enough that the history page's own
# pagination never had anything to paginate. Fifty is still a convenience list rather than an
# archive, and it is bounded per user, so the table's worst case is accounts × 50 short rows.
HISTORY_LIMIT = 50


def recent(db: Session, user_id, limit: int = HISTORY_LIMIT) -> list[SearchHistoryEntry]:
    """This user's searches, newest first. Scoped by `user_id` at the query, never filtered after."""
    stmt = (
        select(SearchHistoryEntry)
        .where(SearchHistoryEntry.user_id == user_id)
        .order_by(SearchHistoryEntry.created_at.desc(), SearchHistoryEntry.entry_id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def record(db: Session, user_id, entry: HistoryWrite) -> SearchHistoryEntry:
    """Add one search, replacing any earlier row for the same keyword and trimming to the cap.

    Replace rather than update-in-place: the row carries a `results_count` that may have changed
    since last time, and a fresh row gets a fresh `created_at`, which is what moves it to the top.
    """
    db.execute(
        delete(SearchHistoryEntry).where(
            SearchHistoryEntry.user_id == user_id,
            func.lower(SearchHistoryEntry.keyword) == entry.keyword.lower(),
        )
    )
    # Trim *before* the insert, leaving one slot free, so the row about to be written can never be
    # the row the trim removes. Trimming afterwards makes that a promise about timestamp resolution
    # instead of a property of the code, and the failure mode when it does not hold is a 500 on the
    # search that just succeeded.
    _trim(db, user_id, keep=HISTORY_LIMIT - 1)
    row = SearchHistoryEntry(
        user_id=user_id,
        keyword=entry.keyword,
        filters=entry.filters or [],
        results_count=entry.results_count,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _trim(db: Session, user_id, keep: int) -> None:
    """Leave this user's `keep` newest rows and delete the rest. Caller commits.

    Selected by id rather than expressed as one `DELETE … OFFSET`, which PostgreSQL does not accept
    directly — and the two-step is honest about what it does, since the set is small and bounded.
    """
    if keep <= 0:
        db.execute(delete(SearchHistoryEntry).where(SearchHistoryEntry.user_id == user_id))
        return
    newest = (
        select(SearchHistoryEntry.entry_id)
        .where(SearchHistoryEntry.user_id == user_id)
        .order_by(SearchHistoryEntry.created_at.desc(), SearchHistoryEntry.entry_id.desc())
        .limit(keep)
    )
    keep_ids = list(db.execute(newest).scalars())
    if not keep_ids:
        return
    db.execute(
        delete(SearchHistoryEntry).where(
            SearchHistoryEntry.user_id == user_id,
            SearchHistoryEntry.entry_id.notin_(keep_ids),
        )
    )


def forget(db: Session, user_id, entry_id) -> bool:
    """Remove one row. Returns whether it existed *for this user* — a miss is not an error.

    The `user_id` in the `WHERE` is what stops one account deleting another's row by guessing a
    uuid, and it is why this takes the user rather than trusting the path parameter alone.
    """
    result = db.execute(
        delete(SearchHistoryEntry).where(
            SearchHistoryEntry.user_id == user_id,
            SearchHistoryEntry.entry_id == entry_id,
        )
    )
    db.commit()
    return bool(result.rowcount)


def clear(db: Session, user_id) -> int:
    """Empty this user's history. Returns how many rows went, so the caller can say so."""
    result = db.execute(delete(SearchHistoryEntry).where(SearchHistoryEntry.user_id == user_id))
    db.commit()
    return int(result.rowcount or 0)
