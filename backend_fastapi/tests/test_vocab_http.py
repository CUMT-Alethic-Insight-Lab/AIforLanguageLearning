from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, select

from app.db import init_db, override_engine_for_tests
from app.main import app
from app.models import PublicVocabEntry, UserVocabQuery


def _register_and_login(client: TestClient, username: str) -> str:
    client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "Admin1234"},
    )
    resp = client.post("/api/auth/login", json={"username": username, "password": "Admin1234"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    return str(body["data"]["accessToken"])


def test_vocab_lookup_http_uses_public_vocab(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    with Session(engine) as session:
        session.add(PublicVocabEntry(term="hello", definition="释义：你好\n例句：Hello!", lang="en"))
        session.commit()

    client = TestClient(app)
    resp = client.post("/v1/vocab/lookup", json={"term": "hello", "source": "manual"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["term"] == "hello"
    assert body["from_public_vocab"] is True
    assert "释义" in body["definition"]
    assert body["cefr_level"]
    assert isinstance(body["recommendations"], list)


def test_vocab_lookup_ocr_http(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    monkeypatch.setattr("app.routers.vocab.ocr_image_base64", lambda image, language="english": "hello")
    async def _fake_generate_vocab_fields(_term: str):
        return {
            "meaning": "你好",
            "example": "Hello, world.",
            "example_translation": "你好，世界。",
        }

    monkeypatch.setattr("app.routers.vocab.generate_vocab_fields", _fake_generate_vocab_fields)
    async def _fake_build_recommendations(**_: object):
        return []

    monkeypatch.setattr("app.routers.vocab._build_recommendations", _fake_build_recommendations)

    client = TestClient(app)
    payload = base64.b64encode(b"dummy").decode("utf-8")
    resp = client.post("/v1/vocab/lookup-ocr", json={"image": payload, "language": "english"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["term"] == "hello"
    assert body["meaning"] == "你好"


def test_vocab_lookup_persists_user_linked_metadata(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    with Session(engine) as session:
        session.add(PublicVocabEntry(term="agenda", definition="释义：议程\n例句：Let's review the agenda.", lang="en"))
        session.commit()

    from app.routers.vocab import LookupRecommendation

    async def _fake_build_recommendations(**_: object):
        return [
            LookupRecommendation(
                word="schedule",
                reason="与 agenda 语义接近",
                score=0.92,
                relation_type="synonym",
            )
        ]

    monkeypatch.setattr("app.routers.vocab._build_recommendations", _fake_build_recommendations)

    client = TestClient(app)
    token = _register_and_login(client, "student_lookup")
    resp = client.post(
        "/v1/vocab/lookup",
        json={"term": "agenda", "source": "manual", "session_id": "sess-1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meaning"] == "议程"
    assert isinstance(body["recommendations"], list)

    with Session(engine) as session:
        rows = list(session.exec(select(UserVocabQuery)).all())
        assert len(rows) == 1
        query = rows[0]
        assert query.user_id is not None
        assert query.meta_data["cefr_level"]
        assert query.meta_data["source"] == "manual"
