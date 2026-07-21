"""Classroom / experiment minimal data-model skeleton for the September pilot.

Defines ten SQLModel tables:

- Classroom          – class entity (teacher, course, semester)
- ClassEnrollment    – student/assistant membership in a classroom
- Experiment         – experimental definition (pretest/posttest window)
- ExperimentGroup    – treatment / control group within an experiment
- ExperimentGroupMember – student assignment + consent + anonymised export id
- ClassroomSession   – teacher-led classroom session (topic, timerange)
- ClassroomSpeakerState – durable current-speaker state for a classroom session
- SessionActivity    – individual student activity within a session
- ActivityTurn       – fine-grained turn within an activity (student/teacher/AI)
- Assessment         – pretest / posttest / essay / speaking / vocab assessment record

All tables use ``extend_existing=True`` so that they coexist peacefully with
any previously-defined tables sharing the same name.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

# ── 1. Classroom ────────────────────────────────────────────────────────


class Classroom(SQLModel, table=True):
    __tablename__ = "classrooms"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=256)
    course_name: str = Field(max_length=256)
    teacher_id: int = Field(foreign_key="users.id", index=True)
    semester: str = Field(max_length=64, description='e.g. "2026-Fall"')
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── 2. ClassEnrollment ──────────────────────────────────────────────────


class ClassEnrollment(SQLModel, table=True):
    __tablename__ = "class_enrollments"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    classroom_id: int = Field(foreign_key="classrooms.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    role: str = Field(max_length=32, description='"student" or "assistant"')
    joined_at: datetime = Field(default_factory=datetime.utcnow)


# ── 3. Experiment ───────────────────────────────────────────────────────


class Experiment(SQLModel, table=True):
    __tablename__ = "experiments"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=256)
    classroom_id: int = Field(foreign_key="classrooms.id", index=True)
    description: str = Field(default="")
    started_at: datetime | None = Field(default=None)
    ended_at: datetime | None = Field(default=None)
    status: str = Field(max_length=32, description='"draft"/"active"/"completed"')
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── 4. ExperimentGroup ──────────────────────────────────────────────────


class ExperimentGroup(SQLModel, table=True):
    __tablename__ = "experiment_groups"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    experiment_id: int = Field(foreign_key="experiments.id", index=True)
    name: str = Field(max_length=128, description='e.g. "Treatment A", "Control"')
    is_control: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── 5. ExperimentGroupMember ────────────────────────────────────────────


class ExperimentGroupMember(SQLModel, table=True):
    __tablename__ = "experiment_group_members"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="experiment_groups.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    consent_status: str = Field(
        default="pending",
        max_length=32,
        description='"pending"/"granted"/"declined"',
    )
    anonymized_export_id: str | None = Field(default=None, max_length=128)
    joined_at: datetime | None = Field(default=None)


# ── 6. ClassroomSession ─────────────────────────────────────────────────


class ClassroomSession(SQLModel, table=True):
    __tablename__ = "classroom_sessions"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    classroom_id: int = Field(foreign_key="classrooms.id", index=True)
    experiment_id: int | None = Field(default=None, foreign_key="experiments.id", index=True)
    teacher_id: int = Field(foreign_key="users.id", index=True)
    topic: str = Field(default="", max_length=512)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── 7. ClassroomSpeakerState ────────────────────────────────────────────


class ClassroomSpeakerState(SQLModel, table=True):
    """The single durable current-speaker row for a classroom session."""

    __tablename__ = "classroom_speaker_states"
    __table_args__ = {"extend_existing": True}

    classroom_session_id: int = Field(
        primary_key=True,
        foreign_key="classroom_sessions.id",
    )
    current_speaker_id: int = Field(foreign_key="users.id", index=True)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 8. SessionActivity ──────────────────────────────────────────────────


class SessionActivity(SQLModel, table=True):
    __tablename__ = "session_activities"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    classroom_session_id: int = Field(foreign_key="classroom_sessions.id", index=True)
    student_id: int = Field(foreign_key="users.id", index=True)
    activity_type: str = Field(
        max_length=64,
        description='"vocab_lookup"/"essay_submit"/"dialogue_turn"/"assessment" etc.',
    )
    source_event_id: str | None = Field(
        default=None,
        max_length=128,
        description="conversation_id or submission id",
    )
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── 9. ActivityTurn ─────────────────────────────────────────────────────


class ActivityTurn(SQLModel, table=True):
    __tablename__ = "activity_turns"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_activity_id: int = Field(foreign_key="session_activities.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    turn_type: str = Field(max_length=32, description='"student"/"teacher"/"ai"')
    content: str = Field(default="")
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: datetime | None = Field(default=None)


# ── 10. Assessment ──────────────────────────────────────────────────────


class Assessment(SQLModel, table=True):
    __tablename__ = "assessments"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    experiment_id: int | None = Field(default=None, foreign_key="experiments.id", index=True)
    classroom_id: int | None = Field(default=None, foreign_key="classrooms.id", index=True)
    assessment_type: str = Field(
        max_length=64,
        description='"pretest"/"posttest"/"essay"/"speaking"/"vocab"',
    )
    score: float | None = Field(default=None)
    result_data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    submitted_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
