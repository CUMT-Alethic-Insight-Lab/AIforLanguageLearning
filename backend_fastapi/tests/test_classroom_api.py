"""Tests for classroom/experiment minimal API (Agent C)."""

from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

from app.db import override_engine_for_tests
from app.domain.classroom.models import ClassroomSession
from app.domain.models import User
from app.infrastructure.security import hash_password
from app.interfaces.classroom_router import router


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()
    SQLModel.metadata.create_all(eng)
    override_engine_for_tests(eng)
    return eng


@pytest.fixture
def client(engine):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _create_user_and_token(engine, username: str, role: str = "student") -> tuple[str, int]:
    """Create a user in the DB directly and return (access_token, user_id).

    The classroom test app does NOT include the auth router, so we
    cannot use register/login endpoints.  Instead we insert the user
    directly into the database and mint a JWT ourselves.
    """
    from sqlmodel import select

    from app.infrastructure.security import create_access_token

    with Session(engine) as session:
        existing = session.exec(select(User).where(User.username == username)).first()
        if existing is None:
            user = User(
                username=username,
                email=f"{username}@example.com",
                password_hash=hash_password("Admin1234"),
                role=role,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            user_id = user.id
        else:
            existing.role = role
            session.add(existing)
            session.commit()
            user_id = existing.id

    token = create_access_token({"sub": username})
    return token, user_id


def _seed_classroom_session(engine):
    teacher_token, teacher_id = _create_user_and_token(engine, "turn_teacher", "teacher")
    student_token, student_id = _create_user_and_token(engine, "turn_student", "student")
    outsider_token, outsider_id = _create_user_and_token(engine, "turn_outsider", "student")

    with Session(engine) as session:
        from app.domain.classroom.models import ClassEnrollment, Classroom, ClassroomSession

        classroom = Classroom(
            name="Turn Class",
            course_name="ENG101",
            teacher_id=teacher_id,
            semester="2026-Fall",
        )
        session.add(classroom)
        session.flush()
        session.add(
            ClassEnrollment(
                classroom_id=classroom.id,
                student_id=student_id,
                role="student",
            )
        )
        classroom_session = ClassroomSession(
            classroom_id=classroom.id,
            teacher_id=teacher_id,
            topic="Turn taking",
        )
        session.add(classroom_session)
        session.commit()
        session.refresh(classroom)
        session.refresh(classroom_session)

    return {
        "teacher_token": teacher_token,
        "teacher_id": teacher_id,
        "student_token": student_token,
        "student_id": student_id,
        "outsider_token": outsider_token,
        "outsider_id": outsider_id,
        "classroom_id": classroom.id,
        "session_id": classroom_session.id,
    }


# ── 1. POST /api/v1/classrooms — create classroom ──────────────────────


def test_create_classroom_as_teacher(engine, client):
    token, _ = _create_user_and_token(engine, "teacher1", role="teacher")
    resp = client.post(
        "/api/v1/classrooms",
        json={"name": "Eng101 Section A", "course_name": "ENG101", "semester": "2026-Fall"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Eng101 Section A"
    assert body["course_name"] == "ENG101"
    assert body["semester"] == "2026-Fall"
    assert isinstance(body["id"], int)
    assert isinstance(body["teacher_id"], int)


def test_create_classroom_as_student_forbidden(engine, client):
    token, _ = _create_user_and_token(engine, "student1", role="student")
    resp = client.post(
        "/api/v1/classrooms",
        json={"name": "Should Fail", "course_name": "X", "semester": "2026-Fall"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text


def test_create_classroom_unauthorized(client):
    resp = client.post(
        "/api/v1/classrooms",
        json={"name": "No Auth", "course_name": "X", "semester": "2026-Fall"},
    )
    assert resp.status_code == 401, resp.text


# ── 2. GET /api/v1/classrooms — list classrooms ────────────────────────


def test_list_classrooms_teacher(engine, client):
    token, _ = _create_user_and_token(engine, "teacher2", role="teacher")
    # Create two classrooms
    for name in ("Class A", "Class B"):
        resp = client.post(
            "/api/v1/classrooms",
            json={"name": name, "course_name": "ENG101", "semester": "2026-Fall"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
    resp = client.get(
        "/api/v1/classrooms",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_list_classrooms_student(engine, client):
    teacher_token, _ = _create_user_and_token(engine, "teacher3", role="teacher")
    # Create a classroom
    resp = client.post(
        "/api/v1/classrooms",
        json={"name": "StudentClass", "course_name": "ENG101", "semester": "2026-Fall"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201
    classroom_id = resp.json()["id"]

    # Enroll a student
    student_token, student_id = _create_user_and_token(engine, "student2", role="student")
    resp = client.post(
        f"/api/v1/classrooms/{classroom_id}/enrollments",
        json={"student_id": student_id},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201, resp.text

    # Student lists classrooms
    resp = client.get(
        "/api/v1/classrooms",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert any(c["id"] == classroom_id for c in data)


# ── 3. POST /api/v1/classrooms/{id}/enrollments ────────────────────────


def test_enroll_student(engine, client):
    teacher_token, _ = _create_user_and_token(engine, "teacher4", role="teacher")
    resp = client.post(
        "/api/v1/classrooms",
        json={"name": "EnrollTest", "course_name": "ENG101", "semester": "2026-Fall"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201
    classroom_id = resp.json()["id"]

    _, student_id = _create_user_and_token(engine, "student3", role="student")

    resp = client.post(
        f"/api/v1/classrooms/{classroom_id}/enrollments",
        json={"student_id": student_id},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["classroom_id"] == classroom_id
    assert body["student_id"] == student_id
    assert body["role"] == "student"


def test_enroll_duplicate_student(engine, client):
    teacher_token, _ = _create_user_and_token(engine, "teacher5", role="teacher")
    resp = client.post(
        "/api/v1/classrooms",
        json={"name": "DupTest", "course_name": "ENG101", "semester": "2026-Fall"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201
    classroom_id = resp.json()["id"]

    _, student_id = _create_user_and_token(engine, "student4", role="student")
    client.post(
        f"/api/v1/classrooms/{classroom_id}/enrollments",
        json={"student_id": student_id},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    resp = client.post(
        f"/api/v1/classrooms/{classroom_id}/enrollments",
        json={"student_id": student_id},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 409, resp.text


# ── 4. POST /api/v1/classroom-sessions ──────────────────────────────────


def test_create_session(engine, client):
    teacher_token, _ = _create_user_and_token(engine, "teacher6", role="teacher")
    resp = client.post(
        "/api/v1/classrooms",
        json={"name": "SessionTest", "course_name": "ENG101", "semester": "2026-Fall"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201
    classroom_id = resp.json()["id"]

    resp = client.post(
        "/api/v1/classroom-sessions",
        json={"classroom_id": classroom_id, "topic": "Warm-up Discussion", "experiment_id": None},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["classroom_id"] == classroom_id
    assert body["topic"] == "Warm-up Discussion"
    assert body["experiment_id"] is None
    assert isinstance(body["id"], int)


# ── 5. POST /api/v1/session-activities ───────────────────────────────────


def test_create_activity(engine, client):
    teacher_token, _ = _create_user_and_token(engine, "teacher7", role="teacher")
    resp = client.post(
        "/api/v1/classrooms",
        json={"name": "ActivityTest", "course_name": "ENG101", "semester": "2026-Fall"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201
    classroom_id = resp.json()["id"]

    _, student_id = _create_user_and_token(engine, "student5", role="student")
    # Enroll the student
    resp = client.post(
        f"/api/v1/classrooms/{classroom_id}/enrollments",
        json={"student_id": student_id},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201

    # Create session
    resp = client.post(
        "/api/v1/classroom-sessions",
        json={"classroom_id": classroom_id, "topic": "Warm-up", "experiment_id": None},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201
    session_id = resp.json()["id"]

    # Create activity
    resp = client.post(
        "/api/v1/session-activities",
        json={
            "classroom_session_id": session_id,
            "student_id": student_id,
            "activity_type": "vocab_lookup",
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["classroom_session_id"] == session_id
    assert body["student_id"] == student_id
    assert body["activity_type"] == "vocab_lookup"


def test_create_activity_other_teacher_forbidden(engine, client):
    owner_token, _ = _create_user_and_token(engine, "teacher7_owner", role="teacher")
    other_token, _ = _create_user_and_token(engine, "teacher7_other", role="teacher")
    resp = client.post(
        "/api/v1/classrooms",
        json={"name": "ActivityOwnerTest", "course_name": "ENG101", "semester": "2026-Fall"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    classroom_id = resp.json()["id"]
    _, student_id = _create_user_and_token(engine, "student5_owner", role="student")
    client.post(
        f"/api/v1/classrooms/{classroom_id}/enrollments",
        json={"student_id": student_id},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    resp = client.post(
        "/api/v1/classroom-sessions",
        json={"classroom_id": classroom_id, "topic": "Owned", "experiment_id": None},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    session_id = resp.json()["id"]

    resp = client.post(
        "/api/v1/session-activities",
        json={
            "classroom_session_id": session_id,
            "student_id": student_id,
            "activity_type": "dialogue",
        },
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403, resp.text


# ── 6. POST /api/v1/activity-turns ───────────────────────────────────────


def test_create_turn_as_teacher(engine, client):
    teacher_token, _ = _create_user_and_token(engine, "teacher8", role="teacher")
    resp = client.post(
        "/api/v1/classrooms",
        json={"name": "TurnTest", "course_name": "ENG101", "semester": "2026-Fall"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    classroom_id = resp.json()["id"]

    _, student_id = _create_user_and_token(engine, "student6", role="student")
    client.post(
        f"/api/v1/classrooms/{classroom_id}/enrollments",
        json={"student_id": student_id},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    resp = client.post(
        "/api/v1/classroom-sessions",
        json={"classroom_id": classroom_id, "topic": "Test", "experiment_id": None},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    session_id = resp.json()["id"]

    resp = client.post(
        "/api/v1/session-activities",
        json={
            "classroom_session_id": session_id,
            "student_id": student_id,
            "activity_type": "dialogue",
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201, resp.text
    activity_id = resp.json()["id"]

    resp = client.post(
        "/api/v1/activity-turns",
        json={
            "session_activity_id": activity_id,
            "turn_type": "teacher",
            "content": "What does X mean?",
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["session_activity_id"] == activity_id
    assert body["user_id"] == student_id  # teacher creates for the student
    assert body["turn_type"] == "teacher"
    assert body["content"] == "What does X mean?"


def test_create_turn_other_teacher_forbidden(engine, client):
    owner_token, _ = _create_user_and_token(engine, "teacher8_owner", role="teacher")
    other_token, _ = _create_user_and_token(engine, "teacher8_other", role="teacher")
    resp = client.post(
        "/api/v1/classrooms",
        json={"name": "TurnOwnerTest", "course_name": "ENG101", "semester": "2026-Fall"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    classroom_id = resp.json()["id"]
    _, student_id = _create_user_and_token(engine, "student6_owner", role="student")
    client.post(
        f"/api/v1/classrooms/{classroom_id}/enrollments",
        json={"student_id": student_id},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    resp = client.post(
        "/api/v1/classroom-sessions",
        json={"classroom_id": classroom_id, "topic": "Owned", "experiment_id": None},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    session_id = resp.json()["id"]
    resp = client.post(
        "/api/v1/session-activities",
        json={
            "classroom_session_id": session_id,
            "student_id": student_id,
            "activity_type": "dialogue",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    activity_id = resp.json()["id"]

    resp = client.post(
        "/api/v1/activity-turns",
        json={"session_activity_id": activity_id, "turn_type": "teacher", "content": "No access"},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403, resp.text


def test_create_turn_as_student_self(engine, client):
    teacher_token, _ = _create_user_and_token(engine, "teacher9", role="teacher")
    resp = client.post(
        "/api/v1/classrooms",
        json={"name": "SelfTurnTest", "course_name": "ENG101", "semester": "2026-Fall"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    classroom_id = resp.json()["id"]

    student_token, student_id = _create_user_and_token(engine, "student7", role="student")
    client.post(
        f"/api/v1/classrooms/{classroom_id}/enrollments",
        json={"student_id": student_id},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    resp = client.post(
        "/api/v1/classroom-sessions",
        json={"classroom_id": classroom_id, "topic": "Test", "experiment_id": None},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    session_id = resp.json()["id"]

    resp = client.post(
        "/api/v1/session-activities",
        json={
            "classroom_session_id": session_id,
            "student_id": student_id,
            "activity_type": "dialogue",
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201, resp.text
    activity_id = resp.json()["id"]

    resp = client.post(
        "/api/v1/activity-turns",
        json={"session_activity_id": activity_id, "turn_type": "student", "content": "Hello"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user_id"] == student_id


def test_create_turn_student_for_other_forbidden(engine, client):
    teacher_token, _ = _create_user_and_token(engine, "teacher10", role="teacher")
    resp = client.post(
        "/api/v1/classrooms",
        json={"name": "ForbidTest", "course_name": "ENG101", "semester": "2026-Fall"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    classroom_id = resp.json()["id"]

    _, student8_id = _create_user_and_token(engine, "student8", role="student")
    student9_token, student9_id = _create_user_and_token(engine, "student9", role="student")
    # Enroll both students
    for sid in (student8_id, student9_id):
        client.post(
            f"/api/v1/classrooms/{classroom_id}/enrollments",
            json={"student_id": sid},
            headers={"Authorization": f"Bearer {teacher_token}"},
        )
    resp = client.post(
        "/api/v1/classroom-sessions",
        json={"classroom_id": classroom_id, "topic": "Test", "experiment_id": None},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    session_id = resp.json()["id"]

    resp = client.post(
        "/api/v1/session-activities",
        json={
            "classroom_session_id": session_id,
            "student_id": student8_id,
            "activity_type": "dialogue",
        },
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert resp.status_code == 201, resp.text
    activity_id = resp.json()["id"]

    # student9 tries to create a turn for student8's activity
    resp = client.post(
        "/api/v1/activity-turns",
        json={"session_activity_id": activity_id, "turn_type": "student", "content": "Hack"},
        headers={"Authorization": f"Bearer {student9_token}"},
    )
    assert resp.status_code == 403, resp.text


# ── 7. Current speaker control ──────────────────────────────────────────


def test_teacher_sets_current_speaker(engine, client):
    seeded = _seed_classroom_session(engine)

    resp = client.post(
        f"/api/v1/classroom-sessions/{seeded['session_id']}/current-speaker",
        json={"student_id": seeded["student_id"]},
        headers={"Authorization": f"Bearer {seeded['teacher_token']}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["classroom_session_id"] == seeded["session_id"]
    assert body["current_speaker_id"] == seeded["student_id"]


def test_student_cannot_set_current_speaker(engine, client):
    seeded = _seed_classroom_session(engine)

    resp = client.post(
        f"/api/v1/classroom-sessions/{seeded['session_id']}/current-speaker",
        json={"student_id": seeded["student_id"]},
        headers={"Authorization": f"Bearer {seeded['student_token']}"},
    )

    assert resp.status_code == 403


def test_cannot_set_unenrolled_student_as_current_speaker(engine, client):
    seeded = _seed_classroom_session(engine)

    resp = client.post(
        f"/api/v1/classroom-sessions/{seeded['session_id']}/current-speaker",
        json={"student_id": seeded["outsider_id"]},
        headers={"Authorization": f"Bearer {seeded['teacher_token']}"},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Student is not enrolled in this classroom"


def test_get_and_clear_current_speaker(engine, client):
    seeded = _seed_classroom_session(engine)

    set_resp = client.post(
        f"/api/v1/classroom-sessions/{seeded['session_id']}/current-speaker",
        json={"student_id": seeded["student_id"]},
        headers={"Authorization": f"Bearer {seeded['teacher_token']}"},
    )
    assert set_resp.status_code == 200

    get_resp = client.get(
        f"/api/v1/classroom-sessions/{seeded['session_id']}/current-speaker",
        headers={"Authorization": f"Bearer {seeded['student_token']}"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["current_speaker_id"] == seeded["student_id"]

    clear_resp = client.delete(
        f"/api/v1/classroom-sessions/{seeded['session_id']}/current-speaker",
        headers={"Authorization": f"Bearer {seeded['teacher_token']}"},
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["current_speaker_id"] is None

    get_after_clear = client.get(
        f"/api/v1/classroom-sessions/{seeded['session_id']}/current-speaker",
        headers={"Authorization": f"Bearer {seeded['student_token']}"},
    )
    assert get_after_clear.status_code == 200
    assert get_after_clear.json()["current_speaker_id"] is None


def test_current_speaker_survives_runtime_reload(engine, client):
    import app.application.classroom_runtime as classroom_runtime

    seeded = _seed_classroom_session(engine)
    response = client.post(
        f"/api/v1/classroom-sessions/{seeded['session_id']}/current-speaker",
        json={"student_id": seeded["student_id"]},
        headers={"Authorization": f"Bearer {seeded['teacher_token']}"},
    )
    assert response.status_code == 200

    reloaded_runtime = importlib.reload(classroom_runtime)
    assert reloaded_runtime.get_current_speaker(seeded["session_id"]) == seeded["student_id"]


def test_concurrent_speaker_updates_and_clear_keep_state_consistent(tmp_path):
    from app.application.classroom_runtime import clear_current_speaker, set_current_speaker
    from app.domain.classroom.models import ClassroomSpeakerState

    db_path = tmp_path / "concurrent_speaker.db"
    concurrent_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    SQLModel.metadata.create_all(concurrent_engine)
    override_engine_for_tests(concurrent_engine)
    seeded = _seed_classroom_session(concurrent_engine)
    _, second_student_id = _create_user_and_token(
        concurrent_engine,
        "turn_second_student",
        "student",
    )
    with Session(concurrent_engine) as session:
        from app.domain.classroom.models import ClassEnrollment

        session.add(
            ClassEnrollment(
                classroom_id=seeded["classroom_id"],
                student_id=second_student_id,
                role="student",
            )
        )
        session.commit()

    assignments = [seeded["student_id"], second_student_id] * 5
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(
            executor.map(
                lambda student_id: set_current_speaker(seeded["session_id"], student_id),
                assignments,
            )
        )

    with Session(concurrent_engine) as session:
        states = session.exec(
            select(ClassroomSpeakerState).where(
                ClassroomSpeakerState.classroom_session_id == seeded["session_id"]
            )
        ).all()
    assert len(states) == 1
    assert states[0].current_speaker_id in {seeded["student_id"], second_student_id}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(clear_current_speaker, seeded["session_id"]),
            executor.submit(
                set_current_speaker,
                seeded["session_id"],
                seeded["student_id"],
            ),
        )
        for future in futures:
            future.result()

    with Session(concurrent_engine) as session:
        states_after_race = session.exec(
            select(ClassroomSpeakerState).where(
                ClassroomSpeakerState.classroom_session_id == seeded["session_id"]
            )
        ).all()
    assert len(states_after_race) <= 1
    if states_after_race:
        assert states_after_race[0].current_speaker_id == seeded["student_id"]


def test_other_teacher_cannot_set_or_clear_current_speaker(engine, client):
    seeded = _seed_classroom_session(engine)
    other_teacher_token, _ = _create_user_and_token(engine, "turn_other_teacher", "teacher")
    path = f"/api/v1/classroom-sessions/{seeded['session_id']}/current-speaker"

    set_response = client.post(
        path,
        json={"student_id": seeded["student_id"]},
        headers={"Authorization": f"Bearer {other_teacher_token}"},
    )
    clear_response = client.delete(
        path,
        headers={"Authorization": f"Bearer {other_teacher_token}"},
    )

    assert set_response.status_code == 403
    assert clear_response.status_code == 403


def test_ended_classroom_session_rejects_speaker_operations(engine, client):
    seeded = _seed_classroom_session(engine)
    other_teacher_token, _ = _create_user_and_token(engine, "ended_other_teacher", "teacher")
    with Session(engine) as session:
        classroom_session = session.get(ClassroomSession, seeded["session_id"])
        assert classroom_session is not None
        classroom_session.ended_at = datetime.now(UTC).replace(tzinfo=None)
        session.add(classroom_session)
        session.commit()

    path = f"/api/v1/classroom-sessions/{seeded['session_id']}/current-speaker"
    headers = {"Authorization": f"Bearer {seeded['teacher_token']}"}
    responses = (
        client.post(path, json={"student_id": seeded["student_id"]}, headers=headers),
        client.get(path, headers=headers),
        client.delete(path, headers=headers),
    )

    assert [response.status_code for response in responses] == [409, 409, 409]
    assert all(response.json()["detail"] == "Classroom session has ended" for response in responses)

    other_headers = {"Authorization": f"Bearer {other_teacher_token}"}
    unauthorized_responses = (
        client.post(path, json={"student_id": seeded["student_id"]}, headers=other_headers),
        client.get(path, headers=other_headers),
        client.delete(path, headers=other_headers),
    )
    assert [response.status_code for response in unauthorized_responses] == [403, 403, 403]


def test_missing_classroom_session_rejects_speaker_operations(engine, client):
    teacher_token, _ = _create_user_and_token(engine, "turn_missing_teacher", "teacher")
    path = "/api/v1/classroom-sessions/999999/current-speaker"
    headers = {"Authorization": f"Bearer {teacher_token}"}

    responses = (
        client.post(path, json={"student_id": 999999}, headers=headers),
        client.get(path, headers=headers),
        client.delete(path, headers=headers),
    )

    assert [response.status_code for response in responses] == [404, 404, 404]
