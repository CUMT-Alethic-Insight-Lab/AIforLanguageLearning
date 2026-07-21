from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app.db import init_db, override_engine_for_tests
from app.domain.models import User
from app.infrastructure.security import create_access_token, hash_password
from app.main import app


def _register_and_login(client: TestClient, username: str) -> dict:
    """Register a user and return auth data (accessToken + user dict)."""
    client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "Admin1234"},
    )
    resp = client.post("/api/auth/login", json={"username": username, "password": "Admin1234"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    return body["data"]


_FAKE_PIPELINE_RESULT = {
    "dimensions": {},
    "total_score": 7.0,
    "grade": "B",
    "feedback": "ok",
    "suggestions": [],
    "corrected_text": "",
    "llm_raw": {
        "score": 70,
        "feedback": "ok",
        "errors": [],
        "suggestions": [],
        "rewritten": "",
        "scores": {},
    },
}


async def _fake_run_grading_pipeline(*, ocr_text: str, language: str):
    return _FAKE_PIPELINE_RESULT


# ---------------------------------------------------------------------------
# Test 1: Anonymous reads anonymous submission → 200
# ---------------------------------------------------------------------------
def test_anonymous_read_anonymous_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    monkeypatch.setattr("app.routers.essays.run_grading_pipeline", _fake_run_grading_pipeline)

    # Create an anonymous submission (no auth header → user_id IS NULL)
    client = TestClient(app)
    resp = client.post(
        "/v1/essays/grade",
        json={"text": "I has a pen.", "language": "en"},
    )
    assert resp.status_code == 200
    submission_id = resp.json()["submission_id"]

    # Anonymous GET → should succeed (submission.user_id is None)
    resp2 = client.get(f"/v1/essays/{submission_id}")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["submission_id"] == submission_id


# ---------------------------------------------------------------------------
# Test 2: Anonymous reads named submission → 403
# ---------------------------------------------------------------------------
def test_anonymous_read_named_submission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    monkeypatch.setattr("app.routers.essays.run_grading_pipeline", _fake_run_grading_pipeline)

    client = TestClient(app)
    auth = _register_and_login(client, "named_user")
    token = auth["accessToken"]

    # Create a submission as authenticated user → submission.user_id is set
    resp = client.post(
        "/v1/essays/grade",
        json={"text": "I has a pen.", "language": "en"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    submission_id = resp.json()["submission_id"]

    # Anonymous GET → should be denied (submission.user_id is not None)
    resp2 = client.get(f"/v1/essays/{submission_id}")
    assert resp2.status_code == 403


# ---------------------------------------------------------------------------
# Test 3: Student reads own submission → 200
# ---------------------------------------------------------------------------
def test_student_read_own_submission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    monkeypatch.setattr("app.routers.essays.run_grading_pipeline", _fake_run_grading_pipeline)

    client = TestClient(app)
    auth = _register_and_login(client, "student_own")
    token = auth["accessToken"]

    # Create a submission as this student
    resp = client.post(
        "/v1/essays/grade",
        json={"text": "My own essay.", "language": "en"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    submission_id = resp.json()["submission_id"]

    # Student reads own submission → should succeed
    resp2 = client.get(
        f"/v1/essays/{submission_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["submission_id"] == submission_id


# ---------------------------------------------------------------------------
# Test 4: Student reads another student's submission → 403
# ---------------------------------------------------------------------------
def test_student_read_others_submission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    monkeypatch.setattr("app.routers.essays.run_grading_pipeline", _fake_run_grading_pipeline)

    client = TestClient(app)
    auth_a = _register_and_login(client, "student_a")
    token_a = auth_a["accessToken"]

    # Create a submission as student_a
    resp = client.post(
        "/v1/essays/grade",
        json={"text": "Student A's essay.", "language": "en"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    submission_id = resp.json()["submission_id"]

    # Register and login as student_b
    auth_b = _register_and_login(client, "student_b")
    token_b = auth_b["accessToken"]

    # Student B tries to read Student A's submission → should be denied
    resp2 = client.get(
        f"/v1/essays/{submission_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp2.status_code == 403


# ---------------------------------------------------------------------------
# Test 5: Teacher reads any submission → 200
# ---------------------------------------------------------------------------
def test_teacher_read_any_submission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    monkeypatch.setattr("app.routers.essays.run_grading_pipeline", _fake_run_grading_pipeline)

    client = TestClient(app)
    auth = _register_and_login(client, "student_for_teacher")
    token = auth["accessToken"]

    # Create a submission as a student
    resp = client.post(
        "/v1/essays/grade",
        json={"text": "Student essay for teacher test.", "language": "en"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    submission_id = resp.json()["submission_id"]

    # Create a teacher user directly (register API always sets role="student")
    with Session(engine) as session:
        teacher = User(
            username="teacher_user",
            email="teacher@example.com",
            password_hash=hash_password("Admin1234"),
            role="teacher",
        )
        session.add(teacher)
        session.commit()
        session.refresh(teacher)
        teacher_token = create_access_token({"sub": teacher.username, "userId": teacher.id})

    # Teacher reads the student's submission → should succeed
    resp2 = client.get(
        f"/v1/essays/{submission_id}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["submission_id"] == submission_id


# ---------------------------------------------------------------------------
# Test 6: Admin reads any submission → 200
# ---------------------------------------------------------------------------
def test_admin_read_any_submission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    monkeypatch.setattr("app.routers.essays.run_grading_pipeline", _fake_run_grading_pipeline)

    client = TestClient(app)
    auth = _register_and_login(client, "student_for_admin")
    token = auth["accessToken"]

    # Create a submission as a student
    resp = client.post(
        "/v1/essays/grade",
        json={"text": "Student essay for admin test.", "language": "en"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    submission_id = resp.json()["submission_id"]

    # Create an admin user directly
    with Session(engine) as session:
        admin = User(
            username="admin_user",
            email="admin@example.com",
            password_hash=hash_password("Admin1234"),
            role="admin",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        admin_token = create_access_token({"sub": admin.username, "userId": admin.id})

    # Admin reads the student's submission → should succeed
    resp2 = client.get(
        f"/v1/essays/{submission_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["submission_id"] == submission_id


# ---------------------------------------------------------------------------
# Test 7: GET with nonexistent submission_id → 404
# ---------------------------------------------------------------------------
def test_get_nonexistent_submission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    resp = client.get("/v1/essays/99999")
    assert resp.status_code == 404
