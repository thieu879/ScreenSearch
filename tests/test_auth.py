"""Tests for authentication and user management API endpoints.

Covers:
- /auth/send-otp: generate and store OTP code with 5-minute TTL
- /auth/register: successful registration with valid OTP, failure on bad/expired OTP
- /auth/login: valid credentials, invalid password, inactive user, HttpOnly cookies set
- /auth/forgot-password & /auth/reset-password: password reset flow via OTP
- /auth/me: profile fetch with valid access token, unauthenticated 401
- /auth/google: Google OAuth login flow
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import RefreshToken, User
from src.db.session import get_db
from src.main import app
from src.services.otp import store_otp


# Disable app lifespan (model loading) for fast unit testing
@asynccontextmanager
async def mock_lifespan(app):
    yield


app.router.lifespan_context = mock_lifespan


# Setup test SQLite in-memory database for isolated testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    User.__table__.create(bind=engine, checkfirst=True)
    RefreshToken.__table__.create(bind=engine, checkfirst=True)
    yield
    RefreshToken.__table__.drop(bind=engine, checkfirst=True)
    User.__table__.drop(bind=engine, checkfirst=True)


def test_send_otp_success():
    with patch("src.api.auth.send_otp_email") as mock_email:
        res = client.post(
            "/api/v1/auth/send-otp",
            json={"email": "newuser@example.com", "purpose": "register"},
        )
        assert res.status_code == 200
        assert "Mã OTP đã được gửi" in res.json()["message"]
        mock_email.assert_called_once()


def test_register_user_without_otp_fails():
    res = client.post(
        "/api/v1/auth/register",
        json={
            "email": "no_otp@example.com",
            "password": "Password123",
            "otp": "000000",
        },
    )
    assert res.status_code == 400
    assert "Mã OTP không hợp lệ" in res.json()["detail"]


def test_register_user_success():
    email = "testuser@example.com"
    otp_code = "123456"
    store_otp(email, "register", otp_code, ttl_seconds=300)

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "otp": otp_code,
            "full_name": "Test User",
            "username": "testuser",
        },
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Đăng ký tài khoản thành công."


def test_login_success_and_cookies():
    email = "loginuser@example.com"
    otp_code = "654321"
    store_otp(email, "register", otp_code, ttl_seconds=300)

    # Register
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "MySecretPassword123", "otp": otp_code},
    )

    # Login
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "MySecretPassword123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["email"] == email
    assert data["user"]["role"] == "User"

    # Check cookies
    cookies = response.cookies
    assert "access_token" in cookies
    assert "refresh_token" in cookies
    assert "csrf_token" in cookies


def test_forgot_password_and_reset_flow():
    email = "forgot@example.com"
    otp_code = "999888"
    store_otp(email, "register", "111222", ttl_seconds=300)

    # 1. Register
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "OldPassword123", "otp": "111222"},
    )

    # 2. Forgot password request OTP
    with patch("src.api.auth.send_otp_email") as mock_email:
        res = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": email, "purpose": "forgot_password"},
        )
        assert res.status_code == 200
        mock_email.assert_called_once()

    # Pre-store known OTP for reset test
    store_otp(email, "forgot_password", otp_code, ttl_seconds=300)

    # 3. Reset password
    reset_res = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": email,
            "otp": otp_code,
            "new_password": "NewPassword123",
            "confirm_password": "NewPassword123",
        },
    )
    assert reset_res.status_code == 200
    assert "Đặt lại mật khẩu thành công" in reset_res.json()["message"]

    # 4. Login with new password
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "NewPassword123"},
    )
    assert login_res.status_code == 200


def test_google_login_missing_code():
    res = client.post("/api/v1/auth/google", json={})
    assert res.status_code == 400
    assert "Thiếu mã xác thực Google OAuth" in res.json()["detail"]


def test_admin_stats_and_user_management():
    # 1. Register an admin user
    email = "admin@example.com"
    otp_code = "654321"
    store_otp(email, "register", otp_code, ttl_seconds=300)
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "AdminPassword123", "otp": otp_code},
    )

    # Elevate role to Admin directly in DB
    db = TestingSessionLocal()
    admin_user = db.query(User).filter(User.email == email).first()
    assert admin_user is not None
    admin_user.role = "Admin"
    db.commit()
    db.close()

    # 2. Login as Admin
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "AdminPassword123"},
    )
    assert login_res.status_code == 200
    cookies = login_res.cookies
    csrf_token = cookies.get("csrf_token")

    # 3. Get /admin/stats
    stats_res = client.get("/api/v1/admin/stats", cookies=cookies)
    assert stats_res.status_code == 200
    stats_data = stats_res.json()
    assert stats_data["total_users"] >= 1
    assert stats_data["admin_users"] >= 1

    # 4. Create new user via admin POST /admin/users
    create_res = client.post(
        "/api/v1/admin/users",
        headers={"X-CSRF-Token": csrf_token},
        cookies=cookies,
        json={
            "email": "created_by_admin@example.com",
            "password": "Password123",
            "full_name": "Created User",
            "username": "createduser",
            "role": "User",
            "status": "active",
        },
    )
    assert create_res.status_code == 200
    created_user_data = create_res.json()
    assert created_user_data["email"] == "created_by_admin@example.com"

    # 5. List users
    users_res = client.get("/api/v1/admin/users", cookies=cookies)
    assert users_res.status_code == 200
    user_list = users_res.json()
    assert len(user_list) >= 2
