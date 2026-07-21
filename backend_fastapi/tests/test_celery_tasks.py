"""Celery 任务测试"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("CELERY_DEMO_EAGER", "1")

from app.infrastructure.messaging.tasks import grade_essay_task, generate_daily_vocab_task


@pytest.fixture
def db_engine(tmp_path):
    from sqlmodel import create_engine
    from app.db import init_db, override_engine_for_tests
    db_path = tmp_path / "test_celery.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()
    return engine


def test_grade_essay_task_eager(db_engine, monkeypatch):
    from sqlmodel import Session, select
    from app.db import get_engine
    from app.models import EssaySubmission
    from app.domain.models import LearningRecord

    async def _fake_grade_essay(*, ocr_text: str, language: str):
        return {
            "score": 75,
            "feedback": "不错",
            "errors": [],
            "suggestions": ["注意时态"],
            "rewritten": "I have a dream.",
            "scores": {
                "vocabulary": 70,
                "grammar": 75,
                "fluency": 78,
                "logic": 80,
                "content": 72,
                "structure": 75,
                "total": 75,
            },
        }

    monkeypatch.setattr("app.llm.grade_essay", _fake_grade_essay)
    # 避免测试时连接真实 Redis / 初始化 LanguageTool
    monkeypatch.setattr(
        "app.infrastructure.persistence.cache.sync_redis_cache.SyncRedisCache.get",
        lambda self, key: None,
    )
    monkeypatch.setattr(
        "app.infrastructure.persistence.cache.sync_redis_cache.SyncRedisCache.set",
        lambda self, key, value, ttl=None: False,
    )
    monkeypatch.setattr("app.domain.essay_spelling.check_essay", lambda text: {"issues": [], "issue_count": 0, "spelling_count": 0, "grammar_count": 0})

    with Session(get_engine()) as session:
        submission = EssaySubmission(
            user_id=1,
            session_id="test",
            conversation_id="conv_test",
            request_id="req1",
            ocr_text="I has a dream.",
            language="en",
        )
        session.add(submission)
        session.commit()
        session.refresh(submission)
        essay_id = str(submission.id)

    result = grade_essay_task.run(essay_id=essay_id, content="I has a dream.")
    assert result["essay_id"] == essay_id
    assert "score" in result
    assert result.get("status") != "failed"
    # 验证标准化结果结构
    assert "result" in result
    assert "dimensions" in result["result"]
    assert "total_score" in result["result"]
    assert "grade" in result["result"]

    with Session(get_engine()) as session:
        records = list(
            session.exec(
                select(LearningRecord)
                .where(LearningRecord.user_id == 1)
                .where(LearningRecord.type == "essay")
            ).all()
        )
        assert len(records) == 1
        record = records[0]
        assert record.meta_data["action"] == "grade_essay"
        assert record.meta_data["source"] == "celery"
        assert record.meta_data["input_mode"] == "text"
        assert record.meta_data["score"] == result["score"]


def test_generate_daily_vocab_task_eager():
    result = generate_daily_vocab_task.run(user_id="user_456")
    assert result["user_id"] == "user_456"
    assert isinstance(result["words"], list)
