"""Tests for research export API (Agent D)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app.db import init_db, override_engine_for_tests
from app.domain.classroom.models import (
    ActivityTurn,
    Classroom,
    ClassroomSession,
    SessionActivity,
)
from app.domain.models import User
from app.main import app


def _register_and_login(client: TestClient, username: str) -> dict:
    client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "Admin1234"},
    )
    resp = client.post("/api/auth/login", json={"username": username, "password": "Admin1234"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    return body["data"]


# ── data setup helper ────────────────────────────────────────────────────────


def _setup_export_data(session: Session, teacher_user_id: int) -> dict:
    """Create student, classroom, session, activity, turns. Return ids.

    teacher_user_id must be an existing User.id with role='teacher'.
    """
    student = User(username="export_s", email="export_s@test.dev", role="student")
    session.add(student)
    session.flush()

    classroom = Classroom(
        name="Export Test Class",
        course_name="ENG201",
        teacher_id=teacher_user_id,
        semester="2026-Fall",
    )
    session.add(classroom)
    session.flush()

    cls_sess = ClassroomSession(
        classroom_id=classroom.id,
        teacher_id=teacher_user_id,
        topic="Export Topic",
    )
    session.add(cls_sess)
    session.flush()

    activity = SessionActivity(
        classroom_session_id=cls_sess.id,
        student_id=student.id,
        activity_type="dialogue_turn",
        source_event_id="conv_test123",
    )
    session.add(activity)
    session.flush()

    turn = ActivityTurn(
        session_activity_id=activity.id,
        user_id=student.id,
        turn_type="student",
        content="What is LLM?",
    )
    session.add(turn)
    session.flush()

    session.commit()

    # Extract plain IDs to avoid DetachedInstanceError after session closes
    return {
        "teacher_id": teacher_user_id,
        "student_id": student.id,
        "classroom_id": classroom.id,
        "classroom_session_id": cls_sess.id,
        "activity_id": activity.id,
        "turn_id": turn.id,
    }


# ── tests ────────────────────────────────────────────────────────────────────


# ── helper: promote a registered user to a given role ────────────────────────

def _promote_user(engine, user_id: int, role: str) -> None:
    with Session(engine) as s:
        u = s.get(User, user_id)
        u.role = role
        s.commit()


def test_export_json_teacher_own_classroom(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    auth = _register_and_login(client, "export_teacher")
    token = auth["accessToken"]
    teacher_id = auth["user"]["id"]
    _promote_user(engine, teacher_id, "teacher")

    data = _setup_export_data(Session(engine), teacher_id)

    resp = client.get(
        f"/api/v1/research/exports/turns.json?classroom_id={data['classroom_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["turn_id"] == data["turn_id"]
    assert rows[0]["source_event_id"] == "conv_test123"
    assert "user_id" not in rows[0]


def test_export_json_with_identifiers(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    auth = _register_and_login(client, "export_ident_t")
    token = auth["accessToken"]
    teacher_id = auth["user"]["id"]
    _promote_user(engine, teacher_id, "teacher")

    data = _setup_export_data(Session(engine), teacher_id)

    resp = client.get(
        f"/api/v1/research/exports/turns.json?classroom_id={data['classroom_id']}&include_identifiers=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["user_id"] == data["student_id"]


def test_export_csv_teacher_own_classroom(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    auth = _register_and_login(client, "export_csv_t")
    token = auth["accessToken"]
    teacher_id = auth["user"]["id"]
    _promote_user(engine, teacher_id, "teacher")

    data = _setup_export_data(Session(engine), teacher_id)

    resp = client.get(
        f"/api/v1/research/exports/turns.csv?classroom_id={data['classroom_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]


def test_export_teacher_cross_classroom_denied(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    auth = _register_and_login(client, "export_cross_t")
    token = auth["accessToken"]
    teacher_id = auth["user"]["id"]
    _promote_user(engine, teacher_id, "teacher")

    resp = client.get(
        "/api/v1/research/exports/turns.json?classroom_id=99999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_export_student_denied(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    auth = _register_and_login(client, "export_student")
    token = auth["accessToken"]

    resp = client.get(
        "/api/v1/research/exports/turns.json?classroom_id=1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_export_anonymous_denied(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    resp = client.get("/api/v1/research/exports/turns.json?classroom_id=1")
    assert resp.status_code in (401, 403)


def test_export_admin_any_classroom(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    auth = _register_and_login(client, "export_admin")
    token = auth["accessToken"]
    admin_id = auth["user"]["id"]
    _promote_user(engine, admin_id, "admin")

    data = _setup_export_data(Session(engine), admin_id)

    resp = client.get(
        f"/api/v1/research/exports/turns.json?classroom_id={data['classroom_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
