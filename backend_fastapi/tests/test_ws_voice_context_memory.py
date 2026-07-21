from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app.db import init_db, override_engine_for_tests
from app.domain.models import User
from app.infrastructure.security import create_access_token, hash_password
from app.main import app


def _run_voice_round(ws: Any, request_id: str, pcm_b64: str) -> list[dict[str, Any]]:
    ws.send_json(
        {
            "type": "AUDIO_START",
            "request_id": request_id,
            "payload": {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"},
        }
    )

    started = ws.receive_json()
    assert started["type"] == "TASK_STARTED"
    assert started["request_id"] == request_id

    ws.send_json({"type": "AUDIO_CHUNK", "request_id": request_id, "payload": {"data_b64": pcm_b64}})
    ws.send_json({"type": "AUDIO_END", "request_id": request_id})

    events: list[dict[str, Any]] = []
    for _ in range(30):
        msg = ws.receive_json()
        events.append(msg)
        if msg.get("type") == "TASK_FINISHED" and msg.get("request_id") == request_id:
            break

    return events


def test_ws_context_patch_persists_and_injects_history(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    llm_calls: list[dict[str, Any]] = []

    async def fake_stream_chat(*, system_prompt: str, user_text: str, history=None):
        llm_calls.append(
            {
                "system_prompt": system_prompt,
                "user_text": user_text,
                "history": list(history or []),
            }
        )
        yield "stub-reply"

    monkeypatch.setattr("app.main.stream_chat", fake_stream_chat)
    monkeypatch.setattr(
        "app.main.try_create_seamless_transcriber",
        lambda **_: (lambda _audio, _cfg: "hello from asr"),
    )
    monkeypatch.setattr("app.main.settings.enable_asr", True)
    monkeypatch.setattr("app.main.settings.asr_backend", "seamless")

    client = TestClient(app)
    with client.websocket_connect("/ws/v1?session_id=test&conversation_id=conv_ctx") as ws:
        _ = ws.receive_json()  # server TASK_STARTED

        dummy_pcm = b"\x00\x00" * 320
        b64 = base64.b64encode(dummy_pcm).decode("utf-8")

        round1 = _run_voice_round(ws, "voice1", b64)
        assert any(m.get("type") == "LLM_RESULT" and m.get("request_id") == "voice1" for m in round1)

        ws.send_json(
            {
                "type": "CONTEXT_PATCH",
                "request_id": "ctx1",
                "payload": {"op": "replace", "text": "记住：用户喜欢简短回答"},
            }
        )
        patch_evt = ws.receive_json()
        assert patch_evt["type"] == "CONTEXT_MEMORY"
        patched_evt = ws.receive_json()
        assert patched_evt["type"] == "CONTEXT_PATCHED"
        assert patched_evt["request_id"] == "ctx1"
        assert (patched_evt.get("payload") or {}).get("memory") == "记住：用户喜欢简短回答"

        round2 = _run_voice_round(ws, "voice2", b64)
        assert any(m.get("type") == "LLM_RESULT" and m.get("request_id") == "voice2" for m in round2)

    assert len(llm_calls) >= 2
    second_call = llm_calls[-1]
    assert "记住：用户喜欢简短回答" in str(second_call.get("system_prompt") or "")

    history = second_call.get("history") or []
    assert any(h.get("role") == "assistant" for h in history)
    assert any(h.get("role") == "user" for h in history)


def test_ws_history_and_prompt_are_isolated_when_users_reuse_conversation_id(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "isolated_context.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    with Session(engine) as session:
        first = User(
            username="context_user_a",
            email="context_user_a@example.com",
            password_hash=hash_password("Password123!"),
            role="student",
        )
        second = User(
            username="context_user_b",
            email="context_user_b@example.com",
            password_hash=hash_password("Password123!"),
            role="student",
        )
        session.add(first)
        session.add(second)
        session.commit()
        session.refresh(first)
        session.refresh(second)
        assert first.id is not None and second.id is not None
        first_token = create_access_token(
            {"sub": first.username, "userId": first.id, "role": first.role}
        )
        second_token = create_access_token(
            {"sub": second.username, "userId": second.id, "role": second.role}
        )

    calls: list[dict[str, Any]] = []

    async def fake_stream_chat(**kwargs):
        calls.append(
            {
                "system_prompt": kwargs.get("system_prompt"),
                "user_text": kwargs.get("user_text"),
                "history": list(kwargs.get("history") or []),
            }
        )
        yield "reply."

    monkeypatch.setattr("app.main.stream_chat", fake_stream_chat)
    monkeypatch.setattr("app.main.synthesize_tts_wav", lambda text: f"wav:{text}".encode())
    monkeypatch.setattr("app.main.get_runtime_config", lambda: {})
    monkeypatch.delenv("KIMI_API_KEY", raising=False)

    client = TestClient(app)
    shared_scope = "session_id=shared-session&conversation_id=shared-conversation"

    with client.websocket_connect(f"/ws/v1?token={first_token}&{shared_scope}") as ws:
        _ = ws.receive_json()
        ws.send_json(
            {
                "type": "CONTEXT_SET",
                "request_id": "context-a",
                "payload": {"system_prompt": "PRIVATE PROMPT A"},
            }
        )
        assert ws.receive_json()["type"] == "CONTEXT_SET"
        ws.send_json(
            {"type": "TEXT", "request_id": "text-a", "payload": {"text": "message-a"}}
        )
        for _ in range(30):
            if ws.receive_json().get("type") == "TASK_FINISHED":
                break

    with client.websocket_connect(f"/ws/v1?token={second_token}&{shared_scope}") as ws:
        _ = ws.receive_json()
        ws.send_json(
            {"type": "TEXT", "request_id": "text-b", "payload": {"text": "message-b"}}
        )
        for _ in range(30):
            if ws.receive_json().get("type") == "TASK_FINISHED":
                break

    second_user_calls = [call for call in calls if call["user_text"] == "message-b"]
    assert second_user_calls
    assert all(call["system_prompt"] != "PRIVATE PROMPT A" for call in second_user_calls)
    assert all(call["history"] == [] for call in second_user_calls)
