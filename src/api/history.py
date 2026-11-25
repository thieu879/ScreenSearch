"""Search history — one list per account, not one per browser.

**Signed-in only, and that is the point rather than a restriction.** These routes sit apart from the
review routes, which are deliberately open so a pseudonymous tester can reach them from a link with
no credential (`api/security.py`). A history has no such caller: it *is* account data, there is no
useful anonymous version of "your recent searches", and `/history` has been behind `ProtectedRoute`
in the frontend since login landed. So the session is required, and whose history is being read or
written is never a request parameter — the same rule `services/reviews.py:reviewer_identity` applies
to a verdict, arrived at here by construction instead of by resolution.

**Recording is a separate request from searching, on purpose.** Folding it into `POST /search` would
be one round trip fewer, and would couple the endpoint that must always work to a write that may
fail: a history row is a convenience, and losing one must never cost a search. It would also make
the open search endpoint write account data. The frontend fires this and does not wait for it.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from src.api.auth_middleware import get_current_user
from src.db.models import SearchHistoryEntry, User
from src.db.session import get_db
from src.models.schemas import HistoryEntry, HistoryWrite
from src.services import history

logger = logging.getLogger(__name__)
history_router = APIRouter(prefix="/history", tags=["history"])


def _entry(row: SearchHistoryEntry) -> HistoryEntry:
    """One stored row as the API shape. Ids and timestamps become strings at the boundary."""
    return HistoryEntry(
        entry_id=str(row.entry_id),
        keyword=row.keyword,
        results_count=row.results_count,
        filters=list(row.filters or []),
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


@history_router.get("", response_model=list[HistoryEntry])
def list_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[HistoryEntry]:
    """This account's recent searches, newest first, capped at `history.HISTORY_LIMIT`."""
    return [_entry(row) for row in history.recent(db, user.user_id)]


@history_router.post("", response_model=HistoryEntry, status_code=201)
def add_history(
    entry: HistoryWrite,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HistoryEntry:
    """Remember one search. Re-running a query moves it to the top rather than duplicating it."""
    return _entry(history.record(db, user.user_id, entry))


@history_router.delete("/{entry_id}", status_code=204)
def delete_history_entry(
    entry_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Remove one row.

    404 when it is not *this account's* row, which covers both "no such id" and "somebody else's" —
    deliberately the same answer, since distinguishing them would confirm that another account's
    entry exists. `services.history.forget` scopes the delete itself, so a wrong id deletes nothing
    even if this check were ever removed.
    """
    try:
        parsed = uuid.UUID(entry_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="No such history entry.") from exc
    if not history.forget(db, user.user_id, parsed):
        raise HTTPException(status_code=404, detail="No such history entry.")
    return Response(status_code=204)


@history_router.delete("", status_code=204)
def clear_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Empty this account's history. Idempotent — clearing nothing is a 204, not an error."""
    history.clear(db, user.user_id)
    return Response(status_code=204)
