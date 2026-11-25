"""Authentication and authorization dependencies for FastAPI routes.

``get_current_user`` reads the access token from the ``access_token`` HttpOnly cookie,
verifies it, and loads the user from the database.  ``require_role`` is a dependency
factory that restricts an endpoint to one or more roles.

CSRF protection: state-changing methods (POST/PUT/PATCH/DELETE) require a matching
``X-CSRF-Token`` header whose value equals the ``csrf_token`` cookie.  The CSRF cookie
is *not* HttpOnly so JavaScript can read it; the access/refresh cookies *are* HttpOnly
so JavaScript cannot.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from src.db.models import User
from src.db.session import get_db
from src.services.auth import decode_token

# ---------------------------------------------------------------------------
# Current user dependency
# ---------------------------------------------------------------------------


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Read the access token from the cookie, verify it, and return the user."""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập.")

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Token không hợp lệ.")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Token không hợp lệ.")

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=401, detail="Token không hợp lệ.")

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Người dùng không tồn tại.")
    if user.status != "active":
        raise HTTPException(status_code=401, detail="Tài khoản đã bị vô hiệu hóa.")

    return user


# ---------------------------------------------------------------------------
# Role-based authorization
# ---------------------------------------------------------------------------


def require_role(*allowed_roles: str) -> Callable:
    """Return a FastAPI dependency that checks the current user has one of the given roles.

    Usage::

        @router.get("/admin-only", dependencies=[Depends(require_role("Admin"))])
        def admin_endpoint(): ...

    Or inject the user::

        @router.get("/admin-only")
        def admin_endpoint(user: User = Depends(require_role("Admin"))): ...
    """

    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Không có quyền truy cập.")
        return user

    return _check


# Convenience aliases
require_auth = get_current_user
require_admin = require_role("Admin")


# ---------------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------------


def verify_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None),
) -> None:
    """Check that the CSRF header matches the CSRF cookie for state-changing methods.

    GET and HEAD are safe methods and are exempt.  The CSRF cookie is set by the login
    endpoint and is readable by JavaScript (not HttpOnly).
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    csrf_cookie = request.cookies.get("csrf_token")
    if not csrf_cookie or not x_csrf_token:
        raise HTTPException(status_code=403, detail="CSRF token thiếu.")

    if not secrets.compare_digest(csrf_cookie, x_csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token không hợp lệ.")


def generate_csrf_token() -> str:
    """Generate a random CSRF token."""
    return secrets.token_urlsafe(32)
