"""Search history — the account owns it, and nothing about that is the client's to say.

These are the assertions that would have caught the reported defect had the feature been built this
way first: two accounts must not see one list, and a signed-out caller must not see one at all.

Storage is a per-test in-memory SQLite database, following `test_auth.py`. The one thing that needs
saying about that: the model's `UUID`/`JSONB` columns are PostgreSQL types, so the table is created
with `with_variant` bindings supplied here rather than by pointing at a real server — a test that
needs Supabase to read a list of five strings is testing the network.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.auth_middleware import get_current_user
from src.db.models import SearchHistoryEntry, User
from src.db.session import get_db
from src.main import app
from src.services import history


@asynccontextmanager
async def _no_lifespan(app):
    """The corpus is irrelevant here and takes ~36 s to load."""
    yield


app.router.lifespan_context = _no_lifespan

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_tables():
    User.__table__.create(bind=engine, checkfirst=True)
    SearchHistoryEntry.__table__.create(bind=engine, checkfirst=True)
    yield
    SearchHistoryEntry.__table__.drop(bind=engine, checkfirst=True)
    User.__table__.drop(bind=engine, checkfirst=True)


@contextmanager
def _override(dependency, replacement):
    """Swap one dependency and put back whatever was there — not whatever "nothing" was.

    Popping instead of restoring is a real bug and it bit here: `test_auth.py` installs its own
    `get_db` override at *module import*, so a fixture that tore down by popping deleted it for
    every test that ran afterwards, and an unrelated admin test failed against a database it was
    never meant to reach. A fixture must not destroy state it did not create.
    """
    previous = app.dependency_overrides.get(dependency)
    app.dependency_overrides[dependency] = replacement
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(dependency, None)
        else:
            app.dependency_overrides[dependency] = previous


@pytest.fixture
def client(db_tables):
    def _db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    with _override(get_db, _db):
        yield TestClient(app)


@pytest.fixture
def as_user():
    """Sign in as a given account for the duration of a `with` block."""

    @contextmanager
    def _as(user):
        with _override(get_current_user, lambda: user):
            yield user

    return _as


def _account(session, email: str) -> User:
    user = User(user_id=uuid4(), email=email, password_hash="x", role="User", status="active")
    session.add(user)
    session.commit()
    return user


class TestHistoryIsPerAccount:
    def test_two_accounts_do_not_see_one_list(self, client, as_user):
        """The reported defect, at the layer that now decides it.

        Both accounts here reach the same server from the same browser — which used to mean the same
        `localStorage` key and therefore one shared list.
        """
        session = Session()
        ann, bob = _account(session, "ann@test.local"), _account(session, "bob@test.local")

        with as_user(ann):
            client.post("/api/v1/history", json={"keyword": "a pedestrian on the right", "results_count": 10})
        with as_user(bob):
            client.post("/api/v1/history", json={"keyword": "a bus at night", "results_count": 4})
            assert [e["keyword"] for e in client.get("/api/v1/history").json()] == ["a bus at night"]
        with as_user(ann):
            assert [e["keyword"] for e in client.get("/api/v1/history").json()] == ["a pedestrian on the right"]

    def test_a_signed_out_caller_has_no_history_at_all(self, client):
        """There is no useful anonymous version of "your recent searches", so there is none."""
        assert client.get("/api/v1/history").status_code == 401
        assert client.post("/api/v1/history", json={"keyword": "x"}).status_code == 401
        assert client.delete("/api/v1/history").status_code == 401

    def test_one_account_cannot_delete_another_s_entry(self, client, as_user):
        """404, not 403 — distinguishing them would confirm the other account's row exists."""
        session = Session()
        ann, bob = _account(session, "ann2@test.local"), _account(session, "bob2@test.local")

        with as_user(ann):
            entry_id = client.post("/api/v1/history", json={"keyword": "a cyclist"}).json()["entry_id"]
        with as_user(bob):
            assert client.delete(f"/api/v1/history/{entry_id}").status_code == 404
        with as_user(ann):
            assert len(client.get("/api/v1/history").json()) == 1


class TestHistoryBehaviour:
    def test_re_running_a_search_moves_it_up_rather_than_duplicating(self, client, as_user):
        """The list answers "what have I been working on"; ten copies of one query answer it worse."""
        session = Session()
        ann = _account(session, "ann3@test.local")

        with as_user(ann):
            for keyword in ("a bus", "a cyclist", "a bus"):
                client.post("/api/v1/history", json={"keyword": keyword, "results_count": 3})
            assert [e["keyword"] for e in client.get("/api/v1/history").json()] == ["a bus", "a cyclist"]

    def test_the_same_query_in_different_case_is_the_same_search(self, client, as_user):
        session = Session()
        ann = _account(session, "ann4@test.local")

        with as_user(ann):
            client.post("/api/v1/history", json={"keyword": "A Bus At Night"})
            client.post("/api/v1/history", json={"keyword": "a bus at night"})
            assert len(client.get("/api/v1/history").json()) == 1

    def test_it_is_bounded_so_the_table_cannot_grow_without_limit(self, client, as_user, monkeypatch):
        """A convenience list, not an archive. Trimmed on write, so nothing accumulates unattended."""
        monkeypatch.setattr(history, "HISTORY_LIMIT", 3)
        session = Session()
        ann = _account(session, "ann5@test.local")

        with as_user(ann):
            for i in range(6):
                client.post("/api/v1/history", json={"keyword": f"query {i}"})
            kept = [e["keyword"] for e in client.get("/api/v1/history").json()]

        assert len(kept) == 3
        assert "query 5" in kept and "query 0" not in kept

    def test_the_result_count_rides_along_because_it_decides_a_repeat(self, client, as_user):
        """A row saying a query returned nothing is more useful than the query alone."""
        session = Session()
        ann = _account(session, "ann6@test.local")

        with as_user(ann):
            client.post("/api/v1/history", json={"keyword": "a polar bear", "results_count": 0})
            assert client.get("/api/v1/history").json()[0]["results_count"] == 0

    def test_clearing_is_idempotent_and_scoped(self, client, as_user):
        session = Session()
        ann, bob = _account(session, "ann7@test.local"), _account(session, "bob7@test.local")

        with as_user(bob):
            client.post("/api/v1/history", json={"keyword": "a truck"})
        with as_user(ann):
            client.post("/api/v1/history", json={"keyword": "a bus"})
            assert client.delete("/api/v1/history").status_code == 204
            assert client.delete("/api/v1/history").status_code == 204
            assert client.get("/api/v1/history").json() == []
        with as_user(bob):
            assert len(client.get("/api/v1/history").json()) == 1

    def test_a_malformed_id_is_a_miss_not_a_crash(self, client, as_user):
        session = Session()
        ann = _account(session, "ann8@test.local")
        with as_user(ann):
            assert client.delete("/api/v1/history/not-a-uuid").status_code == 404
