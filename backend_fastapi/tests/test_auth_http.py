from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app.db import init_db, override_engine_for_tests
from app.main import app
from app.settings import settings


def _ensure_admin_exists(client: TestClient) -> None:
    """The database bootstrap owns the configured admin account."""
    assert settings.seed_admin_enabled is True


def test_auth_login_admin_ok(tmp_path: Path) -> None:
    db_path = tmp_path / "auth_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    _ensure_admin_exists(client)
    resp = client.post(
        "/api/auth/login",
        json={
            "username": settings.seed_admin_username,
            "password": settings.seed_admin_password,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert isinstance(body.get("data"), dict)
    data = body["data"]
    assert isinstance(data.get("accessToken"), str)
    assert data.get("accessToken")
    assert isinstance(data.get("user"), dict)
    assert isinstance(data["user"].get("id"), int)
    assert data["user"]["username"] == settings.seed_admin_username


def test_auth_login_rejects_wrong_password(tmp_path: Path) -> None:
    db_path = tmp_path / "auth_test2.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    _ensure_admin_exists(client)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert isinstance(body.get("error"), str)
