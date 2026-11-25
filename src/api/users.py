"""User profile endpoints: view, update, change password.

All endpoints require authentication.  Users can only access their own profile — the ``me``
pattern avoids any chance of one user modifying another's data by guessing a UUID.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.auth_middleware import get_current_user, verify_csrf
from src.db.models import User
from src.db.session import get_db
from src.models.auth_schemas import (
    ChangePasswordRequest,
    MessageResponse,
    UpdateProfileRequest,
    UserResponse,
)
from src.services.auth import hash_password, revoke_all_user_tokens, verify_password

logger = logging.getLogger(__name__)
users_router = APIRouter(prefix="/users", tags=["users"])


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        user_id=str(user.user_id),
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        avatar=user.avatar,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@users_router.get("/me", response_model=UserResponse)
def get_profile(user: User = Depends(get_current_user)) -> UserResponse:
    """Return the authenticated user's profile."""
    return _user_response(user)


@users_router.patch("/me", response_model=UserResponse, dependencies=[Depends(verify_csrf)])
def update_profile(
    body: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    """Update allowed profile fields.  Role and user_id cannot be changed here."""
    if body.full_name is not None:
        user.full_name = body.full_name.strip()

    if body.username is not None:
        # Check uniqueness
        existing = (
            db.query(User)
            .filter(
                User.username == body.username.strip(),
                User.user_id != user.user_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail="Username đã tồn tại.")
        user.username = body.username.strip()

    if body.avatar is not None:
        user.avatar = body.avatar.strip() if body.avatar else None

    db.commit()
    db.refresh(user)
    return _user_response(user)


@users_router.patch("/me/password", response_model=MessageResponse, dependencies=[Depends(verify_csrf)])
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Change the current user's password.  Revokes all refresh tokens afterwards."""
    if body.new_password != body.confirm_password:
        raise HTTPException(status_code=422, detail="Mật khẩu mới không trùng khớp.")

    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không chính xác.")

    user.password_hash = hash_password(body.new_password)
    db.commit()

    # Revoke all refresh tokens — forces re-login on other devices
    revoke_all_user_tokens(db, user.user_id)

    return MessageResponse(message="Đổi mật khẩu thành công. Các phiên đăng nhập khác đã bị đăng xuất.")
