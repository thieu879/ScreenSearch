"""Who is allowed to reach the operator's endpoints.

**The line is having an account, not holding a role.** ``/reviews/export`` and the unscoped
``/reviews/summary`` require a signed-in user — any signed-in user. They deliberately do **not**
require ``Admin``: the export is the engineer's own work product, and making a person ask someone
else's permission to download the dataset they just built is a worse failure than the one the gate
is there to prevent. Six of the eight accounts on the deployed box are role ``User``, including
teammates who do the reviewing, so an Admin-only export would have locked out most of the people it
exists for.

**The old answer, and the date it stopped being right.** This module used to gate both endpoints on
``OPERATOR_TOKEN``: a shared secret handed to a browser by opening the app with
``?operator_token=…``. That existed because the service had no accounts — testers are deliberately
pseudonymous, and ``services/reviews.py`` explains that a reviewer id is a browser uuid that nobody
is ever asked for a name to obtain. A shared secret was the only way to separate the person running
a session from the people in it.

That premise expired on **2026-08-27**, when the deployment got a working login. The token then
became a *second, weaker credential running in parallel with a real one*: one string for everybody,
not revocable, not attributable to a person, in the proxy's access log by design — and it made a
signed-in engineer paste a secret into a URL to download their own data.

**Why these two endpoints are gated at all — unchanged, and the part worth keeping.**
``GET /reviews/export?decision=all`` returns every row, and a row is ``(query, frame_id, reviewer)``
— precisely the triple ``DELETE /reviews`` requires. Left open, the export is not merely a data
leak: it hands a stranger the means to delete every verdict in the table, one call at a time, and
the deletion endpoint has no other protection because a reviewer id is unguessable *only until it is
published*. Requiring an account does not make that impossible — registration is open — but it does
mean the capability is no longer handed to an anonymous passer-by, and it leaves a user row behind.

The unscoped ``GET /reviews/summary`` is gated on the same reasoning at a smaller scale: with no
``reviewer`` it totals the whole table, which is the session's view rather than one tester's own
progress.

**Not gated, on purpose.** ``/search``, ``/chat``, the thumbnails, ``/status`` and the
reviewer-scoped review calls all stay open, because a tester has to reach them from a link with no
credential — including ``DELETE /reviews``, which is how a tester un-ticks their own verdict
(``useReviews.ts``). What protects the open routes is ``ratelimit.py`` — a different question: cost
and abuse, not authority.

**A link carries a cookie, and that is what makes a session gate workable here.** The export is
reached by *navigating* to it rather than by ``fetch``, because it answers with
``Content-Disposition: attachment`` and the browser has to save the file under the server's own name
(``ReviewBar.tsx`` records why it is a link). A link cannot set a header, which is exactly what
forced the old token into the query string. It *does* send cookies: ``access_token`` is
``Path=/; SameSite=lax``, and a top-level GET navigation is precisely what ``lax`` permits. So the
session travels with the click and there is nothing left to paste anywhere.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.api.auth_middleware import get_current_user
from src.db.models import User
from src.db.session import get_db

__all__ = ["current_operator", "require_operator"]


def current_operator(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """The signed-in user, or ``None``. Never raises.

    For a route that is open on one branch and gated on another. ``/reviews/summary`` answers a
    pseudonymous tester and a signed-in engineer from the same URL, so it cannot hang off a
    dependency that 401s before the handler decides which case it is in. Wholly-gated routes depend
    on ``get_current_user`` directly and get the status code for free.

    No database round-trip happens for an anonymous caller: a missing or undecodable cookie is
    rejected before the user lookup, so this stays cheap on the common path.
    """
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None


def require_operator(user: User | None) -> None:
    """Reject a caller who is not signed in. A plain function, not a dependency.

    Called from inside a handler that is gated on only one of its branches. No role is checked —
    see the module docstring: the export belongs to the engineer who produced it, and gating it on
    ``Admin`` would put a permission request between a person and their own work.
    """
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="This view is for signed-in users. Sign in to continue.",
            # Names the scheme without naming a realm a browser would pop a native login box for:
            # the sign-in is the application's own page, not a credential prompt.
            headers={"WWW-Authenticate": "Bearer"},
        )
