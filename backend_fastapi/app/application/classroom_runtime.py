"""Durable classroom turn-taking state for the September classroom pilot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from ..db import get_engine
from ..domain.classroom.models import (
    ClassEnrollment,
    ClassroomSession,
    ClassroomSpeakerState,
)


@dataclass(frozen=True)
class ClassroomAccess:
    classroom_session: ClassroomSession
    is_teacher_or_admin: bool
    is_enrolled_student: bool


def set_current_speaker(classroom_session_id: int, student_id: int) -> None:
    """Atomically assign a session's current speaker.

    The primary key guarantees one row per classroom session. SQLite and
    PostgreSQL use native upsert so concurrent teachers/workers cannot create
    duplicate state rows.
    """

    session_id = int(classroom_session_id)
    speaker_id = int(student_id)
    with Session(get_engine()) as session:
        classroom_session = session.get(ClassroomSession, session_id)
        if classroom_session is None:
            raise ValueError("classroom_session_not_found")
        if classroom_session.ended_at is not None:
            raise ValueError("classroom_session_ended")
        if not is_student_enrolled(
            session,
            classroom_id=classroom_session.classroom_id,
            student_id=speaker_id,
        ):
            raise ValueError("student_not_enrolled")

        values = {
            "classroom_session_id": session_id,
            "current_speaker_id": speaker_id,
            "updated_at": datetime.now(UTC).replace(tzinfo=None),
        }
        dialect = session.get_bind().dialect.name
        if dialect == "sqlite":
            statement = sqlite_insert(ClassroomSpeakerState).values(**values)
            statement = statement.on_conflict_do_update(
                index_elements=[ClassroomSpeakerState.classroom_session_id],
                set_={
                    "current_speaker_id": speaker_id,
                    "updated_at": values["updated_at"],
                },
            )
            session.exec(statement)
        elif dialect == "postgresql":
            statement = postgresql_insert(ClassroomSpeakerState).values(**values)
            statement = statement.on_conflict_do_update(
                index_elements=[ClassroomSpeakerState.classroom_session_id],
                set_={
                    "current_speaker_id": speaker_id,
                    "updated_at": values["updated_at"],
                },
            )
            session.exec(statement)
        else:
            session.merge(ClassroomSpeakerState(**values))
        session.commit()


def get_current_speaker(classroom_session_id: int) -> int | None:
    session_id = int(classroom_session_id)
    with Session(get_engine()) as session:
        classroom_session = session.get(ClassroomSession, session_id)
        if classroom_session is None or classroom_session.ended_at is not None:
            return None
        state = session.get(ClassroomSpeakerState, session_id)
        return int(state.current_speaker_id) if state is not None else None


def clear_current_speaker(classroom_session_id: int) -> None:
    with Session(get_engine()) as session:
        session.exec(
            delete(ClassroomSpeakerState).where(
                ClassroomSpeakerState.classroom_session_id == int(classroom_session_id)
            )
        )
        session.commit()


def check_student_can_speak(classroom_session_id: int, user_id: int | None) -> tuple[bool, str]:
    session_id = int(classroom_session_id)
    with Session(get_engine()) as session:
        classroom_session = session.get(ClassroomSession, session_id)
        if classroom_session is None:
            return False, "classroom_session_not_found"
        if classroom_session.ended_at is not None:
            return False, "classroom_session_ended"
        state = session.get(ClassroomSpeakerState, session_id)
        if state is None:
            return False, "no_current_speaker"
        if user_id is None:
            return False, "anonymous_not_allowed"
        if int(user_id) != int(state.current_speaker_id):
            return False, "not_current_speaker"
        return True, "ok"


def get_classroom_access(
    session: Session,
    *,
    classroom_session_id: int,
    user_id: int,
    role: str,
) -> ClassroomAccess | None:
    classroom_session = session.get(ClassroomSession, int(classroom_session_id))
    if classroom_session is None:
        return None

    is_teacher_or_admin = role == "admin" or int(classroom_session.teacher_id) == int(user_id)
    enrollment = session.exec(
        select(ClassEnrollment).where(
            ClassEnrollment.classroom_id == classroom_session.classroom_id,
            ClassEnrollment.student_id == int(user_id),
        )
    ).first()
    return ClassroomAccess(
        classroom_session=classroom_session,
        is_teacher_or_admin=is_teacher_or_admin,
        is_enrolled_student=enrollment is not None,
    )


def is_student_enrolled(session: Session, *, classroom_id: int, student_id: int) -> bool:
    enrollment = session.exec(
        select(ClassEnrollment).where(
            ClassEnrollment.classroom_id == int(classroom_id),
            ClassEnrollment.student_id == int(student_id),
        )
    ).first()
    return enrollment is not None
