"""Authentication business logic: password hashing, JWT tokens, session management.

All secrets come from ``src.config.Settings`` — never hardcoded.  Passwords are hashed with
bcrypt, and refresh tokens are stored as SHA-256 hashes so a database leak does not hand out
valid tokens.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import and_
from sqlalchemy.orm import Session

from src.config import get_settings
from src.db.models import RefreshToken, User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Password hashing (bcrypt)
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a plain-text password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# JWT creation / verification
# ---------------------------------------------------------------------------


def _create_token(data: dict, expires_delta: timedelta) -> str:
    settings = get_settings()
    payload = data.copy()
    payload["exp"] = datetime.now(UTC) + expires_delta
    payload["iat"] = datetime.now(UTC)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, role: str) -> str:
    """Short-lived access token carried in an HttpOnly cookie."""
    settings = get_settings()
    return _create_token(
        {"sub": user_id, "role": role, "type": "access"},
        timedelta(minutes=settings.jwt_access_expire_minutes),
    )


def create_refresh_token(user_id: str, role: str) -> str:
    """Long-lived refresh token, also in an HttpOnly cookie."""
    settings = get_settings()
    return _create_token(
        {"sub": user_id, "role": role, "type": "refresh", "jti": uuid.uuid4().hex},
        timedelta(days=settings.jwt_refresh_expire_days),
    )


def decode_token(token: str) -> dict | None:
    """Decode and verify a JWT.  Returns the payload or None on any failure."""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Token hashing (SHA-256 for database storage)
# ---------------------------------------------------------------------------


def hash_token(token: str) -> str:
    """SHA-256 hash of a token string, used to store refresh tokens without keeping the secret."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# User registration
# ---------------------------------------------------------------------------


def register_user(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str | None = None,
    username: str | None = None,
) -> User:
    """Create a new user.  Role is always 'User' — admin accounts are seeded separately."""
    # Check email uniqueness
    if db.query(User).filter(User.email == email.lower()).first():
        raise ValueError("Email đã được đăng ký.")

    # Check username uniqueness if provided
    if username:
        if db.query(User).filter(User.username == username).first():
            raise ValueError("Username đã tồn tại.")

    user = User(
        email=email.lower().strip(),
        username=username.strip() if username else None,
        password_hash=hash_password(password),
        full_name=full_name.strip() if full_name else None,
        role="User",
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def reset_password_by_email(db: Session, email: str, new_password: str) -> User:
    """Reset user password by email (after OTP verification). Revokes all active refresh tokens."""
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not user:
        raise ValueError("Không tìm thấy tài khoản với email này.")
    if user.status != "active":
        raise ValueError("Tài khoản đã bị vô hiệu hóa.")
    user.password_hash = hash_password(new_password)
    db.commit()
    revoke_all_user_tokens(db, user.user_id)
    return user


# ---------------------------------------------------------------------------
# User authentication
# ---------------------------------------------------------------------------


def authenticate_user(db: Session, email: str, password: str) -> User:
    """Verify email + password. Returns the User or raises ValueError."""
    user = db.query(User).filter(User.email == email.lower()).first()
    if not user or not verify_password(password, user.password_hash):
        raise ValueError("Email hoặc mật khẩu không chính xác.")
    if user.status != "active":
        raise ValueError("Tài khoản đã bị vô hiệu hóa.")
    return user


# ---------------------------------------------------------------------------
# Refresh token session management
# ---------------------------------------------------------------------------


def create_session(db: Session, user_id: uuid.UUID, refresh_token: str) -> RefreshToken:
    """Store a hashed refresh token in the database."""
    settings = get_settings()
    rt = RefreshToken(
        user_id=user_id,
        token_hash=hash_token(refresh_token),
        expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_expire_days),
    )
    db.add(rt)
    db.commit()
    db.refresh(rt)
    return rt


def refresh_access(db: Session, refresh_token_str: str) -> tuple[str, str, User]:
    """Validate a refresh token, rotate it, and return (new_access, new_refresh, user).

    Rotation: the old token is revoked and a new one is issued.  If the old token was already
    revoked, all of the user's tokens are revoked — this detects token theft.
    """
    payload = decode_token(refresh_token_str)
    if not payload or payload.get("type") != "refresh":
        raise ValueError("Token không hợp lệ.")

    token_hash = hash_token(refresh_token_str)
    stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if not stored:
        raise ValueError("Token không tồn tại.")

    # Detect reuse of a revoked token → revoke all tokens for this user (token theft detection)
    if stored.revoked_at is not None:
        logger.warning("Reuse of revoked refresh token detected for user %s", stored.user_id)
        db.query(RefreshToken).filter(
            and_(RefreshToken.user_id == stored.user_id, RefreshToken.revoked_at.is_(None)),
        ).update({"revoked_at": datetime.now(UTC)})
        db.commit()
        raise ValueError("Token đã bị thu hồi. Vui lòng đăng nhập lại.")

    if stored.expires_at < datetime.now(UTC):
        raise ValueError("Token đã hết hạn.")

    user = db.query(User).filter(User.user_id == stored.user_id).first()
    if not user or user.status != "active":
        raise ValueError("Tài khoản không hợp lệ.")

    # Rotation: revoke old, issue new
    stored.revoked_at = datetime.now(UTC)

    new_access = create_access_token(str(user.user_id), user.role)
    new_refresh = create_refresh_token(str(user.user_id), user.role)
    create_session(db, user.user_id, new_refresh)

    db.commit()
    return new_access, new_refresh, user


def revoke_refresh_token(db: Session, refresh_token_str: str) -> None:
    """Revoke a single refresh token (logout current session)."""
    token_hash = hash_token(refresh_token_str)
    stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if stored and stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
        db.commit()


def revoke_all_user_tokens(db: Session, user_id: uuid.UUID) -> None:
    """Revoke all refresh tokens for a user (password change, force logout)."""
    db.query(RefreshToken).filter(
        and_(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)),
    ).update({"revoked_at": datetime.now(UTC)})
    db.commit()


# ---------------------------------------------------------------------------
# Google OAuth 2.0 Integration
# ---------------------------------------------------------------------------


def authenticate_google_user(
    db: Session,
    *,
    code: str | None = None,
    credential: str | None = None,
    redirect_uri: str | None = None,
) -> User:
    """Authenticate or register a user using Google OAuth 2.0.

    Accepts either an authorization ``code`` (code flow) or an ``id_token`` / ``credential`` (GIS flow).
    Exchanges/verifies with Google APIs, fetches profile, and finds or creates the user in PostgreSQL.
    """
    import json
    import os
    import urllib.error
    import urllib.parse
    import urllib.request

    settings = get_settings()
    client_id = settings.google_client_id or os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = settings.google_client_secret or os.environ.get("GOOGLE_CLIENT_SECRET", "")

    user_info: dict = {}

    if code:
        # Exchange authorization code for tokens
        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri or "",
            "grant_type": "authorization_code",
        }
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            token_url,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "SceneSearch-App/1.0",
            },
        )

        try:
            with urllib.request.urlopen(req) as resp:
                token_resp = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            logger.error("Failed to exchange Google OAuth code: %s - Body: %s", exc, err_body)
            raise ValueError(f"Xác thực Google thất bại: {err_body}") from exc
        except Exception as exc:
            logger.error("Failed to exchange Google OAuth code: %s", exc)
            raise ValueError("Không thể xác thực mã OAuth từ Google.") from exc

        access_token = token_resp.get("access_token")
        id_token_str = token_resp.get("id_token")

        if access_token:
            # Fetch user info using access token
            userinfo_url = f"https://www.googleapis.com/oauth2/v3/userinfo?access_token={access_token}"
            try:
                userinfo_req = urllib.request.Request(userinfo_url, headers={"User-Agent": "SceneSearch-App/1.0"})
                with urllib.request.urlopen(userinfo_req) as resp:
                    user_info = json.loads(resp.read().decode("utf-8"))
            except Exception as exc:
                logger.warning("Failed to fetch userinfo with access token: %s", exc)

        if not user_info and id_token_str:
            credential = id_token_str

    if not user_info and credential:
        # Verify ID token via Google tokeninfo
        info_url = f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}"
        try:
            info_req = urllib.request.Request(info_url, headers={"User-Agent": "SceneSearch-App/1.0"})
            with urllib.request.urlopen(info_req) as resp:
                user_info = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            logger.error("Failed to verify Google ID token: %s - Body: %s", exc, err_body)
            raise ValueError("ID Token từ Google không hợp lệ.") from exc
        except Exception as exc:
            logger.error("Failed to verify Google ID token: %s", exc)
            raise ValueError("ID Token từ Google không hợp lệ.") from exc

    email = user_info.get("email")
    if not email:
        raise ValueError("Không lấy được email từ tài khoản Google.")

    # Find existing user by email
    user = db.query(User).filter(User.email == email.lower()).first()

    if not user:
        # Create new user for Google SSO
        full_name = user_info.get("name") or user_info.get("given_name") or email.split("@")[0]
        avatar = user_info.get("picture")
        user = User(
            email=email.lower().strip(),
            full_name=full_name,
            avatar=avatar,
            password_hash=hash_password(uuid.uuid4().hex),
            role="User",
            status="active",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # Update name or avatar if provided and missing
        if user_info.get("picture") and not user.avatar:
            user.avatar = user_info.get("picture")
            db.commit()

    if user.status != "active":
        raise ValueError("Tài khoản đã bị vô hiệu hóa.")

    return user
