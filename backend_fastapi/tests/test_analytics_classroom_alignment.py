"""Phase 1: analytics 数据归属统一 —— resolve_class_id_for_user / get_class_user_ids.

覆盖:
1. 学生有 ClassEnrollment → resolve_class_id_for_user 返回 str(classroom_id)
2. 学生无 ClassEnrollment 但有旧 StudentProfile.class_id → fallback 返回旧 class_id
3. get_class_user_ids 数字 class_id 从 ClassEnrollment 查学生
4. 多课堂 enrollment → id desc 稳定
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlmodel import Session, create_engine

from app.application.analytics.orchestration import (
    generate_student_longitudinal_summary,
    get_class_population_counts,
    get_class_summaries,
    get_class_user_ids,
    resolve_class_id_for_user,
)
from app.db import init_db, override_engine_for_tests
from app.domain.analytics.models import AnalyticsArtifact, StudentDailySummary
from app.domain.classroom.models import ClassEnrollment, Classroom
from app.domain.models import LearningRecord, StudentProfile, User

# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def db_engine(tmp_path):
    """Isolated SQLite engine with seeded classroom/enrollment data."""
    db_path = tmp_path / "test_alignment.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()
    return engine


@pytest.fixture
def seed(db_engine):
    with Session(db_engine) as session:
        # ── Users ──────────────────────────────────────────────────
        teacher = User(username="t1", email="t1@test.dev", role="teacher")
        student_a = User(username="sa", email="sa@test.dev", role="student")
        student_b = User(username="sb", email="sb@test.dev", role="student")
        student_c = User(username="sc", email="sc@test.dev", role="student")
        session.add_all([teacher, student_a, student_b, student_c])
        session.flush()

        # ── Classrooms ─────────────────────────────────────────────
        cls_1 = Classroom(
            name="ENG101-1",
            course_name="ENG101",
            teacher_id=int(teacher.id or 0),
            semester="2026-Fall",
        )
        cls_2 = Classroom(
            name="ENG102-2",
            course_name="ENG102",
            teacher_id=int(teacher.id or 0),
            semester="2026-Fall",
        )
        empty_cls = Classroom(
            name="ENG103-empty",
            course_name="ENG103",
            teacher_id=int(teacher.id or 0),
            semester="2026-Fall",
        )
        session.add_all([cls_1, cls_2, empty_cls])
        session.flush()

        # ── Enrollments ────────────────────────────────────────────
        # sa: enrolled in cls_1 only
        session.add(
            ClassEnrollment(
                classroom_id=int(cls_1.id or 0),
                student_id=int(student_a.id or 0),
                role="student",
            )
        )
        # sb: enrolled in cls_1 AND cls_2 (multi-class)
        session.add(
            ClassEnrollment(
                classroom_id=int(cls_1.id or 0),
                student_id=int(student_b.id or 0),
                role="student",
            )
        )
        session.add(
            ClassEnrollment(
                classroom_id=int(cls_2.id or 0),
                student_id=int(student_b.id or 0),
                role="student",
            )
        )
        # sc: no enrollment, but legacy StudentProfile.class_id = "legacy_xyz"
        session.add(
            StudentProfile(
                user_id=int(student_c.id or 0),
                class_id="legacy_xyz",
            )
        )
        session.commit()

        return {
            "cls_1_id": int(cls_1.id or 0),
            "cls_2_id": int(cls_2.id or 0),
            "empty_cls_id": int(empty_cls.id or 0),
            "sa_id": int(student_a.id or 0),
            "sb_id": int(student_b.id or 0),
            "sc_id": int(student_c.id or 0),
        }


# ── tests ───────────────────────────────────────────────────────────────


def test_resolve_class_id_from_enrollment(db_engine, seed):
    """学生有 ClassEnrollment 时返回 str(classroom_id)，而非 StudentProfile.class_id."""
    with Session(db_engine) as session:
        result = resolve_class_id_for_user(session, seed["sa_id"])
        assert result == str(seed["cls_1_id"])


def test_resolve_class_id_fallback_to_legacy_profile(db_engine, seed):
    """学生无 ClassEnrollment 但有旧 StudentProfile.class_id → fallback."""
    with Session(db_engine) as session:
        result = resolve_class_id_for_user(session, seed["sc_id"])
        assert result == "legacy_xyz"


def test_resolve_class_id_multi_enrollment_returns_latest(db_engine, seed):
    """多课堂 enrollment → id desc 返回最新 (cls_2 > cls_1)."""
    with Session(db_engine) as session:
        result = resolve_class_id_for_user(session, seed["sb_id"])
        # cls_2 enrollment was created after cls_1, so id desc → cls_2
        assert result == str(seed["cls_2_id"])


def test_get_class_user_ids_numeric_class_id(db_engine, seed):
    """数字 class_id 从 ClassEnrollment 查学生列表."""
    with Session(db_engine) as session:
        user_ids = get_class_user_ids(session, str(seed["cls_1_id"]))
        # sa and sb are both in cls_1
        assert seed["sa_id"] in user_ids
        assert seed["sb_id"] in user_ids
        assert seed["sc_id"] not in user_ids  # sc only has legacy class_id


def test_get_class_user_ids_legacy_string_class_id(db_engine, seed):
    """非数字 class_id 走 StudentProfile.class_id."""
    with Session(db_engine) as session:
        user_ids = get_class_user_ids(session, "legacy_xyz")
        assert user_ids == [seed["sc_id"]]


def test_get_class_user_ids_unknown_class_id_returns_empty(db_engine, seed):
    """未知 class_id 返回空列表."""
    with Session(db_engine) as session:
        assert get_class_user_ids(session, "999") == []
        assert get_class_user_ids(session, "nonexistent") == []


def test_numeric_classroom_roster_does_not_use_matching_legacy_profile(db_engine, seed):
    with Session(db_engine) as session:
        legacy_only = User(
            username="legacy_numeric",
            email="legacy_numeric@test.dev",
            role="student",
        )
        session.add(legacy_only)
        session.flush()
        session.add(
            StudentProfile(
                user_id=int(legacy_only.id or 0),
                class_id=str(seed["empty_cls_id"]),
            )
        )
        session.commit()

        assert get_class_user_ids(session, str(seed["empty_cls_id"])) == []


def test_resolve_class_id_no_enrollment_no_profile(db_engine):
    """无 enrollment 也无 profile → None."""
    with Session(db_engine) as session:
        assert resolve_class_id_for_user(session, 9999) is None


def test_class_population_counts_distinguish_roster_activity_and_analysis(db_engine, seed):
    target_date = date(2026, 6, 1)
    class_id = str(seed["cls_1_id"])
    with Session(db_engine) as session:
        session.add_all(
            [
                StudentDailySummary(
                    user_id=seed["sa_id"],
                    class_id=class_id,
                    summary_date=target_date,
                    raw_snapshot={"vocab_count": 1, "essay_count": 0, "event_count": 0},
                ),
                StudentDailySummary(
                    user_id=seed["sb_id"],
                    class_id=class_id,
                    summary_date=target_date,
                    raw_snapshot={
                        "vocab_count": 0,
                        "essay_count": 0,
                        "event_count": 0,
                        "query_count": 0,
                        "record_count": 0,
                    },
                ),
            ]
        )
        session.commit()

        counts = get_class_population_counts(session, class_id, target_date)

    assert counts == {
        "total_students": 2,
        "enrolled_students": 2,
        "active_students": 1,
        "analyzed_students": 2,
    }


def test_empty_class_population_counts_are_zero(db_engine, seed):
    with Session(db_engine) as session:
        counts = get_class_population_counts(
            session,
            str(seed["empty_cls_id"]),
            date(2026, 6, 1),
        )

    assert counts == {
        "total_students": 0,
        "enrolled_students": 0,
        "active_students": 0,
        "analyzed_students": 0,
    }


def test_active_student_is_counted_before_daily_analysis_exists(db_engine, seed):
    target_date = date(2026, 6, 1)
    with Session(db_engine) as session:
        session.add(
            LearningRecord(
                user_id=seed["sa_id"],
                type="vocabulary",
                content="lookup",
                created_at=datetime(2026, 6, 1, 10, 0),
            )
        )
        session.commit()

        counts = get_class_population_counts(
            session,
            str(seed["cls_1_id"]),
            target_date,
        )

    assert counts["enrolled_students"] == 2
    assert counts["active_students"] == 1
    assert counts["analyzed_students"] == 0


def test_class_summaries_do_not_mix_multi_enrollment_classes(db_engine, seed):
    class_1_id = str(seed["cls_1_id"])
    class_2_id = str(seed["cls_2_id"])
    with Session(db_engine) as session:
        session.add_all(
            [
                StudentDailySummary(
                    user_id=seed["sb_id"],
                    class_id=class_1_id,
                    summary_date=date(2026, 6, 1),
                ),
                StudentDailySummary(
                    user_id=seed["sb_id"],
                    class_id=class_2_id,
                    summary_date=date(2026, 6, 2),
                ),
            ]
        )
        session.commit()

        summaries = get_class_summaries(
            session,
            class_1_id,
            date(2026, 6, 1),
            date(2026, 6, 2),
        )

    assert [(summary.class_id, summary.summary_date) for summary in summaries] == [
        (class_1_id, date(2026, 6, 1))
    ]


async def test_class_overview_uses_fast_database_fallback(db_engine, seed, monkeypatch):
    from app.application.analytics.facade import build_class_overview_payload

    async def _unexpected_cloud_call(**_kwargs):
        raise AssertionError("class overview must not call the cloud LLM")

    monkeypatch.setattr(
        "app.application.analytics.orchestration.chat_complete_cloud_first",
        _unexpected_cloud_call,
    )

    with Session(db_engine) as session:
        payload = await build_class_overview_payload(
            session,
            class_id=str(seed["cls_1_id"]),
            target_date=date(2026, 6, 3),
            recent_days=3,
        )

    assert payload["recent_analysis"]["window_start"] == "2026-06-01"
    assert payload["recent_analysis"]["window_end"] == "2026-06-03"
    assert "在册学生 2 人" in payload["recent_analysis"]["content"]
    assert payload["recent_analysis"]["evidence"] == []


async def test_class_overview_reuses_cached_llm_artifact(db_engine, seed):
    from app.application.analytics.facade import build_class_overview_payload

    class_id = str(seed["cls_1_id"])
    with Session(db_engine) as session:
        session.add(
            AnalyticsArtifact(
                artifact_type="class_window_analysis",
                scope="class",
                class_id=class_id,
                target_date=date(2026, 6, 3),
                window_start=date(2026, 6, 1),
                window_end=date(2026, 6, 3),
                title="cached",
                content="已生成的云端班级分析",
                evidence=[{"source": "daily_summary"}],
            )
        )
        session.commit()
        payload = await build_class_overview_payload(
            session,
            class_id=class_id,
            target_date=date(2026, 6, 3),
            recent_days=3,
        )

    assert payload["recent_analysis"]["content"] == "已生成的云端班级分析"
    assert payload["recent_analysis"]["evidence"] == [{"source": "daily_summary"}]


async def test_student_longitudinal_summary_is_scoped_to_requested_class(
    db_engine,
    seed,
    monkeypatch,
):
    class_1_id = str(seed["cls_1_id"])
    class_2_id = str(seed["cls_2_id"])

    async def _fake_chat_complete_cloud_first(**_kwargs):
        return "班级内纵向总结"

    monkeypatch.setattr(
        "app.application.analytics.orchestration.chat_complete_cloud_first",
        _fake_chat_complete_cloud_first,
    )

    with Session(db_engine) as session:
        class_1_summary = StudentDailySummary(
            user_id=seed["sb_id"],
            class_id=class_1_id,
            summary_date=date(2026, 6, 1),
            vocab_growth_rate=1.0,
        )
        class_2_summary = StudentDailySummary(
            user_id=seed["sb_id"],
            class_id=class_2_id,
            summary_date=date(2026, 6, 2),
            vocab_growth_rate=9.0,
        )
        session.add_all([class_1_summary, class_2_summary])
        session.commit()
        session.refresh(class_1_summary)
        session.refresh(class_2_summary)

        result = await generate_student_longitudinal_summary(
            session,
            seed["sb_id"],
            class_id=class_1_id,
            end_date=date(2026, 6, 2),
            window_days=2,
            force=True,
        )

    assert result.class_id == class_1_id
    assert result.source_summary_ids == [class_1_summary.id]
    assert class_2_summary.id not in result.source_summary_ids
    assert [item["date"] for item in result.evidence if "date" in item] == ["2026-06-01"]
