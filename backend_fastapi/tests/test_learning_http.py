from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app.db import init_db, override_engine_for_tests
from app.domain.models import LearningRecord, User
from app.infrastructure.dependencies import get_current_user
from app.main import app
from app.routers.learning import _calc_learning_stats


def test_learning_stats_http_shape(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    app.dependency_overrides[get_current_user] = lambda: User(id=1, username="learning_http", email="learning_http@test.com", role="student")
    try:
        client = TestClient(app)
        resp = client.get("/v1/learning/stats")
        assert resp.status_code == 200
        data = resp.json()
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert isinstance(data.get("vocabulary"), int)
    assert isinstance(data.get("essay"), int)
    assert isinstance(data.get("dialogue"), int)
    assert isinstance(data.get("analysis"), int)


def test_learning_analyze_http_shape(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    app.dependency_overrides[get_current_user] = lambda: User(id=1, username="learning_http", email="learning_http@test.com", role="student")
    try:
        client = TestClient(app)
        resp = client.post("/v1/learning/analyze", json={"dimension": "vocabulary"})
        assert resp.status_code == 200
        data = resp.json()
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert data.get("dimension") == "vocabulary"
    assert isinstance(data.get("score"), int)
    assert isinstance(data.get("trend"), int)
    assert isinstance(data.get("insights"), list)
    assert isinstance(data.get("recommendations"), list)
    assert isinstance(data.get("visualization"), dict)


def test_calc_learning_stats_counts_text_and_voice_dialogue(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    with Session(engine) as session:
        user = User(username="learning_stats_student", email="learning_stats@test.com", role="student")
        session.add(user)
        session.commit()
        session.refresh(user)

        session.add(
            LearningRecord(
                user_id=int(user.id or 0),
                type="dialogue",
                content="hello teacher",
                meta_data={"action": "text_turn"},
            )
        )
        session.add(
            LearningRecord(
                user_id=int(user.id or 0),
                type="dialogue",
                content="hello by voice",
                meta_data={"action": "voice_turn"},
            )
        )
        session.commit()

        stats = _calc_learning_stats(session, int(user.id or 0))

    assert stats.dialogue == 2
