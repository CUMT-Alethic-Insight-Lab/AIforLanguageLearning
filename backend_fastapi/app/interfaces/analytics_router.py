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
    build_student_dashboard_payload,
    build_student_profile_payload,
    build_student_report_payload,
    build_weekly_report_payload,
    list_student_class_assignments,
)
from ..application.analytics.orchestration import (
    generate_student_longitudinal_summary,
    resolve_class_id_for_user,
)
from ..db import get_session
from ..domain.analytics.models import InterventionTask
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
    total_students: int
    active_students: int
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
    payload = await build_class_dashboard_payload(
        session,
        class_id=class_id,
        target_date=target_date,
        recent_days=recent_days,
        include_weekly=include_weekly,
    )
    session.commit()
    return ClassDashboardResponse.model_validate(payload)


@router.get("/student/{student_id}/dashboard", response_model=StudentDashboardResponse)
@require_role(Role.TEACHER)
async def student_dashboard(
    student_id: int,
    days: int = Query(default=14, ge=3, le=90, description="回溯天数"),
    target_date: date | None = Query(default=None, description="默认昨天"),
    llm_enhance: bool = Query(default=False, description="是否润色 Agent 报告"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StudentDashboardResponse:
    try:
        payload = await build_student_dashboard_payload(
            session,
            student_id=student_id,
            days=days,
            target_date=target_date,
            llm_enhance=llm_enhance,
        )
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
    payload = await build_class_overview_payload(
        session,
        class_id=class_id,
        target_date=target_date,
        recent_days=recent_days,
    )
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
    payload = build_class_students_payload(session, class_id=class_id, target_date=target_date)
    return [StudentListItem.model_validate(item) for item in payload]


@router.get("/student/{student_id}/profile", response_model=StudentProfileResponse)
@require_role(Role.TEACHER)
async def student_profile(
    student_id: int,
    days: int = Query(default=14, ge=3, le=90, description="回溯天数"),
    target_date: date | None = Query(default=None, description="默认昨天"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StudentProfileResponse:
    payload = await build_student_profile_payload(
        session,
        student_id=student_id,
        days=days,
        target_date=target_date,
    )
    session.commit()
    return StudentProfileResponse.model_validate(payload)


@router.get("/student/{student_id}/report", response_model=StudentReportResponse)
@require_role(Role.TEACHER)
async def student_report(
    student_id: int,
    target_date: date | None = Query(default=None, description="目标日期，默认为昨天"),
    llm_enhance: bool = Query(default=False, description="是否润色 Agent 报告"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StudentReportResponse:
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
    payload = list_student_class_assignments(
        session,
        class_id=class_id,
        include_unassigned=include_unassigned,
        limit=limit,
    )
    return [StudentClassAssignmentItem.model_validate(item) for item in payload]


@router.post("/student/{student_id}/class-assignment", response_model=StudentClassAssignmentUpdateResponse)
@require_role(Role.TEACHER)
async def update_student_class_assignment(
    student_id: int,
    req: StudentClassAssignmentUpdateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StudentClassAssignmentUpdateResponse:
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


@router.post("/intervention", response_model=InterventionResponse, status_code=status.HTTP_201_CREATED)
@require_role(Role.TEACHER)
async def create_intervention(
    req: InterventionCreateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> InterventionResponse:
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
    days: int = Query(default=14, ge=3, le=90, description="回溯天数"),
    target_date: date | None = Query(default=None, description="默认昨天"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
    summary = await generate_student_longitudinal_summary(
        session,
        student_id,
        class_id=resolve_class_id_for_user(session, student_id),
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
    payload = await build_weekly_report_payload(session, class_id=class_id, week_start=week_start)
    session.commit()
    return WeeklyReportResponse.model_validate(payload)
