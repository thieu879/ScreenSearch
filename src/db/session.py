"""SQLAlchemy engine and session factory for PostgreSQL.

Reads ``DATABASE_URL`` from ``src.config.Settings``.  The engine is created once at import time
(via ``lru_cache``) and reused for the lifetime of the process — the same pattern ``get_settings``
uses.

Sync SQLAlchemy + psycopg2, matching the existing codebase which runs sync route handlers in
FastAPI's threadpool.  Async (asyncpg) would be a marginal gain for a service whose bottleneck is
an LLM call per search, not database I/O.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_settings


@lru_cache(maxsize=1)
def get_engine():
    """Process-wide engine.  Cached so the pool is created once."""
    settings = get_settings()
    url = settings.database_url

    # SQLAlchemy needs the ``postgresql://`` scheme, but some tools emit
    # ``postgres://`` (e.g. Heroku).  Normalise silently.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    return create_engine(
        url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,  # reconnect on stale connections
        echo=False,
    )


SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=get_engine(),
    autocommit=False,
    autoflush=False,
)


def get_db():
    """FastAPI dependency — yields a session and closes it after the request.

    Usage::

        @router.get("/example")
        def example(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
