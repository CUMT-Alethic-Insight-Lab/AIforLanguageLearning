from __future__ import annotations

import importlib
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app.application.classroom_runtime import clear_current_speaker, set_current_speaker
from app.db import init_db, override_engine_for_tests
from app.domain.classroom.models import ClassEnrollment, Classroom, ClassroomSession
from app.domain.models import User
from app.infrastructure.security import create_access_token, hash_password
from app.main import app


def _setup_db(tmp_path: Path):
    db_path = tmp_path / "ws_classroom.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()
    return engine


def _create_user(session: Session, username: str, role: str) -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("Admin1234"),
        role=role,
    )
    session.add(user)
    session.flush()
    return user


def _seed_classroom(engine):
    with Session(engine) as session:
        teacher = _create_user(session, "ws_teacher", "teacher")
        current_student = _create_user(session, "ws_current", "student")
        waiting_student = _create_user(session, "ws_waiting", "student")
        classroom = Classroom(
            name="WS Classroom",
            course_name="ENG101",
            teacher_id=teacher.id,
            semester="2026-Fall",
        )
        session.add(classroom)
        session.flush()
        session.add_all(
            [
                ClassEnrollment(
                    classroom_id=classroom.id,
                    student_id=current_student.id,
                    role="student",
                ),
                ClassEnrollment(
                    classroom_id=classroom.id,
                    student_id=waiting_student.id,
                    role="student",
                ),
            ]
        )
        classroom_session = ClassroomSession(
            classroom_id=classroom.id,
            teacher_id=teacher.id,
            topic="Round robin",
        )
        session.add(classroom_session)
        session.commit()
        session.refresh(classroom_session)
        session.refresh(current_student)
        session.refresh(waiting_student)

        return {
            "classroom_session_id": classroom_session.id,
            "current_student_id": current_student.id,
            "waiting_student_id": waiting_student.id,
            "current_token": create_access_token({"sub": current_student.username}),
            "waiting_token": create_access_token({"sub": waiting_student.username}),
        }


def test_classroom_ws_rejects_non_current_speaker_audio_start(tmp_path: Path) -> None:
    import app.application.classroom_runtime as classroom_runtime

    engine = _setup_db(tmp_path)
    seeded = _seed_classroom(engine)
    set_current_speaker(seeded["classroom_session_id"], seeded["current_student_id"])
    reloaded_runtime = importlib.reload(classroom_runtime)
    assert (
        reloaded_runtime.get_current_speaker(seeded["classroom_session_id"])
        == seeded["current_student_id"]
    )

    client = TestClient(app)
    url = (
        "/ws/v1?session_id=classroom"
        "&conversation_id=conv_classroom_reject"
        f"&classroom_session_id={seeded['classroom_session_id']}"
        f"&token={seeded['waiting_token']}"
    )
    with client.websocket_connect(url) as ws:
        connected = ws.receive_json()
        assert connected["type"] == "TASK_STARTED"

        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "blocked_voice",
                "payload": {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"},
            }
        )

        rejected = ws.receive_json()
        assert rejected["type"] == "CLASSROOM_AUDIO_REJECTED"
        assert rejected["payload"]["reason"] == "not_current_speaker"
        assert rejected["payload"]["current_speaker_id"] == seeded["current_student_id"]

        finished = ws.receive_json()
        assert finished["type"] == "TASK_FINISHED"
        assert finished["payload"]["ok"] is False

    clear_current_speaker(seeded["classroom_session_id"])


def test_classroom_ws_rejects_ended_session_even_with_persisted_speaker(tmp_path: Path) -> None:
    engine = _setup_db(tmp_path)
    seeded = _seed_classroom(engine)
    set_current_speaker(seeded["classroom_session_id"], seeded["current_student_id"])
    with Session(engine) as session:
        classroom_session = session.get(ClassroomSession, seeded["classroom_session_id"])
        assert classroom_session is not None
        classroom_session.ended_at = datetime.now(UTC).replace(tzinfo=None)
        session.add(classroom_session)
        session.commit()

    client = TestClient(app)
    url = (
        "/ws/v1?session_id=classroom_ended"
        "&conversation_id=conv_classroom_ended"
        f"&classroom_session_id={seeded['classroom_session_id']}"
        f"&token={seeded['current_token']}"
    )
    with client.websocket_connect(url) as ws:
        assert ws.receive_json()["type"] == "TASK_STARTED"
        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "ended_voice",
                "payload": {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"},
            }
        )

        rejected = ws.receive_json()
        assert rejected["type"] == "CLASSROOM_AUDIO_REJECTED"
        assert rejected["payload"]["reason"] == "classroom_session_ended"
        assert rejected["payload"]["current_speaker_id"] is None
        assert ws.receive_json()["type"] == "TASK_FINISHED"


def test_non_classroom_ws_audio_start_still_creates_voice_task(tmp_path: Path) -> None:
    _setup_db(tmp_path)

    client = TestClient(app)
    with client.websocket_connect("/ws/v1?session_id=plain&conversation_id=conv_plain") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "TASK_STARTED"

        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "plain_voice",
                "payload": {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"},
            }
        )

        started = ws.receive_json()
        assert started["type"] == "TASK_STARTED"
        assert started["request_id"] == "plain_voice"
