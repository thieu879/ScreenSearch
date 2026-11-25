"""API contract tests — the shapes `docs/api-contract.md` promises the frontend.

The agent is patched at the route boundary for most of these: what is under test here is the HTTP
contract, not the pipeline. One end-to-end case runs the real thing and is marked `slow`.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

from src.config import get_settings
from src.models.schemas import FrameHit
from src.services.reviews import ReviewKey

MATCHED_STATE = {
    "matched": True,
    "constraint": {"objects": ["pedestrian"], "relations": {"pedestrian": ["front_left"]}},
    "results": [
        FrameHit(
            frame_id="abc_CAM_FRONT",
            scene_id="s1",
            timestamp_s=1.5,
            score=0.31,
            thumb_url="/api/v1/frames/abc_CAM_FRONT/thumb",
            satisfied=["object:pedestrian"],
        )
    ],
    "distinct_scenes": 6,
    "reason": "",
}
REJECTED_STATE = {
    "matched": False,
    "constraint": {"objects": []},
    "results": [],
    "distinct_scenes": 0,
    # Fixture text, not a claim about the corpus — this mock only exercises the route's pass-through
    # of `reason`. The real sentence is built in `rejection_reason` and its size read from
    # provenance; a plausible-looking count here would just be another literal to go stale.
    "reason": "No matching frames in this archive. <archive description>",
}


def _agent(state):
    return patch("src.api.routes.agent.ainvoke", AsyncMock(return_value=state))


@pytest.mark.asyncio
async def test_health_is_cheap_and_always_answers(client):
    """The deploy's uptime check calls this; it must not depend on the corpus being loaded."""
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "corpus_frames" in body and "version" in body


@pytest.mark.asyncio
async def test_health_names_the_running_build(client):
    """A bug report against a link that keeps being redeployed is unattributable without this.

    `unknown` is the honest default rather than a plausible-looking one: a promote that skipped
    `--build-arg RELEASE=...` must be visible in the smoke test, not silently indistinguishable
    from a good deploy.
    """
    body = (await client.get("/health")).json()
    assert "release" in body
    assert isinstance(body["release"], str) and body["release"]


@pytest.mark.asyncio
async def test_search_returns_hits_and_the_parsed_constraint(client):
    with _agent(MATCHED_STATE):
        response = await client.post("/api/v1/search", json={"query": "a pedestrian", "top_k": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["distinct_scenes"] == 6
    assert body["results"][0]["thumb_url"].endswith("/thumb")
    # The constraint is echoed back so a wrong parse is visible rather than silently searched for.
    assert body["constraint"]["objects"] == ["pedestrian"]


@pytest.mark.asyncio
async def test_no_match_is_a_200_with_a_reason_not_an_error(client):
    """`matched: false` is an answer. A 4xx/5xx would make the UI show a failure state for a search
    that worked perfectly and correctly found nothing."""
    with _agent(REJECTED_STATE):
        response = await client.post("/api/v1/search", json={"query": "a snow-covered road"})
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False
    assert body["results"] == []
    assert body["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"query": ""},  # empty
        {"query": "x" * 501},  # over max_length
        {"query": "ok", "top_k": 0},  # below range
        {"query": "ok", "top_k": 999},  # above range
        {},  # missing required field
    ],
)
async def test_invalid_requests_are_rejected_by_validation(client, payload):
    response = await client.post("/api/v1/search", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_failure_does_not_leak_the_exception(client):
    """The rubric asks for errors that never leak raw exceptions; the template returned str(e)."""
    with patch("src.api.routes.agent.ainvoke", AsyncMock(side_effect=RuntimeError("secret/path"))):
        response = await client.post("/api/v1/search", json={"query": "anything"})
    assert response.status_code == 500
    assert "secret/path" not in response.text


@pytest.mark.asyncio
async def test_unknown_thumbnail_is_404(client):
    response = await client.get("/api/v1/frames/does-not-exist/thumb")
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frame_id",
    [
        "..%2f..%2f.env",  # encoded traversal — Starlette decodes %2F into a path separator
        "%2e%2e%2f.env",
        "..%2f..%2f..%2fetc%2fpasswd",
        "C:%2fWindows%2fsystem32",  # absolute path
        "D:%2fother%2ffile",  # different Windows drive — see below
        "abc_CAM_FRONT",  # right shape, wrong length: not 32 hex chars
        "ABCDEF0123456789abcdef0123456789_CAM_FRONT",  # uppercase hex is not a nuScenes token
    ],
)
async def test_thumbnail_rejects_anything_that_is_not_a_frame_id(client, frame_id):
    """frame_id arrives straight off the URL, so it must not be able to address the filesystem.

    The different-drive case is the one that was actually broken: `os.path.commonpath` raises
    ValueError rather than returning False when two paths have no common drive, which surfaced as
    a 500 for what is simply an unknown id. Windows-only, so it would never have shown up in the
    Linux deploy — a good argument for testing the branch rather than the platform.
    """
    response = await client.get(f"/api/v1/frames/{frame_id}/thumb")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_thumbnail_serves_a_real_frame(client, corpus):
    """The whitelist must not be so strict that it rejects the ids the corpus actually contains.

    The id comes from whichever thumbnail is on disk rather than from `frame_ids[0]`, because
    thumbnails are a fetched cache and not a committed artifact. `scripts/fetch_assets.py` treats a
    failed thumbnail fetch as a warning on purpose — search does not need images — and the Hub
    rate-limits an unauthenticated runner long before 6,858 files, so an environment holding some
    or none of them is expected rather than broken. A 404 for a frame whose image was never cached
    is this route answering correctly; pinning the assertion to one hardcoded id turns that into a
    red build and invites someone to weaken the whitelist that the case above exists to protect.
    """
    root = os.path.abspath(get_settings().thumbs_dir)
    cached = next((f for f in corpus.frame_ids if os.path.exists(os.path.join(root, f"{f}.jpg"))), None)
    if cached is None:
        pytest.skip(f"no thumbnails cached under {root} — run scripts/fetch_assets.py --what thumbs")
    response = await client.get(f"/api/v1/frames/{cached}/thumb")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert "immutable" in response.headers["cache-control"]


def test_promotion_and_api_agree_on_what_a_frame_id_is():
    """Two copies of the pattern, in the writer and the reader. If they drift, the ingest script
    happily writes files the API will refuse to serve."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    from promote_artifacts import FRAME_ID

    from src.api.routes import _FRAME_ID

    assert FRAME_ID.pattern == _FRAME_ID.pattern


@pytest.mark.asyncio
async def test_chat_alias_still_answers(client):
    """Retained from the template contract; the guide's API docs reference it."""
    with _agent(MATCHED_STATE):
        response = await client.post("/api/v1/chat", json={"message": "a pedestrian"})
    assert response.status_code == 200
    assert "1 frames across 6 clips" in response.json()["response"]


@pytest.mark.asyncio
async def test_status_reports_provenance(client, corpus):
    """Readiness carries which experiment the artifacts came from, so a deployed answer stays
    traceable to a measured run rather than to whatever happened to be on disk."""
    response = await client.get("/api/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["artifacts_loaded"] is True
    assert body["corpus_frames"] == corpus.n_frames
    # Compared against the artifacts, not a literal id. What this test is for is that /status
    # reports *the shipped corpus's* experiment rather than a placeholder; pinning one id asserts
    # which corpus is deployed, which is a different claim and one the artifacts already make.
    assert body["provenance"]["retrieval"] == corpus.provenance["retrieval"]
    assert body["provenance"]["retrieval"], "an empty retrieval id is not traceable to anything"


@pytest.mark.asyncio
async def test_status_reports_whether_the_band_was_fitted_here(client, corpus):
    """The one thing on this endpoint that can be wrong while everything above it looks right.

    Asserted as a state rather than a value: which band is shipped is `config.py`'s claim and is
    tested there, while this is the claim that somebody measured it against *these* frames. §10.3
    is the reason — a band from another corpus is wrong in both directions and shows no symptom.
    """
    body = (await client.get("/api/v1/status")).json()
    band = body["rejection_band"]
    assert band["state"] in {"fitted", "unfitted", "corpus_mismatch", "config_drift"}
    assert band["corpus"] == corpus.fingerprint
    assert band["shipped"] == {"tau_reject": get_settings().tau_reject, "tau_confident": get_settings().tau_confident}
    assert band["detail"], "a state nobody can act on is not a report"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_end_to_end_real_pipeline(client, parsed_constraint):
    """One genuine run: real encoder, real index, real rejection. Only the LLM is mocked.

    q01 rather than a spatial query, because its caption score (0.773, measured 2026-08-02) clears
    `tau_confident` with room to spare. Queries sitting near the threshold are covered by
    `test_operating_point_matches_the_measurement` below, which asserts the measured behaviour
    rather than the hoped-for one.
    """
    with parsed_constraint(scene={"weather": "rain", "time": "night"}):
        response = await client.post("/api/v1/search", json={"query": "a wet road at night", "top_k": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert len(body["results"]) == 10
    assert body["distinct_scenes"] >= 5  # the diversity cap is doing its job
    assert body["results"][0]["thumb_url"].startswith("/api/v1/frames/")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_the_confidence_band_end_to_end(client, parsed_constraint, corpus):
    """The three outcomes, on the real pipeline, with the queries that produce each.

    This is where the §6.1 operating point is actually pinned: a single cutoff refuses real queries,
    "a pedestrian to the front-left" among them — the query the metadata filter most clearly
    improves — so the band labels marginal results rather than hiding them. A wrongly hidden result
    is unrecoverable for the user; a wrongly shown one is noise.

    Thresholds are read from settings, not written here. The band was re-fitted for the 170-scene
    corpus (0.35/0.457 → 0.30/0.50, `config.py`) because the mini values do not transfer, and the
    old ones would have refused q21 at 0.330 — a query the system answers correctly.
    """
    # high — clears tau_confident comfortably, 0.773 against 0.50 (measured 2026-08-02)
    with parsed_constraint(scene={"weather": "rain", "time": "night"}):
        high = (await client.post("/api/v1/search", json={"query": "a wet road at night", "top_k": 10})).json()
    assert high["matched"] is True and high["confidence"] == "high"
    assert not high["reason"]

    # low — q21 at 0.330 sits between the lines: answered, flagged, NOT hidden. It is also the
    # query that set tau_reject (0.330 - 0.035 ≈ 0.30), so this is the case the floor exists for.
    with parsed_constraint(objects=["pedestrian"], relations={"pedestrian": ["front_left"]}):
        low = (
            await client.post("/api/v1/search", json={"query": "a pedestrian to the front-left", "top_k": 10})
        ).json()
    assert low["matched"] is True and low["confidence"] == "low"
    assert len(low["results"]) == 10, "a marginal score must never withhold real results"
    assert low["reason"]

    # no_match — clearly absent, refused outright, and the archive is described
    with parsed_constraint():
        gone = (await client.post("/api/v1/search", json={"query": "a bus on fire"})).json()
    assert gone["matched"] is False and gone["confidence"] is None
    assert gone["results"] == []
    assert f"{corpus.provenance['n_frames']:,} keyframes" in gone["reason"]


ANN = "reviewer-ann"


class TestReviewEndpoints:
    """The human-in-the-loop contract: `PUT/GET/DELETE /reviews`, `/reviews/summary`, `/reviews/export`.

    These use the `corpus` fixture because `PUT` validates the frame against it — which also means
    they skip on a fresh clone rather than failing, like every other corpus-dependent test.
    """

    QUERY = "a bus at night"
    # Every call names a reviewer: one deployment serves every tester from one table, so an
    # unattributed verdict cannot be separated afterwards (`services/reviews.py`).

    @pytest.mark.asyncio
    async def test_a_verdict_is_recorded_and_comes_back_with_the_query(self, client, corpus, review_store):
        frame = corpus.frame_ids[0]
        put = await client.put(
            "/api/v1/reviews",
            json={"query": self.QUERY, "frame_id": frame, "reviewer": ANN, "decision": "approved", "note": "clear bus"},
        )
        assert put.status_code == 200
        assert put.json()["decision"] == "approved"

        listed = await client.get("/api/v1/reviews", params={"query": self.QUERY, "reviewer": ANN})
        assert [(r["frame_id"], r["note"]) for r in listed.json()] == [(frame, "clear bus")]

    @pytest.mark.asyncio
    async def test_verdicts_do_not_leak_between_queries(self, client, corpus, review_store):
        """The UI restores decisions per query; leaking would show a verdict from a different question."""
        frame = corpus.frame_ids[0]
        await client.put(
            "/api/v1/reviews", json={"query": "q1", "frame_id": frame, "reviewer": ANN, "decision": "approved"}
        )
        assert (await client.get("/api/v1/reviews", params={"query": "q2", "reviewer": ANN})).json() == []

    @pytest.mark.asyncio
    async def test_a_frame_the_archive_does_not_hold_is_refused(self, client, corpus, review_store):
        """An export is meant to be resolvable by someone else; a row pointing at nothing is not."""
        response = await client.put(
            "/api/v1/reviews",
            json={"query": self.QUERY, "frame_id": "0" * 32 + "_CAM_FRONT", "reviewer": ANN, "decision": "approved"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_an_unknown_verdict_is_a_validation_error(self, client, corpus, review_store):
        response = await client.put(
            "/api/v1/reviews",
            json={"query": self.QUERY, "frame_id": corpus.frame_ids[0], "reviewer": ANN, "decision": "probably"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_undo_is_idempotent(self, client, corpus, review_store):
        frame = corpus.frame_ids[0]
        await client.put(
            "/api/v1/reviews", json={"query": self.QUERY, "frame_id": frame, "reviewer": ANN, "decision": "approved"}
        )
        params = {"query": self.QUERY, "frame_id": frame, "reviewer": ANN}
        assert (await client.delete("/api/v1/reviews", params=params)).status_code == 204
        assert (await client.delete("/api/v1/reviews", params=params)).status_code == 204
        assert (await client.get("/api/v1/reviews", params={"query": self.QUERY, "reviewer": ANN})).json() == []

    @pytest.mark.asyncio
    async def test_summary_counts_what_has_been_judged(self, client, corpus, review_store, signed_in):
        await client.put(
            "/api/v1/reviews",
            json={"query": self.QUERY, "frame_id": corpus.frame_ids[0], "reviewer": ANN, "decision": "approved"},
        )
        await client.put(
            "/api/v1/reviews",
            json={"query": self.QUERY, "frame_id": corpus.frame_ids[1], "reviewer": ANN, "decision": "rejected"},
        )
        summary = (await client.get("/api/v1/reviews/summary")).json()
        assert (summary["approved"], summary["rejected"], summary["queries_reviewed"]) == (1, 1, 1)

    @pytest.mark.asyncio
    async def test_export_defaults_to_the_approved_set_and_downloads(self, client, corpus, review_store, signed_in):
        """Default `approved` is the dataset; rejections must not silently ride along into one."""
        await client.put(
            "/api/v1/reviews",
            json={"query": self.QUERY, "frame_id": corpus.frame_ids[0], "reviewer": ANN, "decision": "approved"},
        )
        await client.put(
            "/api/v1/reviews",
            json={"query": self.QUERY, "frame_id": corpus.frame_ids[1], "reviewer": ANN, "decision": "rejected"},
        )
        response = await client.get("/api/v1/reviews/export")
        assert response.status_code == 200
        assert "attachment; filename=" in response.headers["content-disposition"]

        payload = response.json()
        assert payload["count"] == 1
        assert payload["decisions"][0]["decision"] == "approved"
        # Provenance rides along, so the exported set records which corpus and encoder produced it.
        assert payload["corpus"]["encoder"] == corpus.provenance["encoder"]

    @pytest.mark.asyncio
    async def test_export_scope_mine_returns_only_this_accounts_rows(self, client, corpus, review_store, signed_in):
        """The complaint this answers: a new account opened the export on 61 rows from 14 strangers.

        Both scopes are real — `all` is the dataset the team built, `mine` is one person's work — and
        the fix was to offer the choice rather than to narrow the default, because the whole-table
        export is the deliverable the Brief describes.
        """
        review_store.put(ReviewKey(self.QUERY, corpus.frame_ids[0], f"user:{signed_in.user_id}"), "approved")
        review_store.put(ReviewKey(self.QUERY, corpus.frame_ids[1], "reviewer-bob"), "approved")

        everyone = (await client.get("/api/v1/reviews/export", params={"decision": "all"})).json()
        mine = (await client.get("/api/v1/reviews/export", params={"decision": "all", "scope": "mine"})).json()

        assert everyone["count"] == 2
        assert mine["count"] == 1
        assert {d["reviewer"] for d in mine["decisions"]} == {f"user:{signed_in.user_id}"}

    @pytest.mark.asyncio
    async def test_export_defaults_to_everyone_so_the_dataset_is_what_downloads(
        self, client, corpus, review_store, signed_in
    ):
        """Unchanged by the new parameter, and deliberately.

        On this corpus every verdict predates account attribution, so `mine` is empty for everyone —
        a default that showed nothing would read as a broken page rather than an honest one.
        """
        review_store.put(ReviewKey(self.QUERY, corpus.frame_ids[0], "reviewer-bob"), "approved")

        assert (await client.get("/api/v1/reviews/export")).json()["count"] == 1

    @pytest.mark.asyncio
    async def test_export_all_includes_rejections_and_csv_is_flat(self, client, corpus, review_store, signed_in):
        await client.put(
            "/api/v1/reviews",
            json={"query": self.QUERY, "frame_id": corpus.frame_ids[1], "reviewer": ANN, "decision": "rejected"},
        )
        response = await client.get("/api/v1/reviews/export", params={"format": "csv", "decision": "all"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        lines = response.text.strip().splitlines()
        assert lines[0].startswith("query,frame_id,reviewer,decision")
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_an_anonymous_verdict_is_required_to_name_its_reviewer(self, client, corpus, review_store):
        """400 rather than an anonymous row. One table serves every tester, so a verdict without an
        author cannot be separated from anyone else's after the session.

        400 and not 422 since the field became optional: whether it is required depends on whether
        the caller has a session, which Pydantic cannot see. A signed-in caller needs no id, and the
        test below is the other half of this one.
        """
        response = await client.put(
            "/api/v1/reviews",
            json={"query": self.QUERY, "frame_id": corpus.frame_ids[0], "decision": "approved"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_a_signed_in_verdict_is_filed_under_the_account(self, client, corpus, review_store, signed_in):
        """The account decides, and the browser id sent alongside it is ignored rather than merged.

        This is the fix for three accounts on one laptop sharing one `localStorage`, therefore one
        reviewer id, therefore one set of verdicts — each seeing the other two's ticks and crosses.
        """
        put = await client.put(
            "/api/v1/reviews",
            json={"query": self.QUERY, "frame_id": corpus.frame_ids[0], "reviewer": ANN, "decision": "approved"},
        )
        assert put.json()["reviewer"] == f"user:{signed_in.user_id}"
        # And the browser id it claimed holds nothing, so a second account on the same browser —
        # which sends this same id — sees an unjudged page.
        assert review_store.for_query(self.QUERY, ANN) == []

    @pytest.mark.asyncio
    async def test_an_anonymous_caller_cannot_claim_an_account(self, client, corpus, review_store):
        """The two id namespaces are both uuids, so the prefix is what keeps them apart.

        Without this, an anonymous caller could pass `user:<someone's id>` and file, read or delete
        verdicts as them — and `GET /reviews/export` publishes those ids by design.
        """
        response = await client.put(
            "/api/v1/reviews",
            json={
                "query": self.QUERY,
                "frame_id": corpus.frame_ids[0],
                "reviewer": "user:2e5c782b-83fa-4074-9a2f-4bf31bd58f26",
                "decision": "approved",
            },
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_one_testers_verdicts_are_invisible_to_another(self, client, corpus, review_store):
        """The contamination this change exists to stop: before it, the second tester opened a query
        already marked up by the first and judged against someone else's answers."""
        frame = corpus.frame_ids[0]
        await client.put(
            "/api/v1/reviews",
            json={"query": self.QUERY, "frame_id": frame, "reviewer": ANN, "decision": "approved"},
        )
        bob = await client.get("/api/v1/reviews", params={"query": self.QUERY, "reviewer": "reviewer-bob"})
        assert bob.json() == []

    @pytest.mark.asyncio
    async def test_two_testers_disagreeing_keeps_both_verdicts(self, client, corpus, review_store, signed_in):
        """Before, the second `PUT` destroyed the first through the primary key. Disagreement is the
        signal a multi-rater session is *for*, so losing it silently was the worst case.

        The two verdicts are seeded through the store rather than over HTTP because `signed_in`
        overrides the session for the whole test, so two `PUT`s would now both be filed under the
        one account — correctly. What is under test here is the export aggregating across reviewers,
        not who a verdict gets attributed to; `test_a_signed_in_verdict_is_filed_under_the_account`
        covers that.
        """
        frame = corpus.frame_ids[0]
        review_store.put(ReviewKey(self.QUERY, frame, ANN), "approved")
        review_store.put(ReviewKey(self.QUERY, frame, "reviewer-bob"), "rejected")

        payload = (await client.get("/api/v1/reviews/export", params={"decision": "all"})).json()
        assert payload["count"] == 2
        assert payload["reviewers"] == [ANN, "reviewer-bob"]

    @pytest.mark.asyncio
    async def test_summary_scopes_to_the_caller_but_counts_everyone(self, client, corpus, review_store, signed_in):
        """A tester sees their own progress; `reviewers` still evidences how many people took part.

        Seeded through the store for the reason given above — and the scoped read now asks for the
        *account's* progress, which is the whole point: sending a browser id no longer decides whose
        row is counted.
        """
        review_store.put(ReviewKey(self.QUERY, corpus.frame_ids[0], f"user:{signed_in.user_id}"), "approved")
        review_store.put(ReviewKey(self.QUERY, corpus.frame_ids[1], "reviewer-bob"), "approved")

        mine = (await client.get("/api/v1/reviews/summary", params={"reviewer": ANN})).json()
        everyone = (await client.get("/api/v1/reviews/summary")).json()
        assert (mine["total"], everyone["total"]) == (1, 2)
        assert mine["reviewers"] == 2

    @pytest.mark.asyncio
    async def test_two_accounts_on_one_browser_do_not_share_verdicts(self, client, corpus, review_store, signed_in):
        """The reported bug, end to end: three logins on one laptop looked like one reviewer.

        Both accounts send the same browser id, because `localStorage` belongs to the browser and
        survives a logout. Before the fix that id *was* the scope, so the second account opened a
        page already marked up by the first.
        """
        from types import SimpleNamespace
        from uuid import uuid4

        from src.api.auth_middleware import get_current_user
        from src.api.security import current_operator
        from src.main import app

        frame = corpus.frame_ids[0]
        await client.put(
            "/api/v1/reviews",
            json={"query": self.QUERY, "frame_id": frame, "reviewer": ANN, "decision": "approved"},
        )

        second = SimpleNamespace(user_id=uuid4(), email="other@test.local", role="User", status="active")
        app.dependency_overrides[get_current_user] = lambda: second
        app.dependency_overrides[current_operator] = lambda: second

        # Same browser, same claimed id, different account — and therefore an unjudged page.
        listed = await client.get("/api/v1/reviews", params={"query": self.QUERY, "reviewer": ANN})
        assert listed.json() == []
        # Nor can the second account undo the first's verdict by naming the id they share.
        params = {"query": self.QUERY, "frame_id": frame, "reviewer": ANN}
        assert (await client.delete("/api/v1/reviews", params=params)).status_code == 204
        assert review_store.for_query(self.QUERY, f"user:{signed_in.user_id}") != []
