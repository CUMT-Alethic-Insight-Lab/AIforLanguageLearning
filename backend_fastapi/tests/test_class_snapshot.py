"""班级横向快照生成测试。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import Session, create_engine, select

from app.application.analytics.class_snapshot import generate_class_daily_snapshot
from app.application.analytics.daily_summary import generate_student_daily_summary
from app.db import init_db, override_engine_for_tests
from app.domain.analytics.models import ClassDailySnapshot, StudentDailySummary
from app.domain.models import StudentProfile, User


@pytest.fixture
def test_engine(tmp_path):
    db_path = tmp_path / "test_snapshot.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()
    return engine


def test_generate_class_daily_snapshot_empty_class(test_engine) -> None:
    """空班级应生成快照但维度为 None。"""
    snapshot = generate_class_daily_snapshot("class_empty", date(2026, 4, 18))
    assert snapshot.class_id == "class_empty"
    assert snapshot.snapshot_date == date(2026, 4, 18)
    assert snapshot.lower_tier_lift_rate is None
    assert snapshot.raw_snapshot["student_count"] == 0


def test_generate_class_daily_snapshot_with_data(test_engine) -> None:
    """有学生数据时应计算维度。"""
    with Session(test_engine) as session:
        user1 = User(username="s1", email="s1@test.com", role="student")
        user2 = User(username="s2", email="s2@test.com", role="student")
        session.add(user1)
        session.add(user2)
        session.commit()
        session.refresh(user1)
        session.refresh(user2)

        session.add(StudentProfile(user_id=user1.id, class_id="class_101", level="beginner"))
        session.add(StudentProfile(user_id=user2.id, class_id="class_101", level="intermediate"))
        session.add(
            StudentDailySummary(
                user_id=user1.id,
                class_id="class_101",
                summary_date=date(2026, 4, 18),
                vocab_growth_rate=1.5,
                grammar_error_decay_slope=-0.5,
                logical_coherence_trend=55.0,
                learning_stability_std=3.0,
                sm2_retention_rate=0.6,
                long_term_memory_robustness=2,
            )
        )
        session.add(
            StudentDailySummary(
                user_id=user2.id,
                class_id="class_101",
                summary_date=date(2026, 4, 18),
                vocab_growth_rate=4.5,
                grammar_error_decay_slope=0.8,
                logical_coherence_trend=75.0,
                learning_stability_std=1.0,
                sm2_retention_rate=0.9,
                long_term_memory_robustness=8,
            )
        )
        session.commit()

    snapshot = generate_class_daily_snapshot("class_101", date(2026, 4, 18))
    assert snapshot.class_id == "class_101"
    # B1: 底层进步斜率（无历史数据时可能为 None）
    # B2: 群体性错误共性指数
    assert snapshot.common_error_index is not None
    assert snapshot.common_error_index > 0  # user1 grammar < 0
    # B3: 中层难度耐受力
    # B4: 学习路径收敛度
    # B5: 能力分布位移
    # B8: 瓶颈期时长
    assert snapshot.bottleneck_duration_days is not None
    # B9: 反馈采纳倾向
    # B10: 任务完成韧性
    assert snapshot.task_completion_resilience is not None
    assert snapshot.raw_snapshot["student_count"] == 2


def test_class_snapshot_persisted(test_engine) -> None:
    """快照应能写入数据库。"""
    snapshot = generate_class_daily_snapshot("class_persist", date(2026, 4, 18))
    with Session(test_engine) as session:
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        assert snapshot.id is not None

        fetched = session.exec(
            select(ClassDailySnapshot).where(ClassDailySnapshot.class_id == "class_persist")
        ).first()
        assert fetched is not None
        assert fetched.snapshot_date == date(2026, 4, 18)
