"""The operator gate and the abuse limits — `src/api/security.py`, `src/api/ratelimit.py`.

Both exist because the deployed URL is public. What they defend is not the same thing: the role
gate defends the review table (an open export hands out the triples `DELETE /reviews` needs), and
the limits defend the OpenAI bill — authority versus cost.

The rate-limit cases run against a throwaway app rather than `/api/v1/search`, deliberately. The
real route loads the corpus, so testing there would make these skip on a fresh clone and in CI —
where a limiter that stopped firing would be exactly as invisible as it was before it existed.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import ratelimit
from src.api.auth_middleware import get_current_user
from src.api.ratelimit import DailyCap, SlidingWindow, client_key, limit_llm, limit_writes
from src.api.security import current_operator
from src.config import get_settings
from src.main import app


@pytest.fixture
def settings_env(monkeypatch):
    """Set environment variables and rebuild the cached Settings and limiters around one test."""

    def _apply(**env):
        for key, value in env.items():
            monkeypatch.setenv(key, str(value))
        get_settings.cache_clear()
        ratelimit.reset()
        return get_settings()

    yield _apply
    get_settings.cache_clear()
    ratelimit.reset()


class TestExportRequiresAnAccount:
    """`/reviews/export` and the unscoped `/reviews/summary` — `src/api/security.py`.

    Replaces `TestOperatorToken`. Until 2026-08-27 these were gated on a shared `OPERATOR_TOKEN`
    pasted into the URL; they are now gated on *having an account* — any account. The behaviour
    under test is the same question — *may this caller have every reviewer's verdicts, and therefore
    the triples that empty the table* — asked of a session instead of a secret.

    **The role is deliberately not checked**, and `test_a_signed_in_non_admin_may_export` is what
    holds that open: an export the engineer has to ask an Admin for is a permission request between
    a person and their own work.

    An anonymous case needs no override and touches no database: `get_current_user` rejects a
    missing cookie before it ever looks a user up.
    """

    @contextmanager
    def signed_in_as(self, role: str):
        """Present the app with a signed-in user of `role`, for the duration of the block.

        Both dependencies are overridden because the two endpoints reach the user by different
        routes: `/reviews/export` depends on `get_current_user` through FastAPI (so an override
        applies), while `/reviews/summary` goes through `current_operator`, which calls it directly
        inside a `try` in order not to raise. Overriding only one would make the export and the
        summary disagree about who is signed in.

        `role` is still a parameter even though no endpoint here checks one — so that
        `test_a_signed_in_non_admin_may_export` can state the role it is asserting about.
        """
        user = SimpleNamespace(user_id=uuid4(), email=f"{role.lower()}@test.local", role=role, status="active")
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[current_operator] = lambda: user
        try:
            yield user
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(current_operator, None)

    @pytest.mark.asyncio
    async def test_export_refuses_an_anonymous_caller(self, client):
        """401, and the refusal must not depend on the corpus being loaded.

        The dependency has to run before the handler touches artifacts, or a box mid-reload would
        answer 503 and read as open to anyone probing it.
        """
        response = await client.get("/api/v1/reviews/export")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_a_signed_in_non_admin_may_export(self, client, corpus, review_store):
        """The regression this file exists to prevent: `Admin` must not creep back in as a
        requirement. A `User` is an engineer, and the dataset is the engineer's own output.
        """
        with self.signed_in_as("User"):
            response = await client.get("/api/v1/reviews/export")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_export_is_served_with_no_url_parameter(self, client, corpus, review_store):
        """The point of the change: a signed-in engineer downloads without pasting anything.

        Asserted against a bare URL on purpose. The old gate would have refused this exact request.
        """
        response = await client.get("/api/v1/reviews/export")
        assert response.status_code == 401, "guard: unauthenticated must fail before the signed-in case"
        with self.signed_in_as("Admin"):
            response = await client.get("/api/v1/reviews/export")
        assert response.status_code == 200
        assert "attachment; filename=" in response.headers["content-disposition"]

    @pytest.mark.asyncio
    async def test_a_token_in_the_query_string_no_longer_opens_anything(self, client):
        """Regression guard: the retired mechanism must stay retired.

        `?token=…` was a working credential until 2026-08-27. A stale bookmark, a screenshot, or a
        line in Caddy's access log still carries one, and none of them should be a way in.
        """
        response = await client.get("/api/v1/reviews/export", params={"token": "operator-token-for-tests"})
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_a_reviewer_sees_their_own_summary_but_not_the_whole_table(self, client, corpus, review_store):
        """The split that lets the review bar keep working for testers with no account at all."""
        mine = await client.get("/api/v1/reviews/summary", params={"reviewer": "reviewer-ann"})
        everyone = await client.get("/api/v1/reviews/summary")
        assert mine.status_code == 200
        assert everyone.status_code == 401
        with self.signed_in_as("Admin"):
            assert (await client.get("/api/v1/reviews/summary")).status_code == 200


class TestClientIdentity:
    """`client_key` — who a limit is charged to, which decides whether it can be walked around."""

    def _request(self, peer: str, forwarded: str | None = None):
        headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
        scope = {"type": "http", "headers": headers, "client": (peer, 1234)}
        from fastapi import Request

        return Request(scope)

    def test_an_untrusted_forwarded_header_shares_one_bucket(self, settings_env):
        """Forgers compete for one allowance rather than minting a fresh identity each request.

        The peer address is not believed either when an untrusted header is present, because
        uvicorn's ProxyHeadersMiddleware may already have overwritten it — it is on by default and
        trusts 127.0.0.1, which is precisely where a Cloudflare tunnel connects from. Both launch
        points pass `--no-proxy-headers`; this is what holds if one of them ever does not.
        """
        settings_env(TRUST_PROXY_HEADERS=False)
        forged = [client_key(self._request("10.0.0.1", f"1.2.3.{i}")) for i in range(3)]
        assert len(set(forged)) == 1

    def test_a_direct_client_keeps_its_own_bucket(self, settings_env):
        settings_env(TRUST_PROXY_HEADERS=False)
        assert client_key(self._request("10.0.0.1")) == "10.0.0.1"
        assert client_key(self._request("10.0.0.2")) == "10.0.0.2"

    def test_the_last_forwarded_entry_wins_not_the_first(self, settings_env):
        """The rule that stops a client minting a fresh identity per request.

        Caddy *appends* the address it saw, so a spoofed header arrives as `<forged>, <real>`.
        Reading the first entry — the usual "original client" convention, correct behind a chain of
        trusted proxies — would let anyone reset their own rate limit at will.
        """
        settings_env(TRUST_PROXY_HEADERS=True)
        assert client_key(self._request("10.0.0.1", "1.2.3.4, 203.0.113.9")) == "203.0.113.9"

    def test_a_single_entry_is_the_client(self, settings_env):
        settings_env(TRUST_PROXY_HEADERS=True)
        assert client_key(self._request("10.0.0.1", "203.0.113.9")) == "203.0.113.9"

    def test_two_colleagues_behind_one_office_address_get_their_own_allowance(self, settings_env):
        """The company-shaped failure: one NAT is one address, so a team shared a single bucket.

        It bit hardest during a review pass, which *is* a burst of writes — two engineers clicking
        verdicts at a normal pace reach 60/minute together while each stays well under it alone.
        """
        settings_env(TRUST_PROXY_HEADERS=True)
        office = self._request("10.0.0.1", "203.0.113.9")
        ann = SimpleNamespace(user_id=uuid4())
        bob = SimpleNamespace(user_id=uuid4())

        assert client_key(office, ann) != client_key(office, bob)

    def test_one_account_keeps_its_bucket_across_networks(self, settings_env):
        """Laptop to phone tether mid-session is not a fresh allowance, nor a lost one."""
        settings_env(TRUST_PROXY_HEADERS=True)
        ann = SimpleNamespace(user_id=uuid4())

        at_desk = client_key(self._request("10.0.0.1", "203.0.113.9"), ann)
        on_mobile = client_key(self._request("10.0.0.2", "198.51.100.7"), ann)
        assert at_desk == on_mobile

    def test_an_account_bucket_cannot_collide_with_an_address(self, settings_env):
        """Same namespacing as a verdict's attribution, and the same reason it is needed."""
        settings_env(TRUST_PROXY_HEADERS=True)
        ann = SimpleNamespace(user_id=uuid4())
        assert client_key(self._request("10.0.0.1"), ann).startswith("user:")

    def test_an_anonymous_caller_still_falls_back_to_the_address(self, settings_env):
        """The open routes exist for a tester arriving from a link, so the address rules still run."""
        settings_env(TRUST_PROXY_HEADERS=False)
        assert client_key(self._request("10.0.0.1"), None) == "10.0.0.1"


class TestSlidingWindow:
    def test_it_allows_up_to_the_limit_then_reports_a_retry_delay(self):
        window = SlidingWindow(limit=3, window_s=60.0)
        assert [window.check("a", now=100.0) for _ in range(3)] == [0.0, 0.0, 0.0]
        assert window.check("a", now=100.0) > 0

    def test_the_window_slides_rather_than_resetting_on_a_boundary(self):
        """A fixed window lets a caller spend two full allowances across the boundary."""
        window = SlidingWindow(limit=2, window_s=60.0)
        window.check("a", now=100.0)
        window.check("a", now=155.0)
        assert window.check("a", now=159.0) > 0  # both hits still inside the window
        assert window.check("a", now=161.0) == 0.0  # the first has aged out, and only the first

    def test_clients_are_counted_separately(self):
        window = SlidingWindow(limit=1, window_s=60.0)
        assert window.check("a", now=100.0) == 0.0
        assert window.check("b", now=100.0) == 0.0

    def test_idle_clients_are_forgotten(self):
        """Otherwise the dict grows one entry per address seen, with an attacker holding the tap."""
        window = SlidingWindow(limit=5, window_s=60.0)
        for i in range(600):
            window.check(f"client-{i}", now=100.0)
        window.check("late", now=100_000.0)
        assert len(window._hits) == 1


class TestDailyCap:
    def test_it_stops_at_the_limit_and_resets_the_next_day(self):
        cap = DailyCap(limit=2)
        day = 86_400.0 * 20_000
        assert [cap.check(now=day) for _ in range(3)] == [True, True, False]
        assert cap.check(now=day + 86_400) is True


class TestLimitedEndpoints:
    """The dependencies as a route actually sees them, on an app with no corpus to load."""

    @staticmethod
    def _app() -> FastAPI:
        app = FastAPI()

        @app.post("/llm", dependencies=[Depends(limit_llm)])
        async def llm() -> dict:
            return {"ok": True}

        @app.put("/write", dependencies=[Depends(limit_writes)])
        async def write() -> dict:
            return {"ok": True}

        return app

    async def _client(self):
        return AsyncClient(transport=ASGITransport(app=self._app()), base_url="http://test")

    @pytest.mark.asyncio
    async def test_the_llm_endpoint_429s_past_the_per_minute_limit(self, settings_env):
        settings_env(LLM_RATE_LIMIT_PER_MINUTE=2, LLM_DAILY_CAP=100)
        async with await self._client() as ac:
            assert [(await ac.post("/llm")).status_code for _ in range(2)] == [200, 200]
            refused = await ac.post("/llm")
        assert refused.status_code == 429
        # Without this a client cannot tell a rate limit from an outage, and retries immediately.
        assert int(refused.headers["retry-after"]) >= 1

    @pytest.mark.asyncio
    async def test_the_daily_cap_answers_503_rather_than_429(self, settings_env):
        """429 means "you asked too often". The honest message here is that the day's budget is gone."""
        settings_env(LLM_RATE_LIMIT_PER_MINUTE=100, LLM_DAILY_CAP=2)
        async with await self._client() as ac:
            assert [(await ac.post("/llm")).status_code for _ in range(2)] == [200, 200]
            spent = await ac.post("/llm")
        assert spent.status_code == 503
        assert "today" in spent.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_a_refused_request_does_not_spend_the_daily_budget(self, settings_env):
        """The per-client window is checked first, so hammering cannot burn the shared cap."""
        settings_env(LLM_RATE_LIMIT_PER_MINUTE=1, LLM_DAILY_CAP=10)
        async with await self._client() as ac:
            for _ in range(6):
                await ac.post("/llm")
        _, daily, _ = ratelimit._limiters()
        assert daily.used == 1

    @pytest.mark.asyncio
    async def test_review_writes_have_their_own_looser_limit(self, settings_env):
        """A reviewing session is bursty — a tester judges ten cards in a row."""
        settings_env(LLM_RATE_LIMIT_PER_MINUTE=1, WRITE_RATE_LIMIT_PER_MINUTE=3)
        async with await self._client() as ac:
            assert [(await ac.put("/write")).status_code for _ in range(3)] == [200, 200, 200]
            assert (await ac.put("/write")).status_code == 429
