"""Analytics 教师端 classroom ownership 权限验证。

覆盖：
- teacher 访问自己课堂/学生 → 200
- teacher 访问别人课堂/学生 → 403
- teacher 访问 legacy class_id → 403
- teacher class-assignments 不传 class_id → 403
- admin 访问任意数据 → 200
- intervention 跨课堂创建 → 403

所有测试在 SQLite 临时数据库中运行，monkeypatch analytics facade 函数
避免真实 LLM/统计数据。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app.db import init_db, override_engine_for_tests
from app.domain.analytics.models import StudentLongitudinalSummary
from app.domain.classroom.models import ClassEnrollment, Classroom
from app.domain.models import User
from app.infrastructure.security import create_access_token, hash_password
from app.main import app

# ── fake payload generators ───────────────────────────────────────────


_FAKE_CLASS_DASHBOARD: dict[str, Any] = {
    "class_id": "1",
    "overview": {
        "class_id": "1",
        "date": date(2026, 5, 31),
        "total_students": 5,
        "active_students": 3,
        "risk_count": 1,
        "ability_distribution": {},
        "trend_7d": {},
        "charts": {},
    },
    "students": [],
    "weekly": None,
}

_FAKE_CLASS_OVERVIEW: dict[str, Any] = {
    "class_id": "1",
    "date": date(2026, 5, 31),
    "total_students": 5,
    "active_students": 3,
    "risk_count": 1,
    "ability_distribution": {},
    "trend_7d": {},
    "charts": {},
}

_FAKE_CLASS_STUDENTS: list[dict[str, Any]] = []

_FAKE_WEEKLY_REPORT: dict[str, Any] = {
    "class_id": "1",
    "week_start": date(2026, 5, 24),
    "content": "Weekly report summary.",
    "generated_at": date(2026, 5, 31),
    "evidence": [],
}

_FAKE_ASSIGNMENTS: list[dict[str, Any]] = []


def _make_fake_student_dashboard(student_id: int) -> dict[str, Any]:
    return {
        "student_id": student_id,
        "profile": _make_fake_profile(student_id),
        "report": _make_fake_report(student_id),
    }


def _make_fake_profile(student_id: int) -> dict[str, Any]:
    return {
        "user_id": student_id,
        "username": f"s{student_id}",
        "profile": None,
        "time_series": [],
        "latest_summary": None,
        "llm_narrative": None,
        "longitudinal_summary": None,
        "charts": {},
        "analysis_methodology": {},
        "data_quality": {},
    }


def _make_fake_report(student_id: int) -> dict[str, Any]:
    return {
        "user_id": student_id,
        "date": date(2026, 5, 31),
        "agent_reports": [],
    }


_FAKE_ASSIGN_RESULT: dict[str, Any] = {
    "user_id": 1,
    "username": "s1",
    "previous_class_id": None,
    "class_id": "1",
    "changed": True,
    "sync_stats": {},
}


async def _fake_build_class_dashboard_payload(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return dict(_FAKE_CLASS_DASHBOARD)


async def _fake_build_class_overview_payload(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return dict(_FAKE_CLASS_OVERVIEW)


def _fake_build_class_students_payload(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    return list(_FAKE_CLASS_STUDENTS)


async def _fake_build_weekly_report_payload(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return dict(_FAKE_WEEKLY_REPORT)


def _fake_list_student_class_assignments(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    return list(_FAKE_ASSIGNMENTS)


async def _fake_build_student_dashboard_payload(
    *args: Any, student_id: int = 0, **kwargs: Any
) -> dict[str, Any]:
    return _make_fake_student_dashboard(student_id)


async def _fake_build_student_profile_payload(
    *args: Any, student_id: int = 0, **kwargs: Any
) -> dict[str, Any]:
    return _make_fake_profile(student_id)


async def _fake_build_student_report_payload(
    *args: Any, student_id: int = 0, **kwargs: Any
) -> dict[str, Any]:
    return _make_fake_report(student_id)


async def _fake_assign_student_class(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return dict(_FAKE_ASSIGN_RESULT)


async def _fake_generate_longitudinal_summary(
    *args: Any, student_id: int = 0, **kwargs: Any
) -> StudentLongitudinalSummary:
    return StudentLongitudinalSummary(
        user_id=student_id,
        class_id="1",
        window_start=date(2026, 5, 1),
        window_end=date(2026, 5, 31),
        window_days=31,
        llm_summary="Fake summary.",
        risk_flags=[],
        strength_flags=[],
        metric_deltas={},
        evidence=[],
    )


# ── fixture ────────────────────────────────────────────────────────────


@pytest.fixture
def setup_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create a temp SQLite DB with classroom/enrollment data and mock facades."""
    db_path = tmp_path / "test_analytics.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    # --- Monkeypatch all facade functions ---
    monkeypatch.setattr(
        "app.interfaces.analytics_router.build_class_dashboard_payload",
        _fake_build_class_dashboard_payload,
    )
    monkeypatch.setattr(
        "app.interfaces.analytics_router.build_class_overview_payload",
        _fake_build_class_overview_payload,
    )
    monkeypatch.setattr(
        "app.interfaces.analytics_router.build_class_students_payload",
        _fake_build_class_students_payload,
    )
    monkeypatch.setattr(
        "app.interfaces.analytics_router.build_weekly_report_payload",
        _fake_build_weekly_report_payload,
    )
    monkeypatch.setattr(
        "app.interfaces.analytics_router.list_student_class_assignments",
        _fake_list_student_class_assignments,
    )
    monkeypatch.setattr(
        "app.interfaces.analytics_router.build_student_profile_payload",
        _fake_build_student_profile_payload,
    )
    monkeypatch.setattr(
        "app.interfaces.analytics_router.build_student_report_payload",
        _fake_build_student_report_payload,
    )
    monkeypatch.setattr(
        "app.interfaces.analytics_router.assign_student_class",
        _fake_assign_student_class,
    )
    monkeypatch.setattr(
        "app.interfaces.analytics_router.generate_student_longitudinal_summary",
        _fake_generate_longitudinal_summary,
    )

    # --- Seed data ---
    with Session(engine) as session:
        teacher = User(
            username="t1",
            email="t1@test.dev",
            password_hash=hash_password("Test1234"),
            role="teacher",
        )
        student = User(
            username="s1",
            email="s1@test.dev",
            password_hash=hash_password("Test1234"),
            role="student",
        )
        other_student = User(
            username="s2",
            email="s2@test.dev",
            password_hash=hash_password("Test1234"),
            role="student",
        )
        admin = User(
            username="admin1",
            email="admin1@test.dev",
            password_hash=hash_password("Test1234"),
            role="admin",
        )
        other_teacher = User(
            username="t2",
            email="t2@test.dev",
            password_hash=hash_password("Test1234"),
            role="teacher",
        )
        session.add_all([teacher, student, other_student, admin, other_teacher])
        session.flush()

        cls = Classroom(
            name="Teacher1Class",
            course_name="ENG101",
            teacher_id=teacher.id,  # type: ignore[arg-type]
            semester="2026-Fall",
        )
        other_cls = Classroom(
            name="Teacher2Class",
            course_name="ENG102",
            teacher_id=other_teacher.id,  # type: ignore[arg-type]
            semester="2026-Fall",
        )
        session.add_all([cls, other_cls])
        session.flush()

        session.add(ClassEnrollment(classroom_id=cls.id, student_id=student.id, role="student"))
        session.add(
            ClassEnrollment(
                classroom_id=other_cls.id, student_id=other_student.id, role="student"
            )
        )
        session.commit()

        # Store IDs while session is still open (avoid DetachedInstanceError)
        data = {
            "teacher_id": teacher.id,
            "student_id": student.id,
            "other_student_id": other_student.id,
            "admin_id": admin.id,
            "other_teacher_id": other_teacher.id,
            "cls_id": cls.id,
            "other_cls_id": other_cls.id,
        }

    # Tokens (use stored IDs to avoid DetachedInstanceError)
    data["teacher_token"] = create_access_token(
        {"sub": "t1", "userId": data["teacher_id"]}
    )
    data["admin_token"] = create_access_token(
        {"sub": "admin1", "userId": data["admin_id"]}
    )
    data["other_teacher_token"] = create_access_token(
        {"sub": "t2", "userId": data["other_teacher_id"]}
    )

    return data


# ── helper ──────────────────────────────────────────────────────────────


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ════════════════════════════════════════════════════════════════════════
#  Student-level access tests
# ════════════════════════════════════════════════════════════════════════


def test_teacher_access_own_student_dashboard(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/student/{setup_db['student_id']}/dashboard",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_teacher_access_other_student_dashboard_403(setup_db: dict) -> None:
    """Teacher 1 tries to access student enrolled in Teacher 2's classroom."""
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/student/{setup_db['other_student_id']}/dashboard",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


def test_teacher_access_student_profile_own_200(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/student/{setup_db['student_id']}/profile",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_teacher_access_student_profile_other_403(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/student/{setup_db['other_student_id']}/profile",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


def test_teacher_cannot_scope_own_student_to_other_class(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/student/{setup_db['student_id']}/profile"
        f"?class_id={setup_db['other_cls_id']}",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


def test_teacher_access_student_report_own_200(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/student/{setup_db['student_id']}/report",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_teacher_access_student_report_other_403(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/student/{setup_db['other_student_id']}/report",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


def test_admin_access_any_student_dashboard_200(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/student/{setup_db['other_student_id']}/dashboard",
        headers=_auth(setup_db["admin_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_admin_access_any_student_profile_200(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/student/{setup_db['other_student_id']}/profile",
        headers=_auth(setup_db["admin_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_admin_access_any_student_report_200(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/student/{setup_db['other_student_id']}/report",
        headers=_auth(setup_db["admin_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_teacher_access_llm_profile_own_200(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/analytics/student/{setup_db['student_id']}/llm-profile",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_teacher_access_llm_profile_other_403(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/analytics/student/{setup_db['other_student_id']}/llm-profile",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


# ════════════════════════════════════════════════════════════════════════
#  Class-level access tests
# ════════════════════════════════════════════════════════════════════════


def test_teacher_access_own_class_dashboard_200(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/class/{setup_db['cls_id']}/dashboard",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_teacher_access_other_class_dashboard_403(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/class/{setup_db['other_cls_id']}/dashboard",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


def test_teacher_access_legacy_class_id_403(setup_db: dict) -> None:
    """Non-numeric class_id like 'class_101' → teacher 403."""
    client = TestClient(app)
    resp = client.get(
        "/api/v1/analytics/class/class_101/dashboard",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


def test_admin_access_legacy_class_id_200(setup_db: dict) -> None:
    """Admins are exempt from class_id validation."""
    client = TestClient(app)
    resp = client.get(
        "/api/v1/analytics/class/class_101/dashboard",
        headers=_auth(setup_db["admin_token"]),
    )
    # Admin passes access check, but the underlying build function may fail
    # (mocked in our case, so it returns 200)
    assert resp.status_code == 200, resp.text


def test_teacher_access_own_class_overview_200(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/class/{setup_db['cls_id']}/overview",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_class_overview_uses_roster_and_explicit_daily_counts(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/class/{setup_db['cls_id']}/overview?target_date=2026-05-31",
        headers=_auth(setup_db["teacher_token"]),
    )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["total_students"] == 1
    assert payload["enrolled_students"] == 1
    assert payload["active_students"] == 0
    assert payload["analyzed_students"] == 0


def test_teacher_access_other_class_overview_403(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/class/{setup_db['other_cls_id']}/overview",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


def test_teacher_access_own_class_students_200(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/class/{setup_db['cls_id']}/students",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_teacher_access_other_class_students_403(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/class/{setup_db['other_cls_id']}/students",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


def test_teacher_access_own_class_weekly_200(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/class/{setup_db['cls_id']}/weekly",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_teacher_access_other_class_weekly_403(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/class/{setup_db['other_cls_id']}/weekly",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


# ════════════════════════════════════════════════════════════════════════
#  Class-assignments
# ════════════════════════════════════════════════════════════════════════


def test_teacher_class_assignments_no_class_id_403(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        "/api/v1/analytics/class-assignments",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


def test_teacher_class_assignments_own_class_200(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/class-assignments?class_id={setup_db['cls_id']}",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_teacher_class_assignments_other_class_403(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/class-assignments?class_id={setup_db['other_cls_id']}",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


def test_admin_class_assignments_no_class_id_200(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.get(
        "/api/v1/analytics/class-assignments",
        headers=_auth(setup_db["admin_token"]),
    )
    assert resp.status_code == 200, resp.text


# ════════════════════════════════════════════════════════════════════════
#  Class-assignment update
# ════════════════════════════════════════════════════════════════════════


def test_teacher_update_own_student_assignment_200(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/analytics/student/{setup_db['student_id']}/class-assignment",
        json={"class_id": str(setup_db["cls_id"]), "note": "test"},
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_teacher_update_other_student_assignment_403(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/analytics/student/{setup_db['other_student_id']}/class-assignment",
        json={"class_id": str(setup_db["cls_id"]), "note": "test"},
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


# ════════════════════════════════════════════════════════════════════════
#  Intervention
# ════════════════════════════════════════════════════════════════════════


def test_teacher_create_intervention_own_student_201(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/v1/analytics/intervention",
        json={
            "student_id": setup_db["student_id"],
            "class_id": str(setup_db["cls_id"]),
            "title": "Test intervention",
            "description": "Teacher assigned intervention",
        },
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code in (200, 201), resp.text


def test_teacher_create_intervention_other_student_403(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/v1/analytics/intervention",
        json={
            "student_id": setup_db["other_student_id"],
            "class_id": str(setup_db["other_cls_id"]),
            "title": "Should fail",
        },
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code == 403, resp.text


def test_admin_create_intervention_any_student_201(setup_db: dict) -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/v1/analytics/intervention",
        json={
            "student_id": setup_db["other_student_id"],
            "class_id": str(setup_db["other_cls_id"]),
            "title": "Admin intervention",
        },
        headers=_auth(setup_db["admin_token"]),
    )
    assert resp.status_code in (200, 201), resp.text


# ════════════════════════════════════════════════════════════════════════
#  Get intervention by id
# ════════════════════════════════════════════════════════════════════════


def test_teacher_get_own_intervention_200(setup_db: dict) -> None:
    """Create an intervention as teacher, then fetch it."""
    client = TestClient(app)
    # Create
    resp = client.post(
        "/api/v1/analytics/intervention",
        json={
            "student_id": setup_db["student_id"],
            "class_id": str(setup_db["cls_id"]),
            "title": "To be fetched",
        },
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code in (200, 201), resp.text
    task_id = resp.json()["id"]

    # Fetch
    resp2 = client.get(
        f"/api/v1/analytics/intervention/{task_id}",
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp2.status_code == 200, resp2.text


def test_teacher_get_other_intervention_403(setup_db: dict) -> None:
    """Teacher 1 creates an intervention for their student, Teacher 2 tries to read it."""
    client = TestClient(app)
    resp = client.post(
        "/api/v1/analytics/intervention",
        json={
            "student_id": setup_db["student_id"],
            "class_id": str(setup_db["cls_id"]),
            "title": "For teacher 1 only",
        },
        headers=_auth(setup_db["teacher_token"]),
    )
    assert resp.status_code in (200, 201), resp.text
    task_id = resp.json()["id"]

    resp2 = client.get(
        f"/api/v1/analytics/intervention/{task_id}",
        headers=_auth(setup_db["other_teacher_token"]),
    )
    assert resp2.status_code == 403, resp2.text


def test_teacher_no_classrooms_access_any_student_403(setup_db: dict) -> None:
    """Teacher with zero classrooms cannot access any student (spec rule 8)."""
    from app.db import get_engine
    from app.infrastructure.security import create_access_token as _mint

    with Session(get_engine()) as session:
        lonely_teacher = User(
            username="lonely_t2",
            email="lonely_t2@test.dev",
            password_hash=hash_password("Test1234"),
            role="teacher",
        )
        orphan_student = User(
            username="orphan_s2",
            email="orphan_s2@test.dev",
            password_hash=hash_password("Test1234"),
            role="student",
        )
        session.add_all([lonely_teacher, orphan_student])
        session.commit()
        token = _mint({"sub": "lonely_t2", "userId": lonely_teacher.id})
        sid = orphan_student.id

    client = TestClient(app)
    resp = client.get(
        f"/api/v1/analytics/student/{sid}/dashboard",
        headers=_auth(token),
    )
    assert resp.status_code == 403, resp.text
