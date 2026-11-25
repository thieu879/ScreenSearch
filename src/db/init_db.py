"""Create all PostgreSQL tables defined in ``src.db.models``.

Run once to bootstrap the database::

    python -m src.db.init_db

Idempotent — ``CREATE TABLE IF NOT EXISTS`` semantics via SQLAlchemy's ``create_all``.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from src.db.models import Base
from src.db.session import get_engine

logger = logging.getLogger(__name__)


def init_db() -> None:
    """Create all ORM tables and apply idempotent migrations."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    # Migrate existing `users` table if columns are missing
    migrations = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(50) UNIQUE;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar TEXT;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active' NOT NULL;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();",
    ]
    with engine.begin() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
            except Exception as exc:
                logger.warning("migration notice for %r: %s", stmt, exc)

    logger.info(
        "tables created/migrated: %s",
        ", ".join(sorted(Base.metadata.tables.keys())),
    )


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    print("OK - Database initialized successfully!")
