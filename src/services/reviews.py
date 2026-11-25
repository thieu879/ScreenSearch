"""Human review of search results — the human-in-the-loop the Brief requires.

The product's claim is not "we find frames", it is "an engineer builds a test dataset from an
archive". Search alone cannot make that claim: `report.md` §2 measures relational lift at +0.290 and
`a wet road at night` at P@10 0.10, so **some** returned frames are wrong, always. What turns a
ranked list into a dataset is a person confirming it. This module stores those confirmations.

**The unit of review is `(query, frame_id, reviewer)`.** A frame is not good or bad in the abstract
— it is a positive *for a question someone asked*, judged *by someone*. `558a…_CAM_FRONT` can be a
correct hit for `driving at night` and a wrong one for `a cyclist at night` at the same time, and a
store keyed on frame alone would make the second decision silently overwrite the first. Keying on
the pair is also exactly the shape a retrieval test set needs: query → judged positives.

`reviewer` joined that key on 2026-08-08, before the first session, and it is not bookkeeping. The
deployment is one service over one database, so **every tester shares this table**. Without a
reviewer column two people judging the same frame for the same query collided on the primary key
and `INSERT OR REPLACE` destroyed the first verdict with no trace — and disagreement between raters
is the most informative thing a multi-rater session produces, so the schema was discarding its best
signal. `for_query` was also unfiltered, so the second tester saw the first one's ticks and crosses
painted on the cards before judging anything, which is contamination of the only evidence the
shipped corpus will ever have.

It is a **pseudonymous browser id, not a login**: enough to separate and attribute verdicts, and
deliberately not enough to identify a person. Nothing asks the tester for a name.

**Storage is stdlib `sqlite3`.** No new dependency, on the same reasoning `requirements.txt` gives
for refusing Chroma: a review set is thousands of short rows, and a service to hold them would add
deployment surface to do less. The database is a **working buffer, not the deliverable** — the
export is. That matters because the deployment target has an ephemeral filesystem: a container
restart loses the buffer, and the honest answer to that is that a reviewer exports when done, not
that we bolt on a managed database for a four-week project. `docs/api-contract.md` says so plainly
rather than letting a user discover it.

Decisions are last-write-wins per pair, so re-judging a frame corrects it instead of appending a
second opinion — an audit trail of one reviewer changing their mind is not information anyone here
needs, and `INSERT OR REPLACE` keeps the export unambiguous.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import NamedTuple

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc  # noqa: UP017

from src.config import get_settings

# What a reviewer can say about a frame. `bookmarked` is deliberately *not* a weaker `approved`:
# it means "come back to this", so export defaults to `approved` only and a bookmark never leaks
# into a dataset by accident.
DECISIONS = ("approved", "rejected", "bookmarked")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    query       TEXT NOT NULL,
    frame_id    TEXT NOT NULL,
    reviewer    TEXT NOT NULL,
    decision    TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL,
    PRIMARY KEY (query, frame_id, reviewer)
);
CREATE INDEX IF NOT EXISTS reviews_by_decision ON reviews (decision);
CREATE INDEX IF NOT EXISTS reviews_by_reviewer ON reviews (reviewer);
"""

# What pre-2026-08-08 rows are attributed to. A real id is a browser uuid, so this cannot collide
# with one, and it is greppable in an export: it marks verdicts recorded when the store could not
# say who made them, rather than silently implying they all came from one person.
LEGACY_REVIEWER = "unknown-pre-attribution"

# What marks a verdict as belonging to an account rather than to a browser. A browser id is a
# `crypto.randomUUID()` and a `user_id` is a uuid too, so without a prefix the two namespaces are
# the same strings and an anonymous caller could *claim* a signed-in engineer's id — reading, adding
# to, and deleting their verdicts. `reviewer_identity` refuses a claim carrying this prefix for
# exactly that reason.
ACCOUNT_PREFIX = "user:"


def reviewer_identity(claimed: str | None, account_id: str | None) -> str:
    """Who a review call is filed under: the account when there is one, the browser when there is not.

    **A browser id was the right answer, and login is what stopped it being one.** The pseudonymous
    id in `FE/src/lib/reviewer.ts` lives in `localStorage`, so it is per *browser profile*, not per
    person — which was precisely the point when the service had no accounts and nobody was ever
    asked for a name. Once every product route sat behind a login (2026-08-26), the same property
    became the defect: three accounts signed in on one laptop share one `localStorage`, therefore one
    reviewer id, therefore one set of verdicts. Each of the three sees the others' ticks and crosses
    — the contamination the `reviewer` column was added to prevent, arriving from the other side.

    Same shape as the `OPERATOR_TOKEN` retirement in `api/security.py`: a mechanism that was correct
    for a service without accounts, left running after the service got them.

    **A session decides; a claim does not.** When the caller has one, `claimed` is ignored rather
    than merged — `reviewer` is a plain request parameter, so trusting it would let anyone file,
    read or delete verdicts as anybody whose id they know, and `GET /reviews/export` publishes ids
    by design. An anonymous caller keeps its browser id, because the open review routes exist for a
    tester who reaches them from a link with no credential.

    Raises `ValueError` if there is neither a session nor a usable claim; the route turns that into
    a 400. Verdicts written before this existed keep their browser ids and are not rewritten — an id
    change is not a merge, and guessing which account a browser belonged to would invent attribution
    rather than recover it.
    """
    if account_id is not None:
        return f"{ACCOUNT_PREFIX}{account_id}"
    if not claimed:
        raise ValueError("A reviewer id is required when you are not signed in.")
    if claimed.startswith(ACCOUNT_PREFIX):
        raise ValueError(f"A reviewer id may not begin with {ACCOUNT_PREFIX!r} — that namespace is accounts.")
    return claimed


class ReviewKey(NamedTuple):
    """What identifies one verdict. A triple, and every part of it is load-bearing.

    Passed as one argument rather than three loose strings so a caller cannot omit `reviewer` and
    quietly write an unattributed row — which is the exact failure this key exists to prevent.
    """

    query: str
    frame_id: str
    reviewer: str


def _migrate(conn: sqlite3.Connection) -> None:
    """Add `reviewer` to a pre-2026-08-08 database, keeping every verdict already in it.

    The column cannot be added with `ALTER TABLE`, because the primary key changes with it, and
    sqlite cannot alter a key in place. So the table is rebuilt — which is also why this runs
    *before* `CREATE TABLE IF NOT EXISTS`: that statement would otherwise be a no-op against the old
    shape and leave the new key unenforced.

    Deliberately not a no-op-if-empty shortcut. A teammate's database may hold a session's work, and
    the cost of being wrong here is somebody's afternoon of judgements.
    """
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "reviews" not in tables:
        return
    columns = {r[1] for r in conn.execute("PRAGMA table_info(reviews)")}
    if "reviewer" in columns:
        return
    n = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    conn.executescript(_SCHEMA.replace("reviews", "reviews_new"))
    conn.execute(
        "INSERT INTO reviews_new (query, frame_id, reviewer, decision, note, reviewed_at)"
        " SELECT query, frame_id, ?, decision, note, reviewed_at FROM reviews",
        (LEGACY_REVIEWER,),
    )
    conn.execute("DROP TABLE reviews")
    conn.execute("ALTER TABLE reviews_new RENAME TO reviews")
    print(f"[reviews] migrated {n} row(s) to the reviewer-keyed schema, attributed to {LEGACY_REVIEWER!r}")


@dataclass(frozen=True)
class Review:
    """One reviewer decision about one frame, in the context of one query."""

    query: str
    frame_id: str
    reviewer: str
    decision: str
    note: str
    reviewed_at: str


class ReviewStore:
    """Thread-confined sqlite connections over one review database.

    A connection per thread, not one shared: FastAPI runs sync route handlers in a threadpool, and
    a sqlite3 connection used from a thread other than the one that created it raises. The
    alternative — `check_same_thread=False` plus a global lock — serialises every request behind
    one connection for no benefit at this size.
    """

    def __init__(self, path: str):
        self.path = path
        self._local = threading.local()
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        with self._connect() as conn:
            _migrate(conn)
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def put(self, key: ReviewKey, decision: str, note: str = "") -> Review:
        """Record or replace one decision. Returns what was stored, timestamp included."""
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}, got {decision!r}")
        if not key.reviewer:
            raise ValueError("reviewer is required; an unattributed verdict cannot be separated later")
        at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO reviews (query, frame_id, reviewer, decision, note, reviewed_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (*key, decision, note, at),
            )
        return Review(*key, decision, note, at)

    def clear(self, key: ReviewKey) -> bool:
        """Undo one decision. Returns whether there was anything to undo.

        Scoped to the reviewer: one tester's undo must not reach into another's verdicts, which on a
        shared deployment is a thing a stray click could otherwise do.
        """
        with self._connect() as conn:
            return (
                conn.execute(
                    "DELETE FROM reviews WHERE query = ? AND frame_id = ? AND reviewer = ?", tuple(key)
                ).rowcount
                > 0
            )

    def for_query(self, query: str, reviewer: str) -> list[Review]:
        """One reviewer's decisions for one query — what the UI restores on a repeat search.

        Filtered by reviewer on purpose. Returning everyone's verdicts is what showed the second
        tester the first tester's answers, and a judgement made after seeing someone else's is not
        the independent evidence the feedback window exists to collect.
        """
        rows = self._connect().execute(
            "SELECT * FROM reviews WHERE query = ? AND reviewer = ? ORDER BY reviewed_at",
            (query, reviewer),
        )
        return [Review(**dict(r)) for r in rows]

    def all(self, decision: str | None = None, reviewer: str | None = None) -> list[Review]:
        """Every decision, newest last. `decision` filters to one verdict, e.g. the export default.

        `reviewer` narrows it to one person's work. **Both scopes are real products and the caller
        picks**: the whole table is the dataset the team built, which is what makes disagreement
        between raters visible and is the deliverable the Brief describes; one reviewer's own rows
        are what an engineer means by "export what I did". Offering only the first made a new
        account's export open on 61 rows from fourteen strangers, with no way to find its own.
        """
        clauses, args = [], []
        if decision:
            clauses.append("decision = ?")
            args.append(decision)
        if reviewer:
            clauses.append("reviewer = ?")
            args.append(reviewer)
        sql = "SELECT * FROM reviews"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return [Review(**dict(r)) for r in self._connect().execute(sql + " ORDER BY reviewed_at", tuple(args))]

    def summary(self, reviewer: str | None = None) -> dict:
        """Counts per decision plus distinct queries reviewed — the header badge, and §9's evidence.

        `reviewer` scopes it to one person, which is what a tester's own progress bar should show:
        a count including everyone else's work anchors the next judgement, and the count is the one
        piece of shared state a tester sees constantly. Omitted, it totals the whole table, which is
        what the operator wants when deciding whether a session produced enough to export.
        """
        where, args = ("", ())
        if reviewer is not None:
            where, args = (" WHERE reviewer = ?", (reviewer,))
        rows = self._connect().execute(f"SELECT decision, COUNT(*) n FROM reviews{where} GROUP BY decision", args)
        counts = {d: 0 for d in DECISIONS}
        counts.update({r["decision"]: r["n"] for r in rows})
        queries = self._connect().execute(f"SELECT COUNT(DISTINCT query) n FROM reviews{where}", args).fetchone()["n"]
        return {**counts, "queries_reviewed": queries, "total": sum(counts.values())}

    def reviewers(self) -> list[str]:
        """Who has judged anything. The evidence that "3-5 people" happened, which no count can give."""
        return [
            r[0]
            for r in self._connect().execute("SELECT reviewer FROM reviews GROUP BY reviewer ORDER BY COUNT(*) DESC")
        ]


class PostgresReviewStore:
    """PostgreSQL-backed review store using `DATABASE_URL` (`public.reviews`)."""

    _SCHEMA_PG = """
    ALTER TABLE public.reviews ADD COLUMN IF NOT EXISTS query TEXT;
    ALTER TABLE public.reviews ADD COLUMN IF NOT EXISTS reviewer TEXT;
    ALTER TABLE public.reviews ADD COLUMN IF NOT EXISTS decision TEXT;
    ALTER TABLE public.reviews ADD COLUMN IF NOT EXISTS note TEXT NOT NULL DEFAULT '';
    ALTER TABLE public.reviews ADD COLUMN IF NOT EXISTS reviewed_at TEXT;
    CREATE UNIQUE INDEX IF NOT EXISTS ix_reviews_query_frame_reviewer
        ON public.reviews (query, frame_id, reviewer);
    """

    def __init__(self, database_url: str):
        self.path = database_url
        if self.path.startswith("postgres://"):
            self.path = self.path.replace("postgres://", "postgresql://", 1)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(self._SCHEMA_PG)

    def _conn(self):
        import psycopg2

        return psycopg2.connect(self.path, connect_timeout=15)

    def put(self, key: ReviewKey, decision: str, note: str = "") -> Review:
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}, got {decision!r}")
        if not key.reviewer:
            raise ValueError("reviewer is required; an unattributed verdict cannot be separated later")
        import uuid

        at = datetime.now(UTC).isoformat(timespec="seconds")
        user_uuid = None
        if key.reviewer.startswith(ACCOUNT_PREFIX):
            try:
                user_uuid = str(uuid.UUID(key.reviewer.removeprefix(ACCOUNT_PREFIX)))
            except ValueError:
                user_uuid = None

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.reviews (review_id, user_id, search_id, frame_id, verdict, notes, query, reviewer, decision, note, reviewed_at)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                    ON CONFLICT (query, frame_id, reviewer) DO UPDATE
                       SET decision = EXCLUDED.decision,
                           verdict = EXCLUDED.verdict,
                           note = EXCLUDED.note,
                           notes = EXCLUDED.notes,
                           reviewed_at = EXCLUDED.reviewed_at
                    """,
                    (
                        str(uuid.uuid4()),
                        user_uuid,
                        key.query,
                        key.frame_id,
                        decision.upper(),
                        "{}",
                        key.query,
                        key.reviewer,
                        decision,
                        note,
                        at,
                    ),
                )
        return Review(*key, decision, note, at)

    def clear(self, key: ReviewKey) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM public.reviews WHERE query = %s AND frame_id = %s AND reviewer = %s",
                    tuple(key),
                )
                return cur.rowcount > 0

    def for_query(self, query: str, reviewer: str) -> list[Review]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT query, frame_id, reviewer, decision, COALESCE(note, ''), COALESCE(reviewed_at, '')
                    FROM public.reviews
                    WHERE query = %s AND reviewer = %s AND query IS NOT NULL
                    ORDER BY reviewed_at
                    """,
                    (query, reviewer),
                )
                return [Review(*r) for r in cur.fetchall()]

    def all(self, decision: str | None = None, reviewer: str | None = None) -> list[Review]:
        clauses = ["query IS NOT NULL", "decision IS NOT NULL"]
        args: list[str] = []
        if decision:
            clauses.append("decision = %s")
            args.append(decision)
        if reviewer:
            clauses.append("reviewer = %s")
            args.append(reviewer)
        sql = (
            "SELECT query, frame_id, reviewer, decision, COALESCE(note, ''), COALESCE(reviewed_at, '') "
            "FROM public.reviews WHERE " + " AND ".join(clauses) + " ORDER BY reviewed_at"
        )
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(args))
                return [Review(*r) for r in cur.fetchall()]

    def summary(self, reviewer: str | None = None) -> dict:
        where = " WHERE query IS NOT NULL AND decision IS NOT NULL"
        args: tuple = ()
        if reviewer is not None:
            where += " AND reviewer = %s"
            args = (reviewer,)
        counts = {d: 0 for d in DECISIONS}
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT decision, COUNT(*) FROM public.reviews{where} GROUP BY decision", args)
                for dec, cnt in cur.fetchall():
                    if dec in counts:
                        counts[dec] = int(cnt)
                cur.execute(f"SELECT COUNT(DISTINCT query) FROM public.reviews{where}", args)
                queries = int(cur.fetchone()[0] or 0)
        return {**counts, "queries_reviewed": queries, "total": sum(counts.values())}

    def reviewers(self) -> list[str]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT reviewer FROM public.reviews WHERE reviewer IS NOT NULL GROUP BY reviewer ORDER BY COUNT(*) DESC"
                )
                return [r[0] for r in cur.fetchall()]


@lru_cache(maxsize=1)
def get_store() -> ReviewStore | PostgresReviewStore:
    """Process-wide store. Cached so the schema check and directory creation happen once.

    Uses PostgreSQL (`DATABASE_URL`) when `review_db == "database"` (or starts with `postgres`),
    otherwise uses the local sqlite path in `settings.review_db`.
    """
    settings = get_settings()
    target = settings.review_db.strip()
    if target == "database" or target.startswith(("postgresql://", "postgres://")):
        url = settings.database_url if target == "database" else target
        return PostgresReviewStore(url)
    return ReviewStore(target)
