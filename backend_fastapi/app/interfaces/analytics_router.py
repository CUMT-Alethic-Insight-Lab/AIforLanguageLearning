"""教师端学情分析 API 路由。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session, select

from ..application.analytics.facade import (
    assign_student_class,
    build_class_dashboard_payload,
    build_class_overview_payload,
    build_class_students_payload,
    build_student_profile_payload,
    build_student_report_payload,
    build_weekly_report_payload,
    list_student_class_assignments,
)
from ..application.analytics.orchestration import (
    generate_student_longitudinal_summary,
    get_class_population_counts,
    resolve_class_id_for_user,
)
from ..application.classroom_access import (
    can_teacher_access_student,
    is_teacher_of_classroom,
)
from ..db import get_session
from ..domain.analytics.models import InterventionTask, StudentDailySummary
from ..domain.classroom.models import ClassEnrollment, Classroom
from ..domain.models import User
from ..infrastructure.dependencies import get_current_user
from ..infrastructure.rbac import Role, require_role

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


class StudentListItem(BaseModel):
    user_id: int
    username: str | None = None
    risk_tags: list[str]
    latest_score: float | None = None
    last_active_date: date | None = None
    class_id: str | None = None


class ChartData(BaseModel):
    type: str
    title: str
    labels: list[str]
    datasets: list[dict[str, Any]]


class StudentProfileData(BaseModel):
    class_id: str | None = None
    level: str | None = None
    goals: list[str] = []
    interests: list[str] = []


class LongitudinalSummaryPayload(BaseModel):
    window_start: date
    window_end: date
    window_days: int
    llm_summary: str
    risk_flags: list[str] = []
    strength_flags: list[str] = []
    metric_deltas: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []


class StudentProfileResponse(BaseModel):
    user_id: int
    username: str | None = None
    profile: StudentProfileData | None = None
    time_series: list[dict[str, Any]]
    latest_summary: dict[str, Any] | None = None
    llm_narrative: str | None = None
    longitudinal_summary: LongitudinalSummaryPayload | None = None
    charts: dict[str, Any] = {}
    analysis_methodology: dict[str, Any] = {}
    data_quality: dict[str, Any] = {}


class StudentReportResponse(BaseModel):
    user_id: int
    date: date
    agent_reports: list[dict[str, Any]]


class ClassOverviewResponse(BaseModel):
    class_id: str
    date: date
    # Compatibility alias: now corrected to mean the enrolled class roster.
    total_students: int
    enrolled_students: int
    active_students: int
    analyzed_students: int
    risk_count: int
    avg_vocab_growth: float | None = None
    avg_grammar_decay: float | None = None
    ability_distribution: dict[str, int]
    trend_7d: dict[str, Any]
    recent_analysis: dict[str, Any] | None = None
    charts: dict[str, Any] = {}


class InterventionCreateRequest(BaseModel):
    student_id: int
    class_id: str | None = None
    title: str
    description: str = ""
    suggestion: dict[str, Any] = {}
    priority: str = "normal"
    due_date: date | None = None


class InterventionResponse(BaseModel):
    id: int
    student_id: int
    class_id: str | None = None
    agent_type: str
    title: str
    description: str
    status: str
    priority: str
    due_date: date | None = None
    created_at: date


class WeeklyReportResponse(BaseModel):
    class_id: str
    week_start: date
    content: str
    generated_at: date
    evidence: list[dict[str, Any]] = []


class ClassDashboardResponse(BaseModel):
    class_id: str
    overview: ClassOverviewResponse
    students: list[StudentListItem]
    weekly: WeeklyReportResponse | None = None


class StudentDashboardResponse(BaseModel):
    student_id: int
    profile: StudentProfileResponse
    report: StudentReportResponse


class StudentClassAssignmentItem(BaseModel):
    user_id: int
    username: str | None = None
    role: str
    class_id: str | None = None
    latest_summary_class_id: str | None = None
    latest_score: float | None = None
    risk_tags: list[str] = []
    last_active_date: date | None = None
    level: str | None = None


class StudentClassAssignmentUpdateRequest(BaseModel):
    class_id: str | None = None
    note: str = ""
    sync_related_records: bool = True


class StudentClassAssignmentUpdateResponse(BaseModel):
    user_id: int
    username: str | None = None
    previous_class_id: str | None = None
    class_id: str | None = None
    changed: bool
    sync_stats: dict[str, int]


# ── Access control helpers ────────────────────────────────────────────────


def _is_admin(current_user: User) -> bool:
    """Check if the user has admin role (full access)."""
    return current_user.role == "admin"


def _parse_classroom_id(class_id: str | None) -> int | None:
    """Try to parse a class_id string to int Classroom.id.

    Returns None if the string is not a pure numeric value.
    Legacy class_ids like ``"class_101"`` are non-numeric and cannot be
    mapped to the new Classroom table.
    """
    if class_id is None:
        return None
    try:
        return int(class_id)
    except (ValueError, TypeError):
        return None


def _ensure_teacher_can_access_classroom(
    session: Session,
    current_user: User,
    class_id: str,
) -> None:
    """Raise 403 if current_user is a teacher who doesn't own this classroom.

    Admin always passes.  Non-numeric *class_id* → teacher 403 (conservative).
    """
    if _is_admin(current_user):
        return

    numeric_id = _parse_classroom_id(class_id)
    if numeric_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Teacher access denied: class_id '{class_id}' "
                   f"cannot be mapped to a classroom",
        )

    if not is_teacher_of_classroom(session, current_user.id or 0, numeric_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Teacher does not own classroom {class_id}",
        )


def _ensure_teacher_can_access_student(
    session: Session,
    current_user: User,
    student_id: int,
    classroom_id: str | None = None,
) -> None:
    """Raise 403 if teacher cannot access *student_id*.

    Admin always passes.
    When *classroom_id* is provided and non-numeric, teacher gets 403.
    """
    if _is_admin(current_user):
        return

    numeric_classroom_id: int | None = None
    if classroom_id is not None:
        numeric_classroom_id = _parse_classroom_id(classroom_id)
        if numeric_classroom_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Teacher access denied: class_id '{classroom_id}' "
                       f"cannot be mapped to a classroom",
            )

    if not can_teacher_access_student(
        session, current_user.id or 0, student_id, numeric_classroom_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Teacher {current_user.username} cannot access "
                   f"student {student_id} data",
        )


def _resolve_student_scope_class_id(
    session: Session,
    current_user: User,
    student_id: int,
    requested_class_id: str | None,
) -> str | None:
    """Resolve one authorized class scope for a student analytics query."""
    if requested_class_id is not None:
        _ensure_teacher_can_access_student(
            session,
            current_user,
            student_id,
            requested_class_id,
        )
        return requested_class_id

    if _is_admin(current_user):
        return resolve_class_id_for_user(session, student_id)

    owned_classroom_ids = list(
        session.exec(
            select(ClassEnrollment.classroom_id)
            .join(Classroom, Classroom.id == ClassEnrollment.classroom_id)
            .where(ClassEnrollment.student_id == student_id)
            .where(ClassEnrollment.role == "student")
            .where(Classroom.teacher_id == (current_user.id or 0))
            .order_by(ClassEnrollment.id.desc())
        )
    )
    owned_classroom_ids = list(dict.fromkeys(owned_classroom_ids))
    if not owned_classroom_ids:
        _ensure_teacher_can_access_student(session, current_user, student_id)
        return None
    if len(owned_classroom_ids) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student belongs to multiple accessible classrooms; specify class_id",
        )
    return str(owned_classroom_ids[0])


async def _scope_student_profile_payload(
    session: Session,
    payload: dict[str, Any],
    *,
    student_id: int,
    class_id: str | None,
    target_date: date,
    days: int,
) -> dict[str, Any]:
    """Remove summaries outside the authorized class before serialization."""
    if class_id is None:
        return payload

    start_date = target_date - timedelta(days=days - 1)
    scoped_summaries = list(
        session.exec(
            select(StudentDailySummary)
            .where(StudentDailySummary.user_id == student_id)
            .where(StudentDailySummary.class_id == class_id)
            .where(StudentDailySummary.summary_date >= start_date)
            .where(StudentDailySummary.summary_date <= target_date)
            .order_by(StudentDailySummary.summary_date)
        )
    )
    allowed_dates = {str(summary.summary_date) for summary in scoped_summaries}
    original_series = payload.get("time_series") or []
    payload["time_series"] = [
        item for item in original_series if str(item.get("date")) in allowed_dates
    ]

    latest_payload = payload.get("latest_summary")
    if not latest_payload or latest_payload.get("class_id") != class_id:
        payload["latest_summary"] = None
        payload["llm_narrative"] = None

    if len(payload["time_series"]) != len(original_series):
        # Radar/bar charts contain values without class identifiers and cannot
        # be safely filtered after facade assembly.
        payload["charts"] = {}

    longitudinal = await generate_student_longitudinal_summary(
        session,
        student_id,
        class_id=class_id,
        end_date=target_date,
        window_days=days,
    )
    payload["longitudinal_summary"] = {
        "window_start": longitudinal.window_start,
        "window_end": longitudinal.window_end,
        "window_days": longitudinal.window_days,
        "llm_summary": longitudinal.llm_summary,
        "risk_flags": longitudinal.risk_flags,
        "strength_flags": longitudinal.strength_flags,
        "metric_deltas": longitudinal.metric_deltas,
        "evidence": longitudinal.evidence,
    }
    data_quality = dict(payload.get("data_quality") or {})
    data_quality.update(
        {
            "class_id": class_id,
            "days_with_summary": len(scoped_summaries),
        }
    )
    payload["data_quality"] = data_quality
    return payload


# ── Routes ───────────────────────────────────────────────────────────────


@router.get("/class/{class_id}/dashboard", response_model=ClassDashboardResponse)
@require_role(Role.TEACHER)
async def class_dashboard(
    class_id: str,
    target_date: date | None = Query(default=None, description="目标日期，默认为昨天"),
    recent_days: int = Query(default=3, ge=3, le=7, description="班级近况分析窗口"),
    include_weekly: bool = Query(default=False, description="是否连同周报一并返回"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ClassDashboardResponse:
    _ensure_teacher_can_access_classroom(session, current_user, class_id)
    effective_date = target_date or (date.today() - timedelta(days=1))
    payload = await build_class_dashboard_payload(
        session,
        class_id=class_id,
        target_date=target_date,
        recent_days=recent_days,
        include_weekly=include_weekly,
    )
    population = get_class_population_counts(session, class_id, effective_date)
    payload["overview"].update(population)
    session.commit()
    return ClassDashboardResponse.model_validate(payload)


@router.get("/student/{student_id}/dashboard", response_model=StudentDashboardResponse)
@require_role(Role.TEACHER)
async def student_dashboard(
    student_id: int,
    class_id: str | None = Query(default=None, description="班级范围；多班学生必须指定"),
    days: int = Query(default=14, ge=3, le=90, description="回溯天数"),
    target_date: date | None = Query(default=None, description="默认昨天"),
    llm_enhance: bool = Query(default=False, description="是否润色 Agent 报告"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StudentDashboardResponse:
    scoped_class_id = _resolve_student_scope_class_id(
        session,
        current_user,
        student_id,
        class_id,
    )
    effective_date = target_date or (date.today() - timedelta(days=1))
    try:
        profile = await build_student_profile_payload(
            session,
            student_id=student_id,
            days=days,
            target_date=target_date,
        )
        profile = await _scope_student_profile_payload(
            session,
            profile,
            student_id=student_id,
            class_id=scoped_class_id,
            target_date=effective_date,
            days=days,
        )
        canonical_class_id = resolve_class_id_for_user(session, student_id)
        if canonical_class_id == scoped_class_id:
            report = await build_student_report_payload(
                session,
                student_id=student_id,
                target_date=target_date,
                llm_enhance=llm_enhance,
            )
        else:
            report = {
                "user_id": student_id,
                "date": effective_date,
                "agent_reports": [],
            }
        payload = {"student_id": student_id, "profile": profile, "report": report}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return StudentDashboardResponse.model_validate(payload)


@router.get("/class/{class_id}/overview", response_model=ClassOverviewResponse)
@require_role(Role.TEACHER)
async def class_overview(
    class_id: str,
    target_date: date | None = Query(default=None, description="目标日期，默认为昨天"),
    recent_days: int = Query(default=3, ge=3, le=7, description="班级近况分析窗口"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ClassOverviewResponse:
    _ensure_teacher_can_access_classroom(session, current_user, class_id)
    effective_date = target_date or (date.today() - timedelta(days=1))
    payload = await build_class_overview_payload(
        session,
        class_id=class_id,
        target_date=target_date,
        recent_days=recent_days,
    )
    payload.update(get_class_population_counts(session, class_id, effective_date))
    session.commit()
    return ClassOverviewResponse.model_validate(payload)


@router.get("/class/{class_id}/students", response_model=list[StudentListItem])
@require_role(Role.TEACHER)
async def class_students(
    class_id: str,
    target_date: date | None = Query(default=None, description="目标日期，默认为昨天"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[StudentListItem]:
    _ensure_teacher_can_access_classroom(session, current_user, class_id)
    payload = build_class_students_payload(session, class_id=class_id, target_date=target_date)
    return [StudentListItem.model_validate(item) for item in payload]


@router.get("/student/{student_id}/profile", response_model=StudentProfileResponse)
@require_role(Role.TEACHER)
async def student_profile(
    student_id: int,
    class_id: str | None = Query(default=None, description="班级范围；多班学生必须指定"),
    days: int = Query(default=14, ge=3, le=90, description="回溯天数"),
    target_date: date | None = Query(default=None, description="默认昨天"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StudentProfileResponse:
    scoped_class_id = _resolve_student_scope_class_id(
        session,
        current_user,
        student_id,
        class_id,
    )
    effective_date = target_date or (date.today() - timedelta(days=1))
    payload = await build_student_profile_payload(
        session,
        student_id=student_id,
        days=days,
        target_date=target_date,
    )
    payload = await _scope_student_profile_payload(
        session,
        payload,
        student_id=student_id,
        class_id=scoped_class_id,
        target_date=effective_date,
        days=days,
    )
    session.commit()
    return StudentProfileResponse.model_validate(payload)


@router.get("/student/{student_id}/report", response_model=StudentReportResponse)
@require_role(Role.TEACHER)
async def student_report(
    student_id: int,
    class_id: str | None = Query(default=None, description="班级范围；多班学生必须指定"),
    target_date: date | None = Query(default=None, description="目标日期，默认为昨天"),
    llm_enhance: bool = Query(default=False, description="是否润色 Agent 报告"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StudentReportResponse:
    scoped_class_id = _resolve_student_scope_class_id(
        session,
        current_user,
        student_id,
        class_id,
    )
    canonical_class_id = resolve_class_id_for_user(session, student_id)
    if scoped_class_id != canonical_class_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No class-scoped agent report is available for the requested classroom",
        )
    try:
        payload = await build_student_report_payload(
            session,
            student_id=student_id,
            target_date=target_date,
            llm_enhance=llm_enhance,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return StudentReportResponse.model_validate(payload)


@router.get("/class-assignments", response_model=list[StudentClassAssignmentItem])
@require_role(Role.TEACHER)
async def get_class_assignments(
    class_id: str | None = Query(default=None, description="按班级过滤"),
    include_unassigned: bool = Query(default=False, description="是否包含未分班学生"),
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[StudentClassAssignmentItem]:
    # Teacher must supply a class_id they own; admin may omit it
    if not _is_admin(current_user):
        if class_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Teacher must specify a class_id to list class assignments",
            )
        _ensure_teacher_can_access_classroom(session, current_user, class_id)
    payload = list_student_class_assignments(
        session,
        class_id=class_id,
        include_unassigned=include_unassigned,
        limit=limit,
    )
    return [StudentClassAssignmentItem.model_validate(item) for item in payload]


@router.post(
    "/student/{student_id}/class-assignment",
    response_model=StudentClassAssignmentUpdateResponse,
)
@require_role(Role.TEACHER)
async def update_student_class_assignment(
    student_id: int,
    req: StudentClassAssignmentUpdateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StudentClassAssignmentUpdateResponse:
    # Teacher must be able to access the student and own the target class
    if not _is_admin(current_user):
        _ensure_teacher_can_access_student(session, current_user, student_id)
        if req.class_id is not None:
            _ensure_teacher_can_access_classroom(session, current_user, req.class_id)
    try:
        payload = await assign_student_class(
            session,
            user_id=student_id,
            class_id=req.class_id,
            operator_user_id=current_user.id,
            note=req.note,
            sync_related_records=req.sync_related_records,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return StudentClassAssignmentUpdateResponse.model_validate(payload)


@router.post(
    "/intervention",
    response_model=InterventionResponse,
    status_code=status.HTTP_201_CREATED,
)
@require_role(Role.TEACHER)
async def create_intervention(
    req: InterventionCreateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> InterventionResponse:
    _ensure_teacher_can_access_student(
        session, current_user, req.student_id, req.class_id
    )
    task = InterventionTask(
        student_id=req.student_id,
        class_id=req.class_id,
        agent_type="manual",
        title=req.title,
        description=req.description,
        suggestion=req.suggestion,
        status="pending",
        priority=req.priority,
        due_date=req.due_date,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return InterventionResponse(
        id=task.id,
        student_id=task.student_id,
        class_id=task.class_id,
        agent_type=task.agent_type,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        due_date=task.due_date,
        created_at=task.created_at.date(),
    )


@router.post("/student/{student_id}/llm-profile", response_model=dict[str, Any])
@require_role(Role.TEACHER)
async def generate_llm_profile(
    student_id: int,
    class_id: str | None = Query(default=None, description="班级范围；多班学生必须指定"),
    days: int = Query(default=14, ge=3, le=90, description="回溯天数"),
    target_date: date | None = Query(default=None, description="默认昨天"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    scoped_class_id = _resolve_student_scope_class_id(
        session,
        current_user,
        student_id,
        class_id,
    )
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
    summary = await generate_student_longitudinal_summary(
        session,
        student_id,
        class_id=scoped_class_id,
        end_date=target_date,
        window_days=days,
        force=True,
    )
    session.commit()
    return {
        "user_id": student_id,
        "days": days,
        "window_start": str(summary.window_start),
        "window_end": str(summary.window_end),
        "narrative": summary.llm_summary,
        "risk_flags": summary.risk_flags,
        "strength_flags": summary.strength_flags,
        "generated_at": summary.updated_at.isoformat(),
    }


@router.get("/intervention/{task_id}", response_model=InterventionResponse)
@require_role(Role.TEACHER)
async def get_intervention(
    task_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> InterventionResponse:
    task = session.exec(select(InterventionTask).where(InterventionTask.id == task_id)).first()
    if task is None:
        raise HTTPException(status_code=404, detail=f"Intervention task {task_id} not found")
    _ensure_teacher_can_access_student(
        session, current_user, task.student_id, task.class_id
    )
    return InterventionResponse(
        id=task.id,
        student_id=task.student_id,
        class_id=task.class_id,
        agent_type=task.agent_type,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        due_date=task.due_date,
        created_at=task.created_at.date(),
    )


@router.get("/class/{class_id}/weekly", response_model=WeeklyReportResponse)
@require_role(Role.TEACHER)
async def class_weekly_report(
    class_id: str,
    week_start: date | None = Query(default=None, description="周报起始日期（周日）"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WeeklyReportResponse:
    _ensure_teacher_can_access_classroom(session, current_user, class_id)
    payload = await build_weekly_report_payload(session, class_id=class_id, week_start=week_start)
    session.commit()
    return WeeklyReportResponse.model_validate(payload)
