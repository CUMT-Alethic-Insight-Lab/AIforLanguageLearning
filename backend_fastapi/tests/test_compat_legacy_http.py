from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app.db import init_db, override_engine_for_tests
from app.main import app
from app.routers.vocab import VocabDefinition, VocabLookupResponse


def test_legacy_vocab_query_compat(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    async def _fake_lookup(*_args, **_kwargs):
        return VocabLookupResponse(
            term="hello",
            definition="你好",
            from_public_vocab=False,
            meaning="你好",
            example="Hello.",
            example_translation="你好。",
            definitions=[
                VocabDefinition(
                    meaning="你好",
                    example="Hello.",
                    example_translation="你好。",
                )
            ],
        )

    monkeypatch.setattr("app.routers.compat_legacy.lookup_vocab", _fake_lookup)

    client = TestClient(app)
    resp = client.post("/api/query/vocabulary", json={"word": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["word"] == "hello"


def test_legacy_learning_stats_compat(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    auth = client.post(
        "/api/auth/register",
        json={
            "username": "legacy_stats",
            "email": "legacy_stats@example.com",
            "password": "LegacyStats123",
        },
    ).json()
    token = auth["data"]["accessToken"]
    resp = client.get(
        "/api/learning/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert isinstance(data.get("vocabulary"), int)
    assert isinstance(data.get("essay"), int)
    assert isinstance(data.get("dialogue"), int)
    assert isinstance(data.get("analysis"), int)
