"""Tests for classroom_access helper module.

Covers every function with normal, edge, and non‑existent cases.
Follows the same SQLite in‑memory pattern as test_classroom_models.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlmodel import Session, SQLModel

from app.application.classroom_access import (
    can_teacher_access_student,
    is_student_in_classroom,
    is_teacher_of_classroom,
    resolve_student_classroom_ids,
)

# Import domain modules so all tables are registered before create_all.
from app.domain import models as _domain_models  # noqa: F401
from app.domain.classroom import models as _classroom_models  # noqa: F401
from app.domain.classroom.models import ClassEnrollment, Classroom
from app.domain.models import User


@pytest.fixture(scope="function")
def engine():
    """Fresh in‑memory SQLite with FK enforcement, all tables created."""
    eng = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    SQLModel.metadata.create_all(eng)
    return eng


# ── helpers ─────────────────────────────────────────────────────────────


def _seed_teacher_student(engine, teacher_idx=1, student_idx=1):
    """Insert one teacher, one student, and one classroom with enrollment.

    Returns (teacher_id, student_id, classroom_id).
    """
    teacher = User(username=f"t{teacher_idx}", email=f"t{teacher_idx}@test.dev", role="teacher")
    student = User(username=f"s{student_idx}", email=f"s{student_idx}@test.dev", role="student")

    with Session(engine) as session:
        session.add_all([teacher, student])
        session.flush()

        cls = Classroom(name=f"Class {teacher_idx}A", course_name="ENG101",
                        teacher_id=teacher.id, semester="2026-Fall")
        session.add(cls)
        session.flush()

        enrollment = ClassEnrollment(classroom_id=cls.id, student_id=student.id, role="student")
        session.add(enrollment)
        session.commit()

        return teacher.id, student.id, cls.id


# ── is_teacher_of_classroom ─────────────────────────────────────────────


class TestIsTeacherOfClassroom:
    def test_teacher_owns_classroom(self, engine):
        teacher_id, _, classroom_id = _seed_teacher_student(engine)
        with Session(engine) as session:
            assert is_teacher_of_classroom(session, teacher_id, classroom_id) is True

    def test_teacher_does_not_own_classroom(self, engine):
        _, _, classroom_id = _seed_teacher_student(engine)
        other_teacher = User(username="other_t", email="other_t@test.dev", role="teacher")
        with Session(engine) as session:
            session.add(other_teacher)
            session.flush()
            assert is_teacher_of_classroom(session, other_teacher.id, classroom_id) is False

    def test_classroom_does_not_exist(self, engine):
        teacher_id, _, _ = _seed_teacher_student(engine)
        with Session(engine) as session:
            assert is_teacher_of_classroom(session, teacher_id, 99999) is False

    def test_classroom_id_none(self, engine):
        """Passing a non‑existent classroom id should return False, not raise."""
        teacher_id, _, _ = _seed_teacher_student(engine)
        with Session(engine) as session:
            assert is_teacher_of_classroom(session, teacher_id, -1) is False


# ── is_student_in_classroom ─────────────────────────────────────────────


class TestIsStudentInClassroom:
    def test_student_enrolled(self, engine):
        _, student_id, classroom_id = _seed_teacher_student(engine)
        with Session(engine) as session:
            assert is_student_in_classroom(session, student_id, classroom_id) is True

    def test_student_not_enrolled(self, engine):
        teacher_id, _, classroom_id = _seed_teacher_student(engine)
        other_student = User(username="other_s", email="other_s@test.dev", role="student")
        with Session(engine) as session:
            session.add(other_student)
            session.flush()
            assert is_student_in_classroom(session, other_student.id, classroom_id) is False

    def test_classroom_does_not_exist(self, engine):
        _, student_id, _ = _seed_teacher_student(engine)
        with Session(engine) as session:
            assert is_student_in_classroom(session, student_id, 99999) is False


# ── can_teacher_access_student ──────────────────────────────────────────


class TestCanTeacherAccessStudent:
    def test_access_granted_with_classroom_id(self, engine):
        teacher_id, student_id, classroom_id = _seed_teacher_student(engine)
        with Session(engine) as session:
            assert (
                can_teacher_access_student(session, teacher_id, student_id, classroom_id)
                is True
            )

    def test_access_denied_wrong_teacher(self, engine):
        _, student_id, classroom_id = _seed_teacher_student(engine)
        other_teacher = User(username="other_t2", email="other_t2@test.dev", role="teacher")
        with Session(engine) as session:
            session.add(other_teacher)
            session.flush()
            assert (
                can_teacher_access_student(
                    session, other_teacher.id, student_id, classroom_id
                )
                is False
            )

    def test_access_denied_student_not_enrolled(self, engine):
        teacher_id, _, classroom_id = _seed_teacher_student(engine)
        other_student = User(username="other_s2", email="other_s2@test.dev", role="student")
        with Session(engine) as session:
            session.add(other_student)
            session.flush()
            assert (
                can_teacher_access_student(
                    session, teacher_id, other_student.id, classroom_id
                )
                is False
            )

    def test_access_granted_without_classroom_id(self, engine):
        """Teacher owns a class the student is enrolled in – should pass."""
        teacher_id, student_id, _ = _seed_teacher_student(engine)
        with Session(engine) as session:
            assert (
                can_teacher_access_student(session, teacher_id, student_id) is True
            )

    def test_access_denied_no_common_classroom(self, engine):
        """Teacher has no classes with the given student."""
        teacher_id, _, _ = _seed_teacher_student(engine, teacher_idx=10, student_idx=10)
        other_teacher = User(username="lonely_t", email="lonely_t@test.dev", role="teacher")
        other_student = User(username="lonely_s", email="lonely_s@test.dev", role="student")
        with Session(engine) as session:
            session.add_all([other_teacher, other_student])
            session.flush()
            assert (
                can_teacher_access_student(session, other_teacher.id, other_student.id)
                is False
            )

    def test_teacher_has_no_classrooms_at_all(self, engine):
        """Teacher with zero classrooms should return False gracefully."""
        new_teacher = User(username="new_t", email="new_t@test.dev", role="teacher")
        new_student = User(username="new_s", email="new_s@test.dev", role="student")
        with Session(engine) as session:
            session.add_all([new_teacher, new_student])
            session.flush()
            assert (
                can_teacher_access_student(session, new_teacher.id, new_student.id)
                is False
            )

    def test_classroom_id_nonexistent(self, engine):
        """Passing a non‑existent classroom_id should deny, not raise."""
        teacher_id, student_id, _ = _seed_teacher_student(engine)
        with Session(engine) as session:
            assert (
                can_teacher_access_student(
                    session, teacher_id, student_id, classroom_id=99999
                )
                is False
            )


# ── resolve_student_classroom_ids ───────────────────────────────────────


class TestResolveStudentClassroomIds:
    def test_student_in_one_classroom(self, engine):
        _, student_id, classroom_id = _seed_teacher_student(engine)
        with Session(engine) as session:
            result = resolve_student_classroom_ids(session, student_id)
            assert result == [classroom_id]

    def test_student_in_multiple_classrooms(self, engine):
        """Student enrolled in two classrooms (different teachers)."""
        teacher1 = User(username="mt1", email="mt1@test.dev", role="teacher")
        teacher2 = User(username="mt2", email="mt2@test.dev", role="teacher")
        student = User(username="ms1", email="ms1@test.dev", role="student")

        with Session(engine) as session:
            session.add_all([teacher1, teacher2, student])
            session.flush()

            cls1 = Classroom(name="Multi A", course_name="ENG101",
                             teacher_id=teacher1.id, semester="2026-Fall")
            cls2 = Classroom(name="Multi B", course_name="MATH101",
                             teacher_id=teacher2.id, semester="2026-Fall")
            session.add_all([cls1, cls2])
            session.flush()

            session.add_all([
                ClassEnrollment(classroom_id=cls1.id, student_id=student.id, role="student"),
                ClassEnrollment(classroom_id=cls2.id, student_id=student.id, role="student"),
            ])
            session.commit()

            result = resolve_student_classroom_ids(session, student.id)
            assert sorted(result) == sorted([cls1.id, cls2.id])

    def test_student_not_enrolled_anywhere(self, engine):
        """Student with no enrollments should return empty list."""
        student = User(username="no_enroll", email="no_enroll@test.dev", role="student")
        with Session(engine) as session:
            session.add(student)
            session.flush()
            assert resolve_student_classroom_ids(session, student.id) == []

    def test_user_id_does_not_exist(self, engine):
        """Non‑existent user id should return empty list."""
        with Session(engine) as session:
            assert resolve_student_classroom_ids(session, 99999) == []
