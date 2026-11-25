"""Shared fixtures.

The LLM is mocked everywhere: tests must be free, deterministic, and runnable in CI with no API key.
Parsing is the only node that calls a model, so patching `parse_constraint` takes the whole graph
offline — there is no second place a completion can leak out.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.models.schemas import QueryConstraint

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS = os.path.join(REPO, "data/artifacts/vectors.npy")


def pytest_collection_modifyitems(config, items):
    """Skip corpus-dependent tests when the artifacts have not been built, rather than erroring.

    A fresh clone has no `data/artifacts/` until `scripts/promote_artifacts.py` runs, and that needs
    the 4 GB nuScenes download. Someone changing a reranker should still be able to run the unit
    tests, and a hard failure there reads as "the repo is broken" rather than "you skipped a step".
    """
    if os.path.exists(ARTIFACTS):
        return
    skip = pytest.mark.skip(reason="data/artifacts not built — run scripts/promote_artifacts.py")
    for item in items:
        if "fidelity" in item.nodeid or "corpus" in getattr(item, "fixturenames", ()):
            item.add_marker(skip)


@pytest.fixture
def signed_in():
    """Run a gated review endpoint as a signed-in user. Role `User` on purpose.

    `User`, not `Admin`, because that is the case the gate is *for*: the export belongs to the
    engineer who produced it, and six of the eight accounts on the deployed box are role `User`.
    A fixture that signed in as an Admin would pass just as happily against an Admin-only gate and
    so would not notice it being reintroduced.

    Overrides the two dependencies rather than minting a real JWT and inserting a real user row.
    The gate itself is under test in `test_api/test_security.py`, and a route test that had to stand
    up Postgres in order to read a review summary would be testing the database instead of the
    contract.

    **Deliberately not autouse.** The fixture this replaces (`_no_operator_token`) was, and it hid
    the gate from every test in the suite; `test_security.py`'s module docstring names that as
    fixture-shaped blindness. Asking for it by name keeps "this endpoint needs an account" legible
    in the test that needs one, and leaves the ungated calls genuinely ungated.
    """
    from types import SimpleNamespace
    from uuid import uuid4

    from src.api.auth_middleware import get_current_user
    from src.api.security import current_operator
    from src.main import app

    user = SimpleNamespace(user_id=uuid4(), email="engineer@test.local", role="User", status="active")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[current_operator] = lambda: user
    yield user
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(current_operator, None)


@pytest_asyncio.fixture
async def client():
    """Async HTTP client bound to the app in-process — no server, no port."""
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def parsed_constraint():
    """Patch the single LLM call, returning whatever constraint the test needs.

    async def test_x(parsed_constraint):
        with parsed_constraint(objects=["pedestrian"]):
            ...
    """

    def _patch(**fields):
        return patch(
            "src.agents.nodes.search_nodes.parse_constraint", AsyncMock(return_value=QueryConstraint(**fields))
        )

    return _patch


@pytest.fixture
def corpus():
    """The promoted corpus. Needs data/artifacts/ — see pytest_collection_modifyitems."""
    from src.services.search.artifacts import get_corpus

    return get_corpus()


@pytest.fixture
def review_store(tmp_path, monkeypatch):
    """An empty review database per test, discarded afterwards.

    Both caches have to be cleared, and in this order: `get_store` reads `get_settings()`, so a
    stale settings object would hand it the real `data/reviews.db` and the suite would accumulate
    rows in the developer's own review set — passing locally, and passing in CI for the wrong reason.

    Overriding `REVIEW_DB` here is also why the suite could not catch the `.env` misconfiguration
    that made every verdict 500 on a real server: a fixture that replaces a setting can never
    exercise the value a deployment actually uses. That case is covered in `test_reviews.py` by
    asserting the store reads `review_db` rather than `database_url`.
    """
    from src.config import get_settings
    from src.services import reviews

    monkeypatch.setenv("REVIEW_DB", str(tmp_path / "reviews.db"))
    get_settings.cache_clear()
    reviews.get_store.cache_clear()
    yield reviews.get_store()
    get_settings.cache_clear()
    reviews.get_store.cache_clear()
