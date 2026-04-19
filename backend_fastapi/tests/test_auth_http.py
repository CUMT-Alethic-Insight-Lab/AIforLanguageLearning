from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app.db import init_db, override_engine_for_tests
from app.main import app


def _ensure_admin_exists(client: TestClient) -> None:
    """Ensure an admin user exists for HTTP auth tests."""
    r = client.post(
        "/api/auth/register",
        json={"username": "admin", "email": "admin@example.com", "password": "Admin1234"},
    )
    # If the user already exists, the register endpoint returns success=False;
    # we can safely ignore that as long as the user is present for login.
    assert r.status_code == 200


def test_auth_login_admin_ok(tmp_path: Path) -> None:
    db_path = tmp_path / "auth_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    _ensure_admin_exists(client)
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "Admin1234"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert isinstance(body.get("data"), dict)
    data = body["data"]
    assert isinstance(data.get("accessToken"), str)
    assert data.get("accessToken")
    assert isinstance(data.get("user"), dict)
    assert isinstance(data["user"].get("id"), int)
    assert data["user"]["username"] == "admin"


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
