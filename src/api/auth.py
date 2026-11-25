"""Authentication endpoints: register, login, refresh, logout, me.

Tokens are set as HttpOnly cookies — never returned in the response body.  The CSRF token
is set as a non-HttpOnly cookie so the frontend JavaScript can read it and send it back as
a header on state-changing requests.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from src.api.auth_middleware import generate_csrf_token, get_current_user
from src.config import get_settings
from src.db.models import User
from src.db.session import get_db
from src.models.auth_schemas import (
    AuthResponse,
    GoogleLoginRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    ResetPasswordRequest,
    SendOtpRequest,
    UserResponse,
)
from src.services.auth import (
    authenticate_google_user,
    authenticate_user,
    create_access_token,
    create_refresh_token,
    create_session,
    refresh_access,
    register_user,
    reset_password_by_email,
    revoke_refresh_token,
)
from src.services.email import send_otp_email
from src.services.otp import delete_otp, generate_otp_code, store_otp, verify_otp

logger = logging.getLogger(__name__)
auth_router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set the three authentication cookies: access, refresh, and CSRF."""
    settings = get_settings()

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.jwt_access_expire_minutes * 60,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.jwt_refresh_expire_days * 86400,
        path="/api/v1/auth",  # Only sent to auth endpoints
    )
    # CSRF cookie — readable by JS, not HttpOnly
    response.set_cookie(
        key="csrf_token",
        value=generate_csrf_token(),
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.jwt_refresh_expire_days * 86400,
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/v1/auth")
    response.delete_cookie("csrf_token", path="/")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@auth_router.post("/send-otp", response_model=MessageResponse)
def send_otp(body: SendOtpRequest, db: Session = Depends(get_db)) -> MessageResponse:
    """Generate and send a 6-digit OTP code via email with 5-minute TTL."""
    email = body.email.lower().strip()
    existing = db.query(User).filter(User.email == email).first()

    if body.purpose == "register":
        if existing:
            raise HTTPException(status_code=409, detail="Email này đã được sử dụng. Vui lòng đăng nhập.")
    elif body.purpose == "forgot_password":
        if not existing:
            raise HTTPException(status_code=404, detail="Email chưa được đăng ký trong hệ thống.")
        if existing.status != "active":
            raise HTTPException(status_code=400, detail="Tài khoản đã bị vô hiệu hóa.")

    otp_code = generate_otp_code(6)
    store_otp(email, body.purpose, otp_code, ttl_seconds=300)

    try:
        send_otp_email(email, otp_code, purpose=body.purpose)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return MessageResponse(message="Mã OTP đã được gửi đến email của bạn. Mã có hiệu lực trong 5 phút.")


@auth_router.post("/register", response_model=MessageResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> MessageResponse:
    """Create a new user account after OTP verification. Role is always 'User'."""
    email = body.email.lower().strip()

    if not verify_otp(email, "register", body.otp):
        raise HTTPException(status_code=400, detail="Mã OTP không hợp lệ hoặc đã hết hạn (5 phút).")

    try:
        register_user(
            db,
            email=email,
            password=body.password,
            full_name=body.full_name,
            username=body.username,
        )
        delete_otp(email, "register")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return MessageResponse(message="Đăng ký tài khoản thành công.")


@auth_router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(body: SendOtpRequest, db: Session = Depends(get_db)) -> MessageResponse:
    """Request an OTP email for password reset."""
    body.purpose = "forgot_password"
    return send_otp(body, db)


@auth_router.post("/reset-password", response_model=MessageResponse)
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)) -> MessageResponse:
    """Reset user password using verified 6-digit OTP code."""
    if body.new_password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Mật khẩu nhập lại không trùng khớp.")

    email = body.email.lower().strip()
    if not verify_otp(email, "forgot_password", body.otp):
        raise HTTPException(status_code=400, detail="Mã OTP không hợp lệ hoặc đã hết hạn (5 phút).")

    try:
        reset_password_by_email(db, email, body.new_password)
        delete_otp(email, "forgot_password")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return MessageResponse(message="Đặt lại mật khẩu thành công. Vui lòng đăng nhập với mật khẩu mới.")


@auth_router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> AuthResponse:
    """Authenticate with email + password, receive tokens in HttpOnly cookies."""
    try:
        user = authenticate_user(db, body.email, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    access = create_access_token(str(user.user_id), user.role)
    refresh = create_refresh_token(str(user.user_id), user.role)
    create_session(db, user.user_id, refresh)

    _set_auth_cookies(response, access, refresh)

    return AuthResponse(message="Đăng nhập thành công.", user=_user_response(user))


@auth_router.post("/google", response_model=AuthResponse)
def google_login(body: GoogleLoginRequest, response: Response, db: Session = Depends(get_db)) -> AuthResponse:
    """Authenticate or register using Google OAuth (authorization code or ID token)."""
    if not body.code and not body.credential:
        raise HTTPException(status_code=400, detail="Thiếu mã xác thực Google OAuth.")

    try:
        user = authenticate_google_user(
            db,
            code=body.code,
            credential=body.credential,
            redirect_uri=body.redirect_uri,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    access = create_access_token(str(user.user_id), user.role)
    refresh = create_refresh_token(str(user.user_id), user.role)
    create_session(db, user.user_id, refresh)

    _set_auth_cookies(response, access, refresh)

    return AuthResponse(message="Đăng nhập Google thành công.", user=_user_response(user))


@auth_router.post("/refresh", response_model=AuthResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> AuthResponse:
    """Exchange a valid refresh token for a new access + refresh token pair (rotation)."""
    refresh_token_str = request.cookies.get("refresh_token")
    if not refresh_token_str:
        raise HTTPException(status_code=401, detail="Refresh token thiếu.")

    try:
        new_access, new_refresh, user = refresh_access(db, refresh_token_str)
    except ValueError as exc:
        _clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    _set_auth_cookies(response, new_access, new_refresh)

    return AuthResponse(message="Token đã được làm mới.", user=_user_response(user))


@auth_router.post("/logout", response_model=MessageResponse)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> MessageResponse:
    """Revoke the current refresh token and clear all auth cookies."""
    refresh_token_str = request.cookies.get("refresh_token")
    if refresh_token_str:
        revoke_refresh_token(db, refresh_token_str)

    _clear_auth_cookies(response)
    return MessageResponse(message="Đã đăng xuất.")


@auth_router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> UserResponse:
    """Return the currently authenticated user's profile."""
    return _user_response(user)
