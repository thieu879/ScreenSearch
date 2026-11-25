"""SQLAlchemy ORM models for the PostgreSQL tables.

Schema follows the user's specification:
- ``users``              — account management (Admin / User roles)
- ``frames``             — keyframe data + AI vectors + detection metadata
- ``reviews``            — human-in-the-loop quality verdicts
- ``search_history``     — a signed-in engineer's recent searches, so their work follows the account
- ``ingest_provenance``  — AI model version tracking

Vector columns (``image_vector``, ``caption_vector``) are stored as ``REAL[]`` (PostgreSQL
native float arrays).  This avoids requiring the ``pgvector`` server extension while the
project already performs similarity search via numpy in memory.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    ARRAY,
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all models."""

    pass


# ---------------------------------------------------------------------------
# 1. users
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="User",
        comment="Admin or User",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        comment="active, disabled, or banned",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # relationships
    reviews: Mapped[list[Review]] = relationship(back_populates="user")
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    search_history: Mapped[list[SearchHistoryEntry]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# 1b. refresh_tokens
# ---------------------------------------------------------------------------


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # relationships
    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    __table_args__ = (
        Index("ix_refresh_tokens_user", "user_id"),
        Index("ix_refresh_tokens_hash", "token_hash"),
    )


# ---------------------------------------------------------------------------
# 2. frames
# ---------------------------------------------------------------------------


class Frame(Base):
    __tablename__ = "frames"

    frame_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    frame_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp_sec: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Vectors stored as REAL[] — native PostgreSQL float arrays, no pgvector extension needed.
    # 768-d for SigLIP2 image embeddings, 384-d for MiniLM caption embeddings.
    image_vector = mapped_column(ARRAY(Float), nullable=True, comment="SigLIP2 image embedding (768-d)")
    caption_vector = mapped_column(ARRAY(Float), nullable=True, comment="MiniLM caption embedding (384-d)")

    detection_metadata = mapped_column(
        JSONB,
        nullable=True,
        comment="Detected objects: bounding boxes, 3D positions, labels (car, person), scene tags",
    )
    captions = mapped_column(
        JSONB,
        nullable=True,
        comment="Florence-2 scene descriptions + Vietnamese translations",
    )

    # relationships
    reviews: Mapped[list[Review]] = relationship(back_populates="frame")

    __table_args__ = (Index("ix_frames_timestamp", "timestamp_sec"),)


# ---------------------------------------------------------------------------
# 3. reviews
# ---------------------------------------------------------------------------


class Review(Base):
    __tablename__ = "reviews"

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )
    search_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    frame_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("frames.frame_id"),
        nullable=True,
    )
    verdict: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="EXACT, RELEVANT, or WRONG",
    )
    notes = mapped_column(
        JSONB,
        nullable=True,
        comment="Reviewer notes on why a result was wrong, e.g. wrong car color",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # relationships
    user: Mapped[User | None] = relationship(back_populates="reviews")
    frame: Mapped[Frame | None] = relationship(back_populates="reviews")

    __table_args__ = (
        Index("ix_reviews_verdict", "verdict"),
        Index("ix_reviews_user", "user_id"),
    )


# ---------------------------------------------------------------------------
# 3b. search_history
# ---------------------------------------------------------------------------


class SearchHistoryEntry(Base):
    """One search a signed-in engineer ran, kept so their work follows the account.

    **Here rather than in `localStorage`, which is where it used to live** *(2026-08-30)*. Browser
    storage belongs to a browser profile, so it was invisible on a second machine and shared by
    every account signing in on one laptop — the same defect as the reviewer id, in the half of the
    product that never reached the server.

    **Here rather than in the sqlite review store**, which is the other obvious home. That store is
    a working buffer whose deliverable is the export (`services/reviews.py`); this is account data,
    and the account rows are already in PostgreSQL, so the foreign key is real and a deleted user
    takes their history with them. It also needs no migration: `init_db` runs `create_all` on every
    boot, so the table appears on a deployed box without a manual step.

    Trimmed to the most recent `HISTORY_LIMIT` per user on write (`services/history.py`) — a
    convenience list, not a record, so it is bounded rather than archival.
    """

    __tablename__ = "search_history"

    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # Cascade so deleting an account removes its history rather than orphaning rows that name a
        # user who no longer exists.
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    keyword: Mapped[str] = mapped_column(String(500), nullable=False)
    filters = mapped_column(
        # `JSONB` is PostgreSQL-only and will not compile against sqlite, so the variant is declared
        # rather than left to fail at table-creation time. It is what lets this table be exercised in
        # a test without a server — and a test that needs Supabase in order to read back a list of
        # five strings is testing the network. Postgres still gets real `JSONB`.
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=True,
        comment="Filter labels shown alongside the query, as a list of strings",
    )
    results_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="How many hits the search returned — what makes a repeat worth or not worth running",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        # Set here rather than by `server_default=func.now()`, which every other table uses, because
        # this column *orders* the list rather than merely recording when a row appeared. A database
        # clock gives whole seconds on sqlite and one transaction-start instant on PostgreSQL, so
        # rows written close together tie — and the tiebreaker would then be a random uuid, i.e. an
        # arbitrary answer to "which search was most recent". A Python timestamp is microsecond
        # resolution and identical on both engines.
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="search_history")

    __table_args__ = (
        # Every read is "this user's rows, newest first", which is exactly this index.
        Index("ix_search_history_user_recent", "user_id", "created_at"),
    )


# ---------------------------------------------------------------------------
# 4. ingest_provenance
# ---------------------------------------------------------------------------


class IngestProvenance(Base):
    __tablename__ = "ingest_provenance"

    version_id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        comment="Pipeline version, e.g. v1.0-siglip2-florence2",
    )
    config = mapped_column(
        JSONB,
        nullable=True,
        comment="AI model parameters and names used in this pipeline version",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Whether this is the currently active pipeline version",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
