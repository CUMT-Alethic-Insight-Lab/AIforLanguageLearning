from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app.db import init_db, override_engine_for_tests
from app.main import app


_FAKE_PIPELINE_RESULT = {
    "dimensions": {
        "content": {"score": 8.0, "weight": 0.30, "weighted": 2.40},
        "structure": {"score": 7.0, "weight": 0.25, "weighted": 1.75},
        "language": {"score": 8.0, "weight": 0.25, "weighted": 2.00},
        "grammar": {"score": 6.0, "weight": 0.20, "weighted": 1.20},
    },
    "total_score": 7.35,
    "grade": "B+",
    "feedback": "整体良好，注意语法细节",
    "suggestions": ["improve grammar"],
    "corrected_text": "I have a pen. I like learning English.",
    "llm_raw": {
        "score": 74,
        "feedback": "整体良好",
        "errors": [],
        "suggestions": ["improve grammar"],
        "rewritten": "I have a pen. I like learning English.",
        "scores": {
            "vocabulary": 80,
            "grammar": 60,
            "fluency": 80,
            "logic": 80,
            "content": 80,
            "structure": 70,
            "total": 74,
        },
    },
}


async def _fake_run_grading_pipeline(*, ocr_text: str, language: str):
    return _FAKE_PIPELINE_RESULT


def test_essay_grade_and_get_via_http(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    monkeypatch.setattr("app.routers.essays.run_grading_pipeline", _fake_run_grading_pipeline)

    client = TestClient(app)

    resp = client.post(
        "/v1/essays/grade",
        json={
            "session_id": "test",
            "conversation_id": "conv_test",
            "request_id": "req1",
            "language": "en",
            "ocr_text": "I has a pen. I like learn English.",
        },
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["conversation_id"] == "conv_test"
    assert body["request_id"] == "req1"
    assert isinstance(body["submission_id"], int)

    # score = round(total_score * 10) = 74
    assert body["score"] == 74

    result = body["result"]
    assert isinstance(result, dict)
    assert "dimensions" in result
    assert "total_score" in result
    assert "grade" in result
    assert "feedback" in result
    assert "suggestions" in result
    assert "corrected_text" in result
    assert "llm_raw" in result

    submission_id = body["submission_id"]

    resp2 = client.get(f"/v1/essays/{submission_id}")
    assert resp2.status_code == 200
    got = resp2.json()
    assert got["submission_id"] == submission_id
    assert got["conversation_id"] == "conv_test"
    assert got["request_id"] == "req1"
    assert got["language"] == "en"
    assert "I has a pen" in got["ocr_text"]
    assert isinstance(got["result"], dict)
    assert got["status"] == "completed"


def test_essay_grade_ocr_via_http(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    monkeypatch.setattr("app.routers.essays.ocr_image_base64", lambda image, language="english": "I has a pen.")
    monkeypatch.setattr("app.routers.essays.run_grading_pipeline", _fake_run_grading_pipeline)

    client = TestClient(app)
    payload = base64.b64encode(b"dummy").decode("utf-8")
    resp = client.post("/v1/essays/grade-ocr", json={"image": payload, "language": "english"})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["submission_id"], int)
    assert body["score"] == 74
    assert isinstance(body["result"], dict)
    assert body["result"]["grade"] == "B+"


def test_essay_submit_text_and_get_status(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    class _FakeTaskResult:
        id = "fake-task-id-123"

    monkeypatch.setattr("app.routers.essays.grade_essay_task.delay", lambda *a, **k: _FakeTaskResult())

    client = TestClient(app)
    resp = client.post(
        "/v1/essays",
        json={
            "content": "I has a pen. I like learn English.",
            "language": "en",
            "user_id": 42,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "submitted"
    assert body["data"]["task_id"] == "fake-task-id-123"
    submission_id = body["data"]["submission_id"]
    assert isinstance(submission_id, int)

    # 查询状态应为 grading（因为 Celery 任务被 mock，不会真实写入结果）
    resp2 = client.get(f"/v1/essays/{submission_id}")
    assert resp2.status_code == 200
    got = resp2.json()
    assert got["submission_id"] == submission_id
    assert got["status"] == "grading"
    assert got["ocr_text"] == "I has a pen. I like learn English."
