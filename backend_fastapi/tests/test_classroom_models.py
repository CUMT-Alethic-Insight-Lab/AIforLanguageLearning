"""Tests for classroom/experiment data-model skeleton.

Verifies:
1. All nine tables are registered in SQLModel.metadata
2. create_all succeeds on an in-memory SQLite database
3. Foreign-key constraints are enforced (invalid FK raises IntegrityError)
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel

# Import domain + classroom modules so that ALL referenced tables (users, etc.)
# are registered in SQLModel.metadata before create_all.
from app.domain import models as _domain_models  # noqa: F401
from app.domain.classroom import models as _classroom_models  # noqa: F401


EXPECTED_TABLES = {
    "classrooms",
    "class_enrollments",
    "experiments",
    "experiment_groups",
    "experiment_group_members",
    "classroom_sessions",
    "session_activities",
    "activity_turns",
    "assessments",
}


@pytest.fixture(scope="function")
def engine():
    """Return a fresh in-memory SQLite engine with FK enforcement enabled."""
    eng = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    SQLModel.metadata.create_all(eng)
    return eng


# ── 1. metadata registration ────────────────────────────────────────────


def test_all_tables_registered():
    """Every classroom table must appear in SQLModel.metadata."""
    registered = set(SQLModel.metadata.tables.keys())
    missing = EXPECTED_TABLES - registered
    assert not missing, f"Missing tables: {missing}"


# ── 2. create_all idempotency ───────────────────────────────────────────


def test_create_all_on_sqlite(engine):
    """create_all must succeed on a fresh SQLite database."""
    # The fixture already called create_all; calling it again is a no-op.
    SQLModel.metadata.create_all(engine)

    # Smoke: list table names
    from sqlalchemy import inspect

    inspector = inspect(engine)
    actual = set(inspector.get_table_names())
    missing = EXPECTED_TABLES - actual
    assert not missing, f"Tables not created: {missing}"


# ── 3. FK constraint enforcement ────────────────────────────────────────


def test_invalid_classroom_fk_raises(engine):
    """Inserting an enrollment for a non-existent classroom must fail."""
    from app.domain.classroom.models import ClassEnrollment

    bad = ClassEnrollment(classroom_id=9999, student_id=9999, role="student")
    with Session(engine) as session:
        session.add(bad)
        with pytest.raises(IntegrityError):
            session.commit()
    # Rollback succeeded ― session usable again
    with Session(engine) as session:
        from sqlmodel import select as sql_select

        result = session.exec(
            sql_select(ClassEnrollment).where(ClassEnrollment.classroom_id == 9999)
        ).first()
        assert result is None


def test_invalid_user_fk_in_enrollment_raises(engine):
    """Inserting an enrollment for a non-existent user must fail."""
    from app.domain.classroom.models import ClassEnrollment, Classroom
    from app.domain.models import User

    # Create a valid user (teacher) and classroom first so that classroom FK passes.
    teacher = User(username="t2", email="t2@test.dev", role="teacher")
    with Session(engine) as session:
        session.add(teacher)
        session.commit()
        session.refresh(teacher)

    cls = Classroom(name="Test", course_name="ENG101", teacher_id=teacher.id, semester="2026-Fall")
    with Session(engine) as session:
        session.add(cls)
        session.commit()
        session.refresh(cls)

    bad = ClassEnrollment(classroom_id=cls.id, student_id=9999, role="student")
    with Session(engine) as session:
        session.add(bad)
        with pytest.raises(IntegrityError):
            session.commit()


def test_invalid_experiment_group_fk_raises(engine):
    """ExperimentGroupMember referencing non-existent group must fail."""
    from app.domain.classroom.models import ExperimentGroupMember

    bad = ExperimentGroupMember(group_id=9999, user_id=9999)
    with Session(engine) as session:
        session.add(bad)
        with pytest.raises(IntegrityError):
            session.commit()


def test_invalid_session_activity_fk_raises(engine):
    """SessionActivity referencing non-existent session must fail."""
    from app.domain.classroom.models import SessionActivity

    bad = SessionActivity(
        classroom_session_id=9999, student_id=9999, activity_type="vocab_lookup"
    )
    with Session(engine) as session:
        session.add(bad)
        with pytest.raises(IntegrityError):
            session.commit()


def test_invalid_activity_turn_fk_raises(engine):
    """ActivityTurn referencing non-existent session_activity must fail."""
    from app.domain.classroom.models import ActivityTurn

    bad = ActivityTurn(session_activity_id=9999, user_id=9999, turn_type="student")
    with Session(engine) as session:
        session.add(bad)
        with pytest.raises(IntegrityError):
            session.commit()


# ── 4. happy-path insert ────────────────────────────────────────────────


def test_full_chain_insert(engine):
    """Insert a realistic chain: Classroom → Session → Activity → Turn."""
    from app.domain.classroom.models import (
        ActivityTurn,
        Classroom,
        ClassroomSession,
        SessionActivity,
    )
    from app.domain.models import User

    with Session(engine) as session:
        teacher = User(username="t1", email="t1@test.dev", role="teacher")
        student = User(username="s1", email="s1@test.dev", role="student")
        session.add_all([teacher, student])
        session.flush()  # assign ids

        cls = Classroom(name="ENG101 Section A", course_name="ENG101", teacher_id=teacher.id, semester="2026-Fall")
        session.add(cls)
        session.flush()

        sess = ClassroomSession(classroom_id=cls.id, teacher_id=teacher.id, topic="Warm-up")
        session.add(sess)
        session.flush()

        act = SessionActivity(
            classroom_session_id=sess.id,
            student_id=student.id,
            activity_type="vocab_lookup",
        )
        session.add(act)
        session.flush()

        turn = ActivityTurn(
            session_activity_id=act.id,
            user_id=student.id,
            turn_type="student",
            content="What does 'mitigate' mean?",
        )
        session.add(turn)
        session.commit()

        # Refresh for assertions (all still bound)
        for obj in (turn, act, sess, cls):
            session.refresh(obj)

        # Verify chain
        assert turn.id is not None
        assert turn.session_activity_id == act.id
        assert act.classroom_session_id == sess.id
        assert sess.classroom_id == cls.id


def test_experiment_group_member_consent_defaults(engine):
    """consent_status defaults to 'pending' and anonymized_export_id is None."""
    from app.domain.classroom.models import (
        Experiment,
        ExperimentGroup,
        ExperimentGroupMember,
        Classroom,
    )
    from app.domain.models import User

    with Session(engine) as session:
        teacher = User(username="t3", email="t3@test.dev", role="teacher")
        user = User(username="e1", email="e1@test.dev", role="student")
        session.add_all([teacher, user])
        session.flush()

        cls = Classroom(name="EXP101", course_name="EXP101", teacher_id=teacher.id, semester="2026-Fall")
        session.add(cls)
        session.flush()

        exp = Experiment(name="Pilot 1", classroom_id=cls.id, status="draft")
        session.add(exp)
        session.flush()

        grp = ExperimentGroup(name="Treatment A", experiment_id=exp.id)
        session.add(grp)
        session.flush()

        member = ExperimentGroupMember(group_id=grp.id, user_id=user.id)
        session.add(member)
        session.commit()

        session.refresh(member)

        assert member.consent_status == "pending"
        assert member.anonymized_export_id is None


def test_assessment_result_data_json(engine):
    """result_data JSON column stores and retrieves a dict."""
    from app.domain.classroom.models import Assessment
    from app.domain.models import User

    payload = {"fluency": 85, "accuracy": 92, "notes": ["good pacing"]}

    with Session(engine) as session:
        user = User(username="a1", email="a1@test.dev", role="student")
        session.add(user)
        session.flush()

        a = Assessment(
            user_id=user.id,
            assessment_type="pretest",
            score=88.5,
            result_data=payload,
        )
        session.add(a)
        session.commit()
        session.refresh(a)

        assert a.result_data == payload
        assert a.score == 88.5
        assert a.assessment_type == "pretest"
