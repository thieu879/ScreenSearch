"""Seed initial admin and test accounts into the database.

Usage::

    python -m scripts.seed_admin

Creates two accounts if they do not already exist:
  admin@ssp.com / Admin@123  (Admin)
  user@ssp.com  / User@123   (User)

Safe to run multiple times — skips accounts whose email already exists.
"""

from __future__ import annotations

import logging
import sys

# Ensure the project root is on sys.path so `src` is importable.
sys.path.insert(0, ".")

from src.db.models import User
from src.db.session import SessionLocal
from src.services.auth import hash_password

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SEED_USERS = [
    {
        "email": "admin@ssp.com",
        "password": "Admin@123",
        "full_name": "System Administrator",
        "role": "Admin",
        "status": "active",
    },
    {
        "email": "user@ssp.com",
        "password": "User@123",
        "full_name": "Test User",
        "role": "User",
        "status": "active",
    },
]


def seed() -> None:
    db = SessionLocal()
    try:
        for data in SEED_USERS:
            existing = db.query(User).filter(User.email == data["email"]).first()
            if existing:
                logger.info("skip: %s already exists (role=%s)", data["email"], existing.role)
                continue

            user = User(
                email=data["email"],
                password_hash=hash_password(data["password"]),
                full_name=data["full_name"],
                role=data["role"],
                status=data["status"],
            )
            db.add(user)
            db.commit()
            logger.info("created: %s (role=%s)", data["email"], data["role"])

    finally:
        db.close()


if __name__ == "__main__":
    seed()
    print("OK - Seed accounts created successfully!")
