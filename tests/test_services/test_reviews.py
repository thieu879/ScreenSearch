"""The review store and the export it feeds — the human-in-the-loop the Brief requires.

What these are really guarding is the composite key. A store keyed on `frame_id` alone would pass
almost every obvious test and then silently destroy a reviewer's work the moment they judged the
same frame for a second query, which is normal use rather than an edge case.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import zipfile

import pytest

from src.services import export
from src.services.reviews import (
    ACCOUNT_PREFIX,
    DECISIONS,
    LEGACY_REVIEWER,
    Review,
    ReviewKey,
    ReviewStore,
    reviewer_identity,
)

# The reviewer these tests speak as. Most of them predate attribution and are about the (query,
# frame_id) half of the key, so they use one id throughout; the tests that are *about* attribution
# name two explicitly.
REVIEWER = "reviewer-a"


def key(query: str, frame_id: str, reviewer: str = REVIEWER) -> ReviewKey:
    """Terse key builder — the tests are about verdicts, not about constructing tuples."""
    return ReviewKey(query, frame_id, reviewer)


class FakeCorpus:
    """Just the three attributes `export` reads. The real Corpus needs 6,858 frames of artifacts."""

    provenance = {"encoder": "openclip:ViT-B-16-SigLIP2:webli", "n_frames": 6858}
    scene_of = {"f1": "scene-a", "f2": "scene-b"}
    timestamp_of = {"f1": 0.5, "f2": 12.0}


@pytest.fixture
def store(tmp_path) -> ReviewStore:
    return ReviewStore(str(tmp_path / "reviews.db"))


class TestReviewStore:
    def test_records_and_reads_back_a_verdict(self, store):
        stored = store.put(key("a bus at night", "f1"), "approved", "clear bus")
        assert (stored.decision, stored.note) == ("approved", "clear bus")
        assert stored.reviewed_at.endswith("+00:00")
        assert [(r.frame_id, r.decision) for r in store.for_query("a bus at night", REVIEWER)] == [("f1", "approved")]

    def test_re_deciding_replaces_rather_than_appends(self, store):
        store.put(key("q", "f1"), "approved")
        store.put(key("q", "f1"), "rejected", "on reflection, a truck")
        assert [(r.decision, r.note) for r in store.for_query("q", REVIEWER)] == [
            ("rejected", "on reflection, a truck")
        ]

    def test_the_same_frame_holds_a_different_verdict_per_query(self, store):
        """The whole reason the key is a pair. Keyed on frame alone, the second call would win both."""
        store.put(key("driving at night", "f1"), "approved")
        store.put(key("a cyclist at night", "f1"), "rejected")
        assert [r.decision for r in store.for_query("driving at night", REVIEWER)] == ["approved"]
        assert [r.decision for r in store.for_query("a cyclist at night", REVIEWER)] == ["rejected"]

    def test_clear_is_idempotent_and_says_whether_it_did_anything(self, store):
        store.put(key("q", "f1"), "approved")
        assert store.clear(key("q", "f1")) is True
        assert store.clear(key("q", "f1")) is False
        assert store.for_query("q", REVIEWER) == []

    def test_clearing_one_verdict_leaves_the_other_query_alone(self, store):
        store.put(key("q1", "f1"), "approved")
        store.put(key("q2", "f1"), "approved")
        store.clear(key("q1", "f1"))
        assert [r.query for r in store.all()] == ["q2"]

    def test_all_filters_to_one_verdict(self, store):
        store.put(key("q", "f1"), "approved")
        store.put(key("q", "f2"), "rejected")
        assert [r.frame_id for r in store.all("approved")] == ["f1"]
        assert len(store.all()) == 2

    def test_summary_counts_every_decision_including_the_zeroes(self, store):
        store.put(key("q1", "f1"), "approved")
        store.put(key("q1", "f2"), "approved")
        store.put(key("q2", "f1"), "rejected")
        assert store.summary() == {
            "approved": 2,
            "rejected": 1,
            "bookmarked": 0,
            "queries_reviewed": 2,
            "total": 3,
        }

    def test_an_unknown_verdict_is_refused(self, store):
        """The API validates too, but the store is also reachable from scripts."""
        with pytest.raises(ValueError, match="decision must be one of"):
            store.put(key("q", "f1"), "probably")

    def test_a_reopened_store_still_has_the_rows(self, tmp_path):
        """`CREATE TABLE IF NOT EXISTS` must not be a truncate — that would lose a session's work."""
        path = str(tmp_path / "reviews.db")
        ReviewStore(path).put(key("q", "f1"), "approved")
        assert len(ReviewStore(path).all()) == 1


class TestReviewerIsolation:
    """The reason `reviewer` joined the key, 2026-08-08.

    One deployment serves every tester from one table. Each of these describes something that was
    silently true before, and would be true again if the reviewer were dropped from the key.
    """

    def test_two_reviewers_judging_the_same_frame_both_survive(self, store):
        """Before: the second `INSERT OR REPLACE` destroyed the first without trace — and
        disagreement between raters is the most informative thing a multi-rater session produces."""
        store.put(key("a bus at night", "f1", "ann"), "approved")
        store.put(key("a bus at night", "f1", "bob"), "rejected")
        assert sorted((r.reviewer, r.decision) for r in store.all()) == [
            ("ann", "approved"),
            ("bob", "rejected"),
        ]

    def test_a_reviewer_only_sees_their_own_verdicts(self, store):
        """Before: a tester opened a query already marked up by the previous tester, and a judgement
        made after seeing someone else's is not the independent evidence the sessions collect."""
        store.put(key("q", "f1", "ann"), "approved")
        store.put(key("q", "f2", "bob"), "rejected")
        assert [r.frame_id for r in store.for_query("q", "ann")] == ["f1"]
        assert [r.frame_id for r in store.for_query("q", "bob")] == ["f2"]

    def test_one_reviewers_undo_cannot_reach_anothers_verdict(self, store):
        store.put(key("q", "f1", "ann"), "approved")
        assert store.clear(key("q", "f1", "bob")) is False
        assert [r.reviewer for r in store.all()] == ["ann"]

    def test_re_deciding_still_replaces_for_the_same_reviewer(self, store):
        """Attribution must not turn one person's correction into a second opinion."""
        store.put(key("q", "f1", "ann"), "approved")
        store.put(key("q", "f1", "ann"), "rejected")
        assert [r.decision for r in store.all()] == ["rejected"]

    def test_summary_scopes_to_one_reviewer_but_totals_without_one(self, store):
        store.put(key("q", "f1", "ann"), "approved")
        store.put(key("q", "f2", "bob"), "approved")
        assert store.summary("ann")["total"] == 1
        assert store.summary()["total"] == 2

    def test_reviewers_lists_who_judged_most_first(self, store):
        """A count of verdicts cannot evidence "3-5 people". This can."""
        store.put(key("q", "f1", "ann"), "approved")
        store.put(key("q", "f2", "ann"), "approved")
        store.put(key("q", "f1", "bob"), "approved")
        assert store.reviewers() == ["ann", "bob"]

    def test_an_unattributed_verdict_is_refused(self, store):
        """Fail loudly rather than write a row nobody can separate out afterwards."""
        with pytest.raises(ValueError, match="reviewer is required"):
            store.put(key("q", "f1", ""), "approved")


class TestMigration:
    """A teammate's database may already hold a session's work. Losing it is not acceptable."""

    @staticmethod
    def _old_schema_db(path: str) -> None:
        """The pre-2026-08-08 table, with one row in it."""
        conn = sqlite3.connect(path)
        with conn:
            conn.execute(
                "CREATE TABLE reviews (query TEXT NOT NULL, frame_id TEXT NOT NULL,"
                " decision TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', reviewed_at TEXT NOT NULL,"
                " PRIMARY KEY (query, frame_id))"
            )
            conn.execute(
                "INSERT INTO reviews VALUES ('a bus at night', 'f1', 'approved', 'kept', '2026-08-07T17:02:25+00:00')"
            )
        conn.close()

    def test_existing_rows_survive_and_are_marked_unattributed(self, tmp_path):
        path = str(tmp_path / "reviews.db")
        self._old_schema_db(path)
        rows = ReviewStore(path).all()
        assert [(r.frame_id, r.decision, r.note, r.reviewer) for r in rows] == [
            ("f1", "approved", "kept", LEGACY_REVIEWER)
        ]

    def test_the_new_key_is_enforced_after_migrating(self, tmp_path):
        """The migration must rebuild the table rather than bolt a column on: `CREATE TABLE IF NOT
        EXISTS` against the old shape is a no-op and would leave the old primary key in force."""
        path = str(tmp_path / "reviews.db")
        self._old_schema_db(path)
        store = ReviewStore(path)
        store.put(key("a bus at night", "f1", "ann"), "rejected")
        assert len(store.all()) == 2  # the legacy row and ann's, neither overwriting the other

    def test_migrating_twice_is_a_no_op(self, tmp_path):
        path = str(tmp_path / "reviews.db")
        self._old_schema_db(path)
        ReviewStore(path)
        assert len(ReviewStore(path).all()) == 1


class TestStoreConfiguration:
    """Regression: every verdict 500'd on a real server while this suite was green.

    The store originally derived its path from `settings.database_url`, which `.env` carries as the
    template's `postgresql://user:password@localhost:5432/dbname` placeholder — so it refused to
    open, and the review feature was dead outside the tests. The fixture that made the suite pass is
    exactly what hid it: overriding a setting cannot exercise the value a deployment reads.

    So this asserts the *wiring*, with no fixture in sight.
    """

    def test_the_store_ignores_the_unused_template_database_url(self, tmp_path, monkeypatch):
        from src.config import get_settings
        from src.services import reviews

        monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost:5432/dbname")
        monkeypatch.setenv("REVIEW_DB", str(tmp_path / "reviews.db"))
        get_settings.cache_clear()
        reviews.get_store.cache_clear()
        try:
            store = reviews.get_store()
            store.put(key("q", "f1"), "approved")
            assert len(store.all()) == 1
        finally:
            get_settings.cache_clear()
            reviews.get_store.cache_clear()

    def test_the_default_path_is_a_plain_file_not_a_url(self):
        """A URL invites pointing this at a server there is no driver for — the original bug."""
        from src.config import Settings

        assert "://" not in Settings().review_db

    def test_a_missing_parent_directory_is_created_rather_than_raising(self, tmp_path):
        """First run on a fresh checkout has no `data/`, and that must not be an error."""
        store = ReviewStore(str(tmp_path / "nested" / "deeper" / "reviews.db"))
        store.put(key("q", "f1"), "approved")
        assert len(store.all()) == 1


class TestExport:
    REVIEWS = [
        Review("a bus at night", "f1", REVIEWER, "approved", "", "2026-08-02T12:00:00+00:00"),
        Review("a bus at night", "f2", REVIEWER, "approved", "second one", "2026-08-02T12:01:00+00:00"),
    ]

    def test_json_carries_the_corpus_provenance(self):
        """A list of frame ids is not a dataset unless it says which archive it indexes."""
        payload = json.loads(export.to_json(self.REVIEWS, FakeCorpus()))
        assert payload["corpus"]["encoder"] == "openclip:ViT-B-16-SigLIP2:webli"
        assert payload["count"] == 2

    def test_rows_carry_the_locators_that_make_a_frame_findable(self):
        row = json.loads(export.to_json(self.REVIEWS, FakeCorpus()))["decisions"][1]
        assert (row["scene_id"], row["timestamp_s"]) == ("scene-b", 12.0)

    def test_a_frame_missing_from_the_corpus_is_kept_with_empty_locators(self):
        """It means the corpus was re-ingested under the review set. Dropping the row hides that."""
        orphan = [Review("q", "gone", REVIEWER, "approved", "", "2026-08-02T12:00:00+00:00")]
        row = json.loads(export.to_json(orphan, FakeCorpus()))["decisions"][0]
        assert row["frame_id"] == "gone"
        assert (row["scene_id"], row["timestamp_s"]) == ("", "")

    def test_csv_has_the_documented_header_and_one_row_per_verdict(self):
        rows = list(csv.reader(io.StringIO(export.to_csv(self.REVIEWS, FakeCorpus()))))
        assert tuple(rows[0]) == export.COLUMNS
        assert [r[1] for r in rows[1:]] == ["f1", "f2"]

    def test_csv_quotes_a_note_containing_a_comma(self):
        """Reviewer notes are free text; an unquoted comma shifts every later column silently."""
        review = [Review("q", "f1", REVIEWER, "rejected", "no bus, a truck", "2026-08-02T12:00:00+00:00")]
        rows = list(csv.reader(io.StringIO(export.to_csv(review, FakeCorpus()))))
        # By name, not by position: inserting `reviewer` moved this column and a positional index
        # asserted the wrong cell was right.
        assert rows[1][export.COLUMNS.index("note")] == "no bus, a truck"

    def test_filename_says_what_is_in_it(self):
        assert export.filename("approved", "json").startswith("scenesearch-approved-")
        assert export.filename(None, "csv").startswith("scenesearch-all-")

    def test_every_decision_value_is_exportable(self):
        """Guards the store's vocabulary and the export staying in step."""
        reviews = [Review("q", f"f{i}", REVIEWER, d, "", "2026-08-02T12:00:00+00:00") for i, d in enumerate(DECISIONS)]
        assert json.loads(export.to_json(reviews, FakeCorpus()))["count"] == len(DECISIONS)

    def test_zip_packages_manifest_and_frame_images(self, tmp_path):
        """ZIP export packs the JSON manifest and all available matching JPEG thumbnails."""
        thumbs = tmp_path / "thumbs"
        thumbs.mkdir()
        (thumbs / "f1.jpg").write_bytes(b"dummy-image-f1")

        zip_bytes = export.to_zip(self.REVIEWS, FakeCorpus(), str(thumbs))
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            assert "manifest.json" in zf.namelist()
            assert "images/f1.jpg" in zf.namelist()
            assert zf.read("images/f1.jpg") == b"dummy-image-f1"
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            assert manifest["count"] == 2


class TestReviewerIdentity:
    """Who a verdict is filed under — the rule that replaced "whatever the client said".

    The store was always scoped correctly; what was wrong was the *scope*. A browser id lives in
    `localStorage`, so it belongs to a browser profile rather than to a person, and once every
    product route sat behind a login three accounts on one laptop became one reviewer — each seeing
    the others' verdicts, which is the contamination the `reviewer` column exists to prevent.
    """

    ACCOUNT = "2e5c782b-83fa-4074-9a2f-4bf31bd58f26"

    def test_a_session_decides_and_a_claim_is_ignored(self):
        """Not merged, not preferred — ignored. `reviewer` is a plain request field, so honouring it
        for a signed-in caller would let anyone file verdicts as anybody whose id they know."""
        assert reviewer_identity("browser-uuid", self.ACCOUNT) == f"user:{self.ACCOUNT}"
        assert reviewer_identity(None, self.ACCOUNT) == f"user:{self.ACCOUNT}"

    def test_an_anonymous_caller_keeps_its_browser_id(self):
        """The open review routes exist for a tester reaching them from a link with no credential."""
        assert reviewer_identity("browser-uuid", None) == "browser-uuid"

    def test_an_anonymous_caller_with_no_claim_is_refused(self):
        """Rather than an unattributed row, which cannot be separated from anyone else's afterwards."""
        for claimed in (None, ""):
            with pytest.raises(ValueError):
                reviewer_identity(claimed, None)

    def test_an_anonymous_caller_cannot_claim_the_account_namespace(self):
        """Both id spaces are uuids, so the prefix is the only thing keeping them apart — and the
        export publishes account ids by design, which is where an impersonator would get one."""
        with pytest.raises(ValueError):
            reviewer_identity(f"{ACCOUNT_PREFIX}{self.ACCOUNT}", None)

    def test_an_account_id_is_distinguishable_in_an_export(self):
        """A row's attribution says which kind of identity produced it, without a second column."""
        assert reviewer_identity(None, self.ACCOUNT).startswith(ACCOUNT_PREFIX)
        assert not reviewer_identity("browser-uuid", None).startswith(ACCOUNT_PREFIX)
