"""CSSCI experiment data export API — minimal viable implementation.

Endpoints:
- GET /api/v1/research/exports/turns.csv?classroom_id=...   → Streaming CSV
- GET /api/v1/research/exports/turns.json?classroom_id=...   → JSON list
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from ..application.classroom_access import is_teacher_of_classroom
from ..db import get_session
from ..domain.classroom.models import (
    ActivityTurn,
    Assessment,
    ClassroomSession,
    ExperimentGroupMember,
    SessionActivity,
)
from ..domain.models import User
from ..infrastructure.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/research", tags=["research"])

# ── helpers ──────────────────────────────────────────────────────────────────


def _ensure_teacher_or_admin(user: User) -> None:
    if user.role not in ("teacher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers and admins can access research exports",
        )


def _resolve_anonymized_id(session: Session, user_id: int) -> tuple[str, bool]:
    """Return (export_id, anonymized).

    Looks up ExperimentGroupMember.anonymized_export_id.
    Falls back to f"student_{user_id}" with anonymized=False.
    """
    stmt = select(ExperimentGroupMember.anonymized_export_id).where(
        ExperimentGroupMember.user_id == user_id,
        ExperimentGroupMember.anonymized_export_id.isnot(None),  # type: ignore[union-attr]
    )
    eid = session.exec(stmt).first()
    if eid:
        return (eid, True)
    return (f"student_{user_id}", False)


def _build_turn_rows(
    session: Session,
    classroom_id: int,
    include_identifiers: bool = False,
) -> list[dict]:
    """Return list of dictionaries with turn export data for a classroom."""
    rows: list[dict] = []

    # Join chain: ActivityTurn → SessionActivity → ClassroomSession → Classroom
    stmt = (
        select(ActivityTurn, SessionActivity, ClassroomSession)
        .join(SessionActivity, ActivityTurn.session_activity_id == SessionActivity.id)
        .join(ClassroomSession, SessionActivity.classroom_session_id == ClassroomSession.id)
        .where(ClassroomSession.classroom_id == classroom_id)
        .order_by(ActivityTurn.started_at)
    )
    results = session.exec(stmt).all()

    for turn, activity, sess in results:
        anon_id, anon_flag = _resolve_anonymized_id(session, turn.user_id)

        # Compute duration_ms
        duration_ms: int | None = None
        if turn.started_at and turn.ended_at:
            delta = turn.ended_at - turn.started_at
            duration_ms = int(delta.total_seconds() * 1000)

        # Assessment join
        score: float | None = None
        assessment_type: str | None = None
        if activity.source_event_id:
            assessment = session.exec(
                select(Assessment)
                .where(Assessment.user_id == turn.user_id)
                .where(Assessment.classroom_id == classroom_id)
                .order_by(Assessment.id.desc())
            ).first()
            if assessment:
                score = assessment.score
                assessment_type = assessment.assessment_type

        row: dict = {
            "anonymized_export_id": anon_id,
            "anonymized": anon_flag,
            "classroom_id": sess.classroom_id,
            "classroom_session_id": sess.id,
            "activity_id": activity.id,
            "turn_id": turn.id,
            "role": turn.turn_type,
            "turn_type": turn.turn_type,
            "started_at": turn.started_at.isoformat() if turn.started_at else None,
            "ended_at": turn.ended_at.isoformat() if turn.ended_at else None,
            "duration_ms": duration_ms,
            "source_event_id": activity.source_event_id,
            "score": score,
            "assessment_type": assessment_type,
        }
        if include_identifiers:
            row["user_id"] = turn.user_id

        rows.append(row)

    return rows


# ── CSV export ────────────────────────────────────────────────────────────────


@router.get("/exports/turns.csv")
def export_turns_csv(
    classroom_id: int = Query(...),
    include_identifiers: bool = Query(False),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _ensure_teacher_or_admin(current_user)

    # Teacher scoped to own classrooms only
    if current_user.role == "teacher" and not is_teacher_of_classroom(
        session, current_user.id, classroom_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only export data from your own classrooms",
        )

    rows = _build_turn_rows(session, classroom_id, include_identifiers=include_identifiers)

    output = io.StringIO()
    fieldnames = [
        "anonymized_export_id",
        "anonymized",
        "classroom_id",
        "classroom_session_id",
        "activity_id",
        "turn_id",
        "role",
        "turn_type",
        "started_at",
        "ended_at",
        "duration_ms",
        "source_event_id",
        "score",
        "assessment_type",
    ]
    if include_identifiers:
        fieldnames.append("user_id")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=turns_classroom_{classroom_id}.csv"},
    )


# ── JSON export ───────────────────────────────────────────────────────────────


@router.get("/exports/turns.json")
def export_turns_json(
    classroom_id: int = Query(...),
    include_identifiers: bool = Query(False),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    _ensure_teacher_or_admin(current_user)

    # Teacher scoped to own classrooms only
    if current_user.role == "teacher" and not is_teacher_of_classroom(
        session, current_user.id, classroom_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only export data from your own classrooms",
        )

    return _build_turn_rows(session, classroom_id, include_identifiers=include_identifiers)
