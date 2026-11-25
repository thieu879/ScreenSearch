"""OTP generation and storage service using Redis with 5-minute TTL (300 seconds).

Includes a transparent in-memory fallback store so that local testing or standalone
environments without an active Redis instance can still run reliably without crashing.
"""

from __future__ import annotations

import logging
import random
import time

from src.config import get_settings

logger = logging.getLogger(__name__)

# Fallback in-memory store: { key: (otp_code, expire_timestamp) }
_in_memory_otp_store: dict[str, tuple[str, float]] = {}


def _get_redis_client():
    """Attempt to get an active Redis client connection."""
    try:
        import redis

        settings = get_settings()
        if not settings.redis_url:
            return None
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2.0)
        client.ping()
        return client
    except Exception as exc:
        logger.debug("Redis connection unavailable, falling back to in-memory OTP store: %s", exc)
        return None


def generate_otp_code(length: int = 6) -> str:
    """Generate a random numeric OTP string of given length (default 6 digits)."""
    return "".join([str(random.randint(0, 9)) for _ in range(length)])


def store_otp(email: str, purpose: str, otp: str, ttl_seconds: int = 300) -> None:
    """Store an OTP code in Redis for given email and purpose with a 5-minute (300s) TTL.

    :param email: Target email address.
    :param purpose: Context ("register" or "forgot_password").
    :param otp: The 6-digit OTP string.
    :param ttl_seconds: Time to live in seconds (default 300 = 5 minutes).
    """
    key = f"otp:{purpose}:{email.lower().strip()}"
    client = _get_redis_client()

    if client:
        try:
            client.setex(key, ttl_seconds, otp)
            logger.info("Stored OTP in Redis for %s (purpose=%s, ttl=%ds)", email, purpose, ttl_seconds)
            return
        except Exception as exc:
            logger.warning("Failed to store OTP in Redis, using in-memory store: %s", exc)

    # In-memory fallback
    expire_time = time.time() + ttl_seconds
    _in_memory_otp_store[key] = (otp, expire_time)
    logger.info("Stored OTP in memory for %s (purpose=%s, ttl=%ds)", email, purpose, ttl_seconds)


def verify_otp(email: str, purpose: str, otp: str) -> bool:
    """Verify if the provided OTP matches the stored OTP for the email and purpose.

    Does NOT delete the OTP on check — call delete_otp on complete success.
    """
    key = f"otp:{purpose}:{email.lower().strip()}"
    client = _get_redis_client()
    stored_otp: str | None = None

    if client:
        try:
            val = client.get(key)
            if val:
                stored_otp = val.decode("utf-8") if isinstance(val, bytes) else str(val)
        except Exception as exc:
            logger.warning("Failed to read OTP from Redis, checking memory: %s", exc)

    if stored_otp is None:
        # Check in-memory fallback
        if key in _in_memory_otp_store:
            val, expire_time = _in_memory_otp_store[key]
            if time.time() <= expire_time:
                stored_otp = val
            else:
                del _in_memory_otp_store[key]  # Clean expired

    if not stored_otp:
        return False

    return stored_otp.strip() == otp.strip()


def delete_otp(email: str, purpose: str) -> None:
    """Remove the OTP from Redis and in-memory store after successful action."""
    key = f"otp:{purpose}:{email.lower().strip()}"
    client = _get_redis_client()

    if client:
        try:
            client.delete(key)
        except Exception:
            pass

    _in_memory_otp_store.pop(key, None)
