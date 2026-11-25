"""Caps on the endpoints that cost money or write data.

`POST /search` spends real money on every call: one gpt-4o-mini completion parses the query into a
constraint. The whole project is budgeted at $5-10 (`CLAUDE.md` § Cost discipline) and the deployed
URL is public with no credential, so an unbounded search endpoint is an open invitation to spend
that budget for us — not necessarily maliciously, a crawler following the link is enough.

Two limits, because they answer different questions:

- **Per caller, per minute.** Stops one visitor hammering the box, and keeps a tester's experience
  unaffected: a person typing queries into a search box does not approach ten a minute. "Caller"
  means the **account** where there is one and the address otherwise — see `client_key`; an address
  puts a whole office behind one NAT into a single bucket, which is a company-shaped failure rather
  than an abuse-shaped one.
- **Global, per day.** The one that actually protects the bill. A per-client limit multiplies by the
  number of clients, and an attacker picks that number. `llm_daily_cap` is a hard ceiling on
  completions bought in a day no matter who asks.

Hitting the daily cap returns 503, not 429: 429 means "you asked too often", and the honest message
here is that the service itself is done for the day. A tester who sees it should tell the operator,
not wait thirty seconds and retry.

**No new dependency.** `slowapi` is the usual answer and would add a package, a middleware and a
Redis-shaped decision to a service that runs as one uvicorn process on one box. The state below is
per process, which is exactly right for that deployment and would be wrong the day it is replicated
— `docs/deploy.md` would have to say so, and it does.

**Reads are not limited at all.** A results grid fetches ten thumbnails at once and the review
restore fires on every search; limiting those buys nothing (they touch local disk and sqlite) and
would break the UI at the first busy moment.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request

from src.api.security import current_operator
from src.config import get_settings
from src.db.models import User


def client_key(request: Request, operator: User | None = None) -> str:
    """Who to charge this request to: the account when there is one, the address when there is not.

    **An address is the wrong unit for a company, and this is the shape of the failure.** Everyone
    behind one office NAT or VPN egress leaves the same address, so a whole team lands in one
    bucket: ten searches a minute for the building, and a colleague's review pass silently spending
    another's allowance. It bites hardest during exactly the activity this product exists for —
    `write_rate_limit_per_minute` is 60, and two engineers clicking through verdicts at a normal
    pace reach that together while each stays well under it alone.

    Charging the account instead is not a hole in the bill protection, because the per-client window
    was never what protects it: an attacker picks the number of clients either way, by address or by
    registration, and `llm_daily_cap` is the hard ceiling that does not multiply. What the per-client
    window buys is that one caller cannot make the service feel broken for the next one — which is a
    statement about people, so an account is the truer unit for it than an address.

    Anonymous callers keep the address rules below, and a signed-in caller never falls back to them,
    so one person's allowance does not change when they move network.

    Behind Caddy every request arrives from the proxy's container address, so charging
    `request.client.host` would put every visitor in one bucket and let the first tester exhaust
    the limit for everyone. `X-Forwarded-For` carries the real address — when it can be trusted.

    **The last entry, not the first.** Caddy *appends* the peer it actually saw, so a client that
    sends `X-Forwarded-For: 1.2.3.4` produces `1.2.3.4, <their real address>`. Reading the first
    entry — the conventional "original client" rule, correct behind a chain of trusted proxies —
    lets anyone forge a fresh identity per request and walk straight through the limiter. With
    exactly one trusted proxy in front, the last entry is the only one the client could not write.

    **uvicorn does this too, and its default is the dangerous one.** `ProxyHeadersMiddleware` is on
    unless disabled, trusting `127.0.0.1`, and it *overwrites* `scope["client"]` from the header —
    so on a Cloudflare tunnel, where the connection genuinely arrives from 127.0.0.1, any visitor
    can set `X-Forwarded-For` and be seen as whoever they typed. Measured, not assumed: five
    searches against a 1/minute limit returned 200 five times with a different forged address on
    each. `--forwarded-allow-ips=*` does not fix it either; that path takes the *first* entry,
    which is the one the client writes. Both launch points therefore pass `--no-proxy-headers`
    (`Dockerfile` CMD, `Makefile: run`) and the decision lives here instead.

    The last clause is the belt to that pair of braces. A flag in two files is one hand-typed
    `uvicorn src.main:app` away from being absent, and the hole reopens silently. So when the
    header is *not* trusted but is present, the peer address cannot be believed either — it may
    already have been rewritten — and every such request shares one bucket. A forger then competes
    with every other forger for a single allowance instead of minting a fresh one per request. The
    cost lands only on a deployment that is behind a proxy and has not said so, which
    `docs/deploy.md` tells you to set.
    """
    if operator is not None:
        # Same namespacing as a review's attribution, and for the same reason: an address and a
        # `user_id` must not be able to name the same bucket.
        return f"user:{operator.user_id}"
    forwarded = request.headers.get("x-forwarded-for", "")
    if get_settings().trust_proxy_headers:
        if forwarded:
            return forwarded.rsplit(",", 1)[-1].strip()
    elif forwarded:
        return "untrusted-forwarded"
    return request.client.host if request.client else "unknown"


class SlidingWindow:
    """Per-key request timestamps inside a rolling window.

    Sliding rather than a fixed window: a fixed window lets a caller spend the whole allowance at
    :59 and the whole of the next one at :00, which is twice the intended rate at exactly the moment
    a burst is happening. The memory cost is one float per request in the window, and the window is
    a minute.
    """

    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> float:
        """Record a hit. Returns 0.0 if allowed, or the seconds until the caller may retry."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            cutoff = now - self.window_s
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                # Retry-After from the oldest hit still in the window: that is when a slot frees.
                # Rounded up, because a client that retries at exactly the boundary is refused again
                # and reads the number as a lie.
                return max(1.0, hits[0] + self.window_s - now)
            hits.append(now)
            self._prune(now)
            return 0.0

    def _prune(self, now: float) -> None:
        """Forget keys with nothing left in the window. Caller holds the lock.

        Without this the dict grows one entry per address seen since the process started, which on a
        public URL is a slow leak with an attacker holding the tap. Swept on write rather than on a
        timer so there is no background task to supervise; the scan is over keys, and the keys that
        survive are the ones actually talking to us.
        """
        if len(self._hits) < 512:
            return
        cutoff = now - self.window_s
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
            del self._hits[key]


class DailyCap:
    """A counter that resets on the UTC day. The ceiling on what a day can cost."""

    def __init__(self, limit: int):
        self.limit = limit
        self._day = 0
        self._count = 0
        self._lock = threading.Lock()

    def check(self, now: float | None = None) -> bool:
        """Record one unit of spend. False once the day's budget is gone."""
        now = time.time() if now is None else now
        day = int(now // 86400)
        with self._lock:
            if day != self._day:
                self._day, self._count = day, 0
            if self._count >= self.limit:
                return False
            self._count += 1
            return True

    @property
    def used(self) -> int:
        return self._count


_llm_window: SlidingWindow | None = None
_llm_daily: DailyCap | None = None
_write_window: SlidingWindow | None = None
_init_lock = threading.Lock()


def _limiters() -> tuple[SlidingWindow, DailyCap, SlidingWindow]:
    """Build the limiters on first use, from settings.

    Lazily rather than at import, so a test that overrides the limits with monkeypatch and calls
    `reset()` gets them, instead of whatever the environment happened to hold when `routes.py` was
    first imported.
    """
    global _llm_window, _llm_daily, _write_window
    with _init_lock:
        if _llm_window is None:
            s = get_settings()
            _llm_window = SlidingWindow(s.llm_rate_limit_per_minute, 60.0)
            _llm_daily = DailyCap(s.llm_daily_cap)
            _write_window = SlidingWindow(s.write_rate_limit_per_minute, 60.0)
    return _llm_window, _llm_daily, _write_window


def reset() -> None:
    """Drop the limiters so the next request rebuilds them. For tests and nothing else."""
    global _llm_window, _llm_daily, _write_window
    with _init_lock:
        _llm_window = _llm_daily = _write_window = None


def limit_llm(request: Request, operator: User | None = Depends(current_operator)) -> None:
    """Guard an endpoint that buys an LLM completion. Per-caller rate, then the global daily cap.

    `current_operator` never raises and FastAPI caches it per request, so a route that already
    depends on it pays for one resolution rather than two.
    """
    window, daily, _ = _limiters()
    retry_after = window.check(client_key(request, operator))
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many searches. Wait a moment and try again.",
            headers={"Retry-After": str(int(retry_after + 0.999))},
        )
    if not daily.check():
        # Checked *after* the per-client window so a single hammering client cannot spend the day's
        # budget on requests it was going to be refused for anyway.
        raise HTTPException(
            status_code=503,
            detail="The archive has reached today's search limit. Please try again tomorrow.",
        )


def limit_writes(request: Request, operator: User | None = Depends(current_operator)) -> None:
    """Guard the review writes. Cheap per call, but the table is the one deliverable here.

    The account key matters most here: a review pass *is* a burst of writes, so two colleagues on
    one office address were sharing the 60/minute allowance that each of them alone stays under.
    """
    _, _, window = _limiters()
    retry_after = window.check(client_key(request, operator))
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many review updates. Wait a moment and try again.",
            headers={"Retry-After": str(int(retry_after + 0.999))},
        )
