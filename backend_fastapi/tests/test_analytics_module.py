"""教师端学情分析模块核心逻辑测试。

覆盖：
- 数据模型创建与序列化
- Agent-0 日度摘要生成（含冷启动保护）
- Agent-1/2/3 分层分析逻辑
- 维度计算函数
- 周报生成（LLM 调用 mock）

标记：
- 默认运行（无标记）
- integration: 需要真实数据库/Redis/LLM 的测试
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session, create_engine, select

from app.application.analytics.agents import (
    BottomTierAgent,
    MiddleTierAgent,
    TopTierAgent,
)
from app.application.analytics.facade import assign_student_class, backfill_student_class_ids
from app.application.analytics.daily_summary import (
    _calc_grammar_error_decay,
    _calc_long_term_memory,
    _calc_lookup_conversion,
    _calc_semantic_accuracy,
    _calc_vocab_growth_rate,
    generate_student_daily_summary,
)
from app.application.analytics.weekly_report import generate_class_weekly_report
from app.db import init_db, override_engine_for_tests
from app.domain.analytics.models import (
    AnalyticsArtifact,
    ClassDailySnapshot,
    InterventionTask,
    StudentDailySummary,
    StudentLongitudinalSummary,
)
from app.domain.models import LearningRecord, StudentProfile, User, VocabularyItem
from app.models import ConversationEvent, EssayResult, UserVocabQuery


# ───────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────


@pytest.fixture
def test_engine(tmp_path):
    """提供隔离的内存/文件 SQLite 引擎。"""
    db_path = tmp_path / "test_analytics.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()
    return engine


@pytest.fixture
def sample_vocab_items() -> list[VocabularyItem]:
    """构造一组词汇记录用于测试。"""
    base = datetime(2026, 4, 1, 12, 0, 0)
    return [
        VocabularyItem(
            user_id=1,
            word="apple",
            mastery_level=4,
            next_review_at=base + timedelta(days=400),
            created_at=base,
        ),
        VocabularyItem(
            user_id=1,
            word="banana",
            mastery_level=2,
            next_review_at=base + timedelta(days=7),
            created_at=base,
        ),
        VocabularyItem(
            user_id=1,
            word="cherry",
            mastery_level=5,
            next_review_at=base + timedelta(days=500),
            created_at=base,
        ),
    ]


@pytest.fixture
def sample_essay_results() -> list[EssayResult]:
    """构造一组作文批改结果用于测试。"""
    base = datetime(2026, 4, 1, 12, 0, 0)
    return [
        EssayResult(
            submission_id=1,
            score=70,
            result={"dimensions": {"grammar": 60, "structure": 65, "language": 70}},
            created_at=base,
        ),
        EssayResult(
            submission_id=2,
            score=75,
            result={"dimensions": {"grammar": 65, "structure": 68, "language": 72}},
            created_at=base + timedelta(days=1),
        ),
        EssayResult(
            submission_id=3,
            score=82,
            result={"dimensions": {"grammar": 72, "structure": 75, "language": 74}},
            created_at=base + timedelta(days=2),
        ),
    ]


# ───────────────────────────────────────────────
# 模型测试
# ───────────────────────────────────────────────


def test_student_daily_summary_model() -> None:
    """测试 StudentDailySummary 模型可正常实例化。"""
    summary = StudentDailySummary(
        user_id=1,
        summary_date=date(2026, 4, 18),
        vocab_growth_rate=3.5,
        sm2_retention_rate=0.85,
    )
    assert summary.user_id == 1
    assert summary.summary_date == date(2026, 4, 18)
    assert summary.vocab_growth_rate == 3.5
    assert summary.sm2_retention_rate == 0.85


def test_class_daily_snapshot_model() -> None:
    """测试 ClassDailySnapshot 模型可正常实例化。"""
    snapshot = ClassDailySnapshot(
        class_id="class_101",
        snapshot_date=date(2026, 4, 18),
        lower_tier_lift_rate=0.12,
        common_error_index=0.35,
        feedback_adoption_tendency={"structure": 0.6, "grammar": 0.4},
    )
    assert snapshot.class_id == "class_101"
    assert snapshot.feedback_adoption_tendency == {"structure": 0.6, "grammar": 0.4}


def test_intervention_task_model() -> None:
    """测试 InterventionTask 模型可正常实例化。"""
    task = InterventionTask(
        student_id=1,
        class_id="class_101",
        agent_type="bottom",
        title="测试干预",
        description="基础词汇薄弱",
        suggestion={"actions": ["复习 5 个核心词"]},
        priority="high",
    )
    assert task.status == "pending"
    assert task.priority == "high"


# ───────────────────────────────────────────────
# 维度计算单元测试
# ───────────────────────────────────────────────


def test_calc_vocab_growth_rate(sample_vocab_items: list[VocabularyItem]) -> None:
    rate = _calc_vocab_growth_rate(sample_vocab_items)
    assert rate is not None
    assert rate == pytest.approx(11 / 3, rel=1e-3)


def test_calc_vocab_growth_rate_empty() -> None:
    assert _calc_vocab_growth_rate([]) is None


def test_calc_sm2_retention(sample_vocab_items: list[VocabularyItem]) -> None:
    from app.application.analytics.daily_summary import _calc_sm2_retention

    rate = _calc_sm2_retention(sample_vocab_items)
    assert rate is not None
    # mastery >= 3: apple(4), cherry(5) => 2/3
    assert rate == pytest.approx(2 / 3, rel=1e-3)


def test_calc_long_term_memory(sample_vocab_items: list[VocabularyItem]) -> None:
    count = _calc_long_term_memory(sample_vocab_items)
    assert count is not None
    # apple(400d), cherry(500d) 都 >= 365
    assert count == 2


def test_calc_lookup_conversion() -> None:
    from app.application.analytics.daily_summary import (
        UserVocabQuery,
        _calc_lookup_conversion,
    )

    queries = [
        UserVocabQuery(term="apple", source="manual", result="", created_at=datetime.utcnow()),
        UserVocabQuery(term="banana", source="manual", result="", created_at=datetime.utcnow()),
    ]
    vocab_items = [
        VocabularyItem(
            user_id=1,
            word="Apple",
            mastery_level=4,
            next_review_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
        ),
    ]
    rate = _calc_lookup_conversion(queries, vocab_items)
    assert rate is not None
    # apple 匹配（忽略大小写），banana 不匹配 => 1/2
    assert rate == 0.5


def test_calc_grammar_error_decay(sample_essay_results: list[EssayResult]) -> None:
    slope = _calc_grammar_error_decay(sample_essay_results)
    assert slope is not None
    # grammar: 60 -> 65 -> 72, slope = (72 - 60) / 2 = 6.0
    assert slope == pytest.approx(6.0, rel=1e-3)


def test_calc_semantic_accuracy(sample_essay_results: list[EssayResult]) -> None:
    acc = _calc_semantic_accuracy(sample_essay_results)
    assert acc is not None
    # language: 70, 72, 74 => avg = 72 => 100 - 72 = 28
    assert acc == pytest.approx(28.0, rel=1e-3)


# ───────────────────────────────────────────────
# Agent-0 日度摘要测试
# ───────────────────────────────────────────────


def test_generate_student_daily_summary_cold_start(test_engine) -> None:
    """冷启动场景：无数据时应返回占位摘要（维度为 None）。"""
    with Session(test_engine) as session:
        user = User(username="test_student", email="s@test.com", role="student")
        session.add(user)
        session.commit()
        session.refresh(user)

    summary = generate_student_daily_summary(user.id, date(2026, 4, 18))
    assert summary.user_id == user.id
    assert summary.summary_date == date(2026, 4, 18)
    # 冷启动时大部分维度应为 None
    assert summary.vocab_growth_rate is None
    assert summary.grammar_error_decay_slope is None
    assert summary.raw_snapshot is not None
    assert summary.raw_snapshot.get("vocab_count") == 0


@patch("app.application.analytics.daily_summary._run_llm_enrichment", new_callable=AsyncMock)
def test_generate_student_daily_summary_exposes_methodology_and_topics(
    mock_llm_enrichment: AsyncMock, test_engine
) -> None:
    mock_llm_enrichment.return_value = {
        "llm_narrative": "学生在跨文化场景中表现稳定。",
        "cross_cultural_deviation": 18.0,
    }

    with Session(test_engine) as session:
        user = User(username="analytics_student", email="analytics@test.com", role="student")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = int(user.id or 0)

        session.add(
            VocabularyItem(
                user_id=user_id,
                word="boarding pass",
                definition="登机牌",
                example="Please show your boarding pass.",
                mastery_level=3,
                next_review_at=datetime(2026, 4, 25),
                created_at=datetime(2026, 4, 18, 9, 0, 0),
            )
        )
        session.add(
            UserVocabQuery(
                user_id=user_id,
                session_id="sess-1",
                conversation_id="conv-1",
                term="customs",
                source="manual",
                result="海关",
                meta_data={"scenario": "airport customs conversation", "theme": "travel"},
                created_at=datetime(2026, 4, 18, 9, 5, 0),
            )
        )
        session.add(
            ConversationEvent(
                user_id=user_id,
                session_id="sess-1",
                conversation_id="conv-1",
                seq=1,
                type="USER_MESSAGE",
                payload={
                    "text": "Could you tell me where customs is?",
                    "scenario": "airport customs conversation",
                    "word_count": 8,
                    "audio_duration_ms": 3200,
                    "response_latency_ms": 1400,
                },
                request_id="voice-1",
                final=True,
                ts=1,
                created_at=datetime(2026, 4, 18, 9, 10, 0),
            )
        )
        session.add(
            LearningRecord(
                user_id=user_id,
                type="dialogue",
                content="airport customs conversation",
                meta_data={"action": "voice_turn", "scenario": "airport customs conversation"},
                created_at=datetime(2026, 4, 18, 9, 11, 0),
            )
        )
        session.commit()

    summary = generate_student_daily_summary(user_id, date(2026, 4, 18))
    assert summary.cross_cultural_deviation == 18.0
    assert summary.topic_coverage_breadth is not None
    assert summary.raw_snapshot["metric_methodology"]["cross_cultural_deviation"]["mode"] == "llm_required"
    assert "travel" in summary.raw_snapshot["topics"]


# ───────────────────────────────────────────────
# Agent-1/2/3 分层分析测试
# ───────────────────────────────────────────────


import asyncio


def test_bottom_tier_agent_identifies_risk() -> None:
    """底层 Agent 应识别出词汇薄弱学生。"""
    summaries = [
        StudentDailySummary(
            user_id=1,
            summary_date=date(2026, 4, 18),
            vocab_growth_rate=1.5,
            learning_stability_std=3.0,
        ),
        StudentDailySummary(
            user_id=2,
            summary_date=date(2026, 4, 18),
            vocab_growth_rate=4.0,
            learning_stability_std=1.0,
        ),
    ]
    report = asyncio.run(BottomTierAgent.analyze(summaries, class_id="class_101"))
    assert report.agent_type == "bottom"
    assert len(report.risk_students) >= 1
    risk_ids = [r["user_id"] for r in report.risk_students]
    assert 1 in risk_ids
    assert len(report.intervention_tasks) >= 1


def test_middle_tier_agent_identifies_bottleneck() -> None:
    """中层 Agent 应识别出瓶颈期学生。"""
    summaries = [
        StudentDailySummary(
            user_id=1,
            summary_date=date(2026, 4, 18),
            vocab_growth_rate=3.0,
            grammar_error_decay_slope=0.8,
            logical_coherence_trend=55.0,
        ),
        StudentDailySummary(
            user_id=2,
            summary_date=date(2026, 4, 18),
            vocab_growth_rate=3.5,
            grammar_error_decay_slope=0.2,
            logical_coherence_trend=75.0,
        ),
    ]
    report = asyncio.run(MiddleTierAgent.analyze(summaries, class_id="class_101"))
    assert report.agent_type == "middle"
    # 至少有一个瓶颈期学生（logical_coherence_trend < 60）
    assert any("瓶颈期" in str(report.insights) for _ in [1])


def test_top_tier_agent_identifies_ceiling() -> None:
    """顶层 Agent 应识别出高阶瓶颈。"""
    summaries = [
        StudentDailySummary(
            user_id=1,
            summary_date=date(2026, 4, 18),
            vocab_growth_rate=5.0,
            autonomous_drive_count=0,
            topic_coverage_breadth=3,
        ),
        StudentDailySummary(
            user_id=2,
            summary_date=date(2026, 4, 18),
            vocab_growth_rate=4.5,
            autonomous_drive_count=5,
            topic_coverage_breadth=10,
        ),
    ]
    report = asyncio.run(TopTierAgent.analyze(summaries, class_id="class_101"))
    assert report.agent_type == "top"
    # 至少有一个顶层学生被标记
    assert len(report.risk_students) >= 1


# ───────────────────────────────────────────────
# 周报生成测试
# ───────────────────────────────────────────────


def test_generate_class_weekly_report_no_data() -> None:
    """无数据时应返回占位周报。"""
    record = generate_class_weekly_report("class_101", date(2026, 4, 13))
    assert record.artifact_type == "weekly_report"
    assert "数据收集中" in record.content or "班级周报" in record.content
    assert record.meta_data.get("student_count") == 0


@pytest.mark.integration
@patch("app.application.analytics.weekly_report._aggregate_weekly_class_data")
@patch("app.application.analytics.weekly_report._aggregate_weekly_student_summaries")
@patch("app.application.analytics.weekly_report.chat_complete")
def test_generate_class_weekly_report_with_llm(
    mock_chat: MagicMock, mock_students: MagicMock, mock_class: MagicMock
) -> None:
    """集成测试：LLM 正常返回时生成完整周报。"""
    mock_chat.return_value = {"content": "本周班级表现良好，建议继续加强词汇训练。"}
    mock_class.return_value = {"has_data": True, "avg_lower_tier_lift": 0.15}
    mock_students.return_value = [
        {"user_id": 1, "vocab_growth_rate": 3.5, "grammar_error_decay_slope": 0.8}
    ]
    record = generate_class_weekly_report("class_101", date(2026, 4, 13))
    assert record.artifact_type == "weekly_report"
    assert "表现良好" in record.content
    assert record.meta_data.get("student_count") == 1


# ───────────────────────────────────────────────
# 数据库持久化测试
# ───────────────────────────────────────────────


def test_persist_and_query_summary(test_engine) -> None:
    """测试摘要可写入并查询。"""
    summary = StudentDailySummary(
        user_id=1,
        summary_date=date(2026, 4, 18),
        vocab_growth_rate=3.5,
        sm2_retention_rate=0.8,
    )
    with Session(test_engine) as session:
        session.add(summary)
        session.commit()
        session.refresh(summary)
        assert summary.id is not None

    with Session(test_engine) as session:
        fetched = session.exec(
            select(StudentDailySummary).where(StudentDailySummary.user_id == 1)
        ).first()
        assert fetched is not None
        assert fetched.vocab_growth_rate == 3.5


def test_persist_intervention_task(test_engine) -> None:
    """测试干预任务可写入并查询。"""
    task = InterventionTask(
        student_id=1,
        class_id="class_101",
        agent_type="bottom",
        title="词汇补底",
        description="基础词汇掌握不足",
        suggestion={"actions": ["复习核心词"]},
        priority="high",
        due_date=date(2026, 4, 21),
    )
    with Session(test_engine) as session:
        session.add(task)
        session.commit()
        session.refresh(task)
        assert task.id is not None
        assert task.status == "pending"


def test_assign_student_class_syncs_related_records(test_engine) -> None:
    """教师调班后，应同步修正相关 analytics 表中的 class_id。"""
    with Session(test_engine) as session:
        user = User(username="student_sync", email="student_sync@test.com", role="student")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = int(user.id or 0)

        session.add(StudentProfile(user_id=user_id, class_id=None, level="beginner"))
        session.add(StudentDailySummary(user_id=user_id, class_id=None, summary_date=date(2026, 4, 18)))
        session.add(
            StudentLongitudinalSummary(
                user_id=user_id,
                class_id=None,
                window_start=date(2026, 4, 5),
                window_end=date(2026, 4, 18),
                window_days=14,
                llm_summary="旧纵向总结",
            )
        )
        session.add(
            AnalyticsArtifact(
                artifact_type="student_note",
                scope="student",
                user_id=user_id,
                class_id=None,
                title="旧记录",
                content="需要同步班级",
            )
        )
        session.add(
            InterventionTask(
                student_id=user_id,
                class_id=None,
                agent_type="manual",
                title="人工干预",
                description="待跟进",
            )
        )
        session.commit()

        result = asyncio.run(
            assign_student_class(
                session,
                user_id=user_id,
                class_id="class_sync_1",
                note="unit_test",
                sync_related_records=True,
            )
        )
        session.commit()

        assert result["class_id"] == "class_sync_1"
        assert result["sync_stats"]["daily_summaries_updated"] == 1
        assert result["sync_stats"]["longitudinal_summaries_updated"] == 1
        assert result["sync_stats"]["intervention_tasks_updated"] == 1
        assert result["sync_stats"]["artifacts_updated"] == 1

    with Session(test_engine) as session:
        profile = session.exec(select(StudentProfile).where(StudentProfile.user_id == user_id)).first()
        summary = session.exec(select(StudentDailySummary).where(StudentDailySummary.user_id == user_id)).first()
        longitudinal = session.exec(
            select(StudentLongitudinalSummary).where(StudentLongitudinalSummary.user_id == user_id)
        ).first()
        task = session.exec(select(InterventionTask).where(InterventionTask.student_id == user_id)).first()
        artifact = session.exec(
            select(AnalyticsArtifact)
            .where(AnalyticsArtifact.user_id == user_id)
            .where(AnalyticsArtifact.artifact_type == "student_note")
        ).first()
        assert profile is not None and profile.class_id == "class_sync_1"
        assert summary is not None and summary.class_id == "class_sync_1"
        assert longitudinal is not None and longitudinal.class_id == "class_sync_1"
        assert task is not None and task.class_id == "class_sync_1"
        assert artifact is not None and artifact.class_id == "class_sync_1"


def test_backfill_student_class_ids_dry_run_keeps_database_clean(test_engine) -> None:
    """回填 dry-run 应只输出候选结果，不真正写库。"""
    with Session(test_engine) as session:
        user = User(username="student_backfill", email="student_backfill@test.com", role="student")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = int(user.id or 0)
        session.add(
            StudentDailySummary(
                user_id=user_id,
                class_id="class_backfill_1",
                summary_date=date(2026, 4, 18),
                vocab_growth_rate=2.5,
            )
        )
        session.commit()

    with Session(test_engine) as session:
        result = asyncio.run(backfill_student_class_ids(session, dry_run=True))
        session.rollback()
        items = [item for item in result["items"] if item["user_id"] == user_id]
        assert items
        assert items[0]["candidate_class_id"] == "class_backfill_1"
        assert result["dry_run"] is True

    with Session(test_engine) as session:
        profile = session.exec(select(StudentProfile).where(StudentProfile.user_id == user_id)).first()
        summary = session.exec(select(StudentDailySummary).where(StudentDailySummary.user_id == user_id)).first()
        assert profile is None
        assert summary is not None and summary.class_id == "class_backfill_1"
