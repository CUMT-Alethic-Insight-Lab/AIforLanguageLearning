from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from app.db import override_engine_for_tests
from app.main import app
from app.settings import settings


@pytest.fixture(scope="module")
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    override_engine_for_tests(engine)
    SQLModel.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c
    override_engine_for_tests(None)


def test_register_and_login(client: TestClient) -> None:
    # register
    r = client.post(
        "/api/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "Hello1234"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["data"]["accessToken"]
    assert data["data"]["refreshToken"]

    # login
    r = client.post("/api/auth/login", json={"username": "alice", "password": "Hello1234"})
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    access_token = data["data"]["accessToken"]

    # me
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert r.status_code == 200
    assert r.json()["data"]["username"] == "alice"


def test_refresh_token(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"username": "alice", "password": "Hello1234"})
    refresh = r.json()["data"]["refreshToken"]
    r = client.post("/api/auth/refresh", json={"refreshToken": refresh})
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert r.json()["data"]["accessToken"]


def test_password_strength(client: TestClient) -> None:
    r = client.post(
        "/api/auth/register",
        json={"username": "bob", "email": "bob@example.com", "password": "weak"},
    )
    assert r.status_code == 200
    assert r.json()["success"] is False


def test_student_profile(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"username": "alice", "password": "Hello1234"})
    token = r.json()["data"]["accessToken"]

    r = client.get("/api/auth/profile", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["data"] is None

    r = client.post(
        "/api/auth/profile",
        json={"level": "intermediate", "goals": ["travel"], "interests": ["movies"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["level"] == "intermediate"


def test_admin_users(client: TestClient) -> None:
    assert settings.seed_admin_enabled is True
    r = client.post(
        "/api/auth/login",
        json={
            "username": settings.seed_admin_username,
            "password": settings.seed_admin_password,
        },
    )
    token = r.json()["data"]["accessToken"]

    r = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert len(r.json()["data"]["users"]) >= 1
