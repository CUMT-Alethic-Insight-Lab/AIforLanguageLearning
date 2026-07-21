"""Minimal classroom/experiment API.

Endpoints (all under ``/api/v1``):

1. POST /classrooms          — create classroom (teacher/admin)
2. GET  /classrooms          — list own or enrolled classrooms
3. POST /classrooms/{id}/enrollments — enroll a student (teacher/admin)
4. POST /classroom-sessions  — create session (teacher/admin)
5. POST /session-activities  — create activity (teacher/admin)
6. POST /activity-turns      — create turn (teacher/admin or self by student)
7. POST/GET/DELETE /classroom-sessions/{id}/current-speaker — classroom turn control
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from ..application.classroom_runtime import (
    clear_current_speaker,
    get_classroom_access,
    get_current_speaker,
    is_student_enrolled,
    set_current_speaker,
)
from ..db import get_session
from ..domain.classroom.models import (
    ActivityTurn,
    ClassEnrollment,
    Classroom,
    ClassroomSession,
    SessionActivity,
)
from ..domain.models import User
from ..infrastructure.dependencies import get_current_user

router = APIRouter(prefix="/api/v1", tags=["classroom"])


# ── request / response models ──────────────────────────────────────────


class CreateClassroomRequest(BaseModel):
    name: str
    course_name: str
    semester: str


class ClassroomOut(BaseModel):
    id: int
    name: str
    course_name: str
    teacher_id: int
    semester: str

    class Config:
        from_attributes = True


class EnrollStudentRequest(BaseModel):
    student_id: int


class CreateSessionRequest(BaseModel):
    classroom_id: int
    topic: str
    experiment_id: int | None = None


class CreateActivityRequest(BaseModel):
    classroom_session_id: int
    student_id: int
    activity_type: str


class CreateTurnRequest(BaseModel):
    session_activity_id: int
    turn_type: str
    content: str


class CurrentSpeakerRequest(BaseModel):
    student_id: int


# ── helpers ──────────────────────────────────────────────────────────────


def _ensure_teacher_or_admin(current_user: User) -> None:
    """Raise 403 if the user is neither teacher nor admin."""
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers and admins can perform this action",
        )


def _get_classroom_or_404(classroom_id: int, session: Session) -> Classroom:
    classroom = session.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Classroom {classroom_id} not found",
        )
    return classroom


def _get_user_or_404(user_id: int, session: Session) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )
    return user


def _get_classroom_session_or_404(session_id: int, session: Session) -> ClassroomSession:
    classroom_session = session.get(ClassroomSession, session_id)
    if classroom_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ClassroomSession {session_id} not found",
        )
    return classroom_session


def _ensure_classroom_session_active(classroom_session: ClassroomSession) -> None:
    if classroom_session.ended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Classroom session has ended",
        )


def _ensure_classroom_session_owner(
    classroom_session: ClassroomSession,
    current_user: User,
) -> None:
    if current_user.role != "admin" and current_user.id != classroom_session.teacher_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this classroom session",
        )


# ── 1. POST /api/v1/classrooms — create classroom ──────────────────────


@router.post("/classrooms", response_model=ClassroomOut, status_code=status.HTTP_201_CREATED)
def create_classroom(
    req: CreateClassroomRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ClassroomOut:
    _ensure_teacher_or_admin(current_user)
    classroom = Classroom(
        name=req.name,
        course_name=req.course_name,
        teacher_id=current_user.id,  # type: ignore[assignment]
        semester=req.semester,
    )
    session.add(classroom)
    session.commit()
    session.refresh(classroom)
    return ClassroomOut.model_validate(classroom)


# ── 2. GET /api/v1/classrooms — list classrooms ────────────────────────


@router.get("/classrooms", response_model=list[ClassroomOut])
def list_classrooms(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ClassroomOut]:
    if current_user.role in ("teacher", "admin"):
        # Teacher/admin: classrooms they own
        classrooms = session.exec(
            select(Classroom).where(Classroom.teacher_id == current_user.id)  # type: ignore[arg-type]
        ).all()
    else:
        # Student: classrooms they are enrolled in
        stmt = (
            select(Classroom)
            .join(ClassEnrollment, ClassEnrollment.classroom_id == Classroom.id)
            .where(ClassEnrollment.student_id == current_user.id)  # type: ignore[arg-type]
        )
        classrooms = session.exec(stmt).all()
    return [ClassroomOut.model_validate(c) for c in classrooms]


# ── 3. POST /api/v1/classrooms/{classroom_id}/enrollments — enroll student ─


@router.post("/classrooms/{classroom_id}/enrollments", status_code=status.HTTP_201_CREATED)
def enroll_student(
    classroom_id: int,
    req: EnrollStudentRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ensure_teacher_or_admin(current_user)
    classroom = _get_classroom_or_404(classroom_id, session)

    # Operator must be the classroom teacher OR an admin
    if current_user.role != "admin" and (current_user.id != classroom.teacher_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the classroom teacher or an admin can enroll students",
        )

    # Verify the student exists
    _get_user_or_404(req.student_id, session)

    # Check not already enrolled
    existing = session.exec(
        select(ClassEnrollment).where(
            ClassEnrollment.classroom_id == classroom_id,
            ClassEnrollment.student_id == req.student_id,
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student is already enrolled in this classroom",
        )

    enrollment = ClassEnrollment(
        classroom_id=classroom_id,
        student_id=req.student_id,
        role="student",
    )
    session.add(enrollment)
    session.commit()
    session.refresh(enrollment)
    return {
        "id": enrollment.id,
        "classroom_id": enrollment.classroom_id,
        "student_id": enrollment.student_id,
        "role": enrollment.role,
    }


# ── 4. POST /api/v1/classroom-sessions ──────────────────────────────────


@router.post("/classroom-sessions", status_code=status.HTTP_201_CREATED)
def create_session(
    req: CreateSessionRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ensure_teacher_or_admin(current_user)
    classroom = _get_classroom_or_404(req.classroom_id, session)

    # Allow only if teacher owns the classroom or is admin
    if current_user.role != "admin" and (current_user.id != classroom.teacher_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this classroom",
        )

    classroom_session = ClassroomSession(
        classroom_id=req.classroom_id,
        teacher_id=current_user.id,  # type: ignore[assignment]
        topic=req.topic,
        experiment_id=req.experiment_id,
    )
    session.add(classroom_session)
    session.commit()
    session.refresh(classroom_session)
    return {
        "id": classroom_session.id,
        "classroom_id": classroom_session.classroom_id,
        "teacher_id": classroom_session.teacher_id,
        "topic": classroom_session.topic,
        "experiment_id": classroom_session.experiment_id,
    }


# ── 5. Current speaker control ───────────────────────────────────────────


@router.post("/classroom-sessions/{session_id}/current-speaker")
def set_classroom_current_speaker(
    session_id: int,
    req: CurrentSpeakerRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    classroom_session = _get_classroom_session_or_404(session_id, session)
    _ensure_classroom_session_owner(classroom_session, current_user)
    _ensure_classroom_session_active(classroom_session)
    _get_user_or_404(req.student_id, session)

    if not is_student_enrolled(
        session,
        classroom_id=classroom_session.classroom_id,
        student_id=req.student_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student is not enrolled in this classroom",
        )

    try:
        set_current_speaker(session_id, req.student_id)
    except ValueError as exc:
        reason = str(exc)
        if reason == "classroom_session_ended":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Classroom session has ended",
            ) from exc
        if reason == "classroom_session_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ClassroomSession {session_id} not found",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student is not enrolled in this classroom",
        ) from exc
    return {
        "classroom_session_id": session_id,
        "current_speaker_id": req.student_id,
    }


@router.get("/classroom-sessions/{session_id}/current-speaker")
def get_classroom_current_speaker(
    session_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    if current_user.id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    classroom_session = _get_classroom_session_or_404(session_id, session)
    access = get_classroom_access(
        session,
        classroom_session_id=session_id,
        user_id=int(current_user.id),
        role=current_user.role,
    )
    if access is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ClassroomSession {session_id} not found",
        )
    if not access.is_teacher_or_admin and not access.is_enrolled_student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot access this classroom session",
        )
    _ensure_classroom_session_active(classroom_session)

    return {
        "classroom_session_id": session_id,
        "current_speaker_id": get_current_speaker(session_id),
    }


@router.delete("/classroom-sessions/{session_id}/current-speaker")
def clear_classroom_current_speaker(
    session_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    classroom_session = _get_classroom_session_or_404(session_id, session)
    _ensure_classroom_session_owner(classroom_session, current_user)
    _ensure_classroom_session_active(classroom_session)
    clear_current_speaker(session_id)
    return {
        "classroom_session_id": session_id,
        "current_speaker_id": None,
    }


# ── 5. POST /api/v1/session-activities ───────────────────────────────────


@router.post("/session-activities", status_code=status.HTTP_201_CREATED)
def create_activity(
    req: CreateActivityRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ensure_teacher_or_admin(current_user)

    # Validate the session exists
    classroom_session = session.get(ClassroomSession, req.classroom_session_id)
    if classroom_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ClassroomSession {req.classroom_session_id} not found",
        )

    if current_user.role != "admin" and current_user.id != classroom_session.teacher_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this classroom session",
        )

    # Validate the student is enrolled in that classroom
    enrollment = session.exec(
        select(ClassEnrollment).where(
            ClassEnrollment.classroom_id == classroom_session.classroom_id,
            ClassEnrollment.student_id == req.student_id,
        )
    ).first()
    if enrollment is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student is not enrolled in this classroom",
        )

    activity = SessionActivity(
        classroom_session_id=req.classroom_session_id,
        student_id=req.student_id,
        activity_type=req.activity_type,
    )
    session.add(activity)
    session.commit()
    session.refresh(activity)
    return {
        "id": activity.id,
        "classroom_session_id": activity.classroom_session_id,
        "student_id": activity.student_id,
        "activity_type": activity.activity_type,
    }


# ── 6. POST /api/v1/activity-turns ───────────────────────────────────────


@router.post("/activity-turns", status_code=status.HTTP_201_CREATED)
def create_turn(
    req: CreateTurnRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    # Validate the activity exists
    activity = session.get(SessionActivity, req.session_activity_id)
    if activity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SessionActivity {req.session_activity_id} not found",
        )

    classroom_session = session.get(ClassroomSession, activity.classroom_session_id)
    if classroom_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ClassroomSession {activity.classroom_session_id} not found",
        )

    # Determine user_id for the turn
    if current_user.role in ("teacher", "admin"):
        if current_user.role != "admin" and current_user.id != classroom_session.teacher_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not own this classroom session",
            )
        # Teacher/admin can create turns for any student in the class
        user_id = activity.student_id
    else:
        # Student can only create turns for themselves
        if current_user.id != activity.student_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only create turns for yourself",
            )
        user_id = current_user.id  # type: ignore[assignment]

    turn = ActivityTurn(
        session_activity_id=req.session_activity_id,
        user_id=user_id,
        turn_type=req.turn_type,
        content=req.content,
    )
    session.add(turn)
    session.commit()
    session.refresh(turn)
    return {
        "id": turn.id,
        "session_activity_id": turn.session_activity_id,
        "user_id": turn.user_id,
        "turn_type": turn.turn_type,
        "content": turn.content,
    }
