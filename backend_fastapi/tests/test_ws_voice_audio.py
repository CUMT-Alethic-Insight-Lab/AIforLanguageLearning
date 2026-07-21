from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, select

from app.db import init_db, override_engine_for_tests
from app.main import app
from app.models import ConversationEvent


def test_ws_text_llm_race_selects_fastest_first_token_not_fastest_full_response(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "test_ttft_race.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    async def fake_stream_chat(
        *,
        system_prompt: str,
        user_text: str,
        history=None,
        model=None,
        base_url=None,
        api_key=None,
    ):
        if base_url:
            await asyncio.sleep(0.01)
            yield "cloud-first"
            await asyncio.sleep(0.05)
            yield "-cloud-last"
        else:
            await asyncio.sleep(0.03)
            yield "local-only"

    monkeypatch.setenv("KIMI_API_KEY", "test-kimi-key")
    monkeypatch.setattr("app.main.stream_chat", fake_stream_chat)
    monkeypatch.setattr("app.main.synthesize_tts_wav", lambda text: b"fake-wav")

    client = TestClient(app)
    with client.websocket_connect("/ws/v1?session_id=test&conversation_id=conv_ttft") as ws:
        first = ws.receive_json()
        assert first["type"] == "TASK_STARTED"

        ws.send_json(
            {
                "type": "TEXT",
                "request_id": "text_ttft",
                "payload": {"text": "hello"},
            }
        )

        seen = []
        for _ in range(30):
            msg = ws.receive_json()
            seen.append(msg)
            if msg.get("type") == "TASK_FINISHED":
                break

    tokens = [m for m in seen if m.get("type") == "LLM_TOKEN"]
    assert tokens
    assert (tokens[0].get("payload") or {}).get("source") == "cloud"
    assert (tokens[0].get("payload") or {}).get("text") == "cloud-first"
    result = next(m for m in seen if m.get("type") == "LLM_RESULT")
    assert (result.get("payload") or {}).get("markdown") == "cloud-first-cloud-last"


def test_ws_voice_audio_min_flow(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    async def fake_stream_chat(*, system_prompt: str, user_text: str, history=None):
        yield "ok"

    monkeypatch.setattr("app.main.stream_chat", fake_stream_chat)
    monkeypatch.setattr(
        "app.main.try_create_seamless_transcriber",
        lambda **_: (lambda _audio, _cfg: "hello from asr"),
    )
    monkeypatch.setattr("app.main.settings.enable_asr", True)
    monkeypatch.setattr("app.main.settings.asr_backend", "seamless")

    client = TestClient(app)
    with client.websocket_connect("/ws/v1?session_id=test&conversation_id=conv_voice") as ws:
        first = ws.receive_json()
        assert first["type"] == "TASK_STARTED"

        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "voice1",
                "payload": {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"},
            }
        )

        msg = ws.receive_json()
        assert msg["type"] == "TASK_STARTED"
        assert msg["request_id"] == "voice1"

        dummy_pcm = b"\x00\x00" * 320  # 20ms silence at 16kHz mono s16le
        ws.send_json(
            {
                "type": "AUDIO_CHUNK",
                "request_id": "voice1",
                "payload": {"data_b64": base64.b64encode(dummy_pcm).decode("utf-8")},
            }
        )

        ws.send_json({"type": "AUDIO_END", "request_id": "voice1"})

        types = []
        for _ in range(15):
            m = ws.receive_json()
            types.append(m.get("type"))
            if m.get("type") == "TASK_FINISHED":
                assert isinstance((m.get("payload") or {}).get("pipeline_metrics"), dict)
                metrics = (m.get("payload") or {}).get("pipeline_metrics") or {}
                assert "llm_latency_ms" in metrics
                assert "tts_total_ms" in metrics
            if m.get("type") == "TASK_FINISHED":
                break

        assert "ASR_FINAL" in types
        assert "LLM_TOKEN" in types
        assert types.index("LLM_TOKEN") < types.index("LLM_RESULT")
        assert "LLM_RESULT" in types
        assert "TTS_CHUNK" in types
        assert "TTS_RESULT" in types
        assert "TASK_FINISHED" in types


def test_ws_voice_audio_empty_asr_text_fallback(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test_empty_asr.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    async def fake_stream_chat(*, system_prompt: str, user_text: str, history=None):
        yield "should_not_be_called"

    monkeypatch.setattr("app.main.stream_chat", fake_stream_chat)
    monkeypatch.setattr(
        "app.main.try_create_seamless_transcriber",
        lambda **_: (lambda _audio, _cfg: ""),
    )
    monkeypatch.setattr("app.main.settings.enable_asr", True)
    monkeypatch.setattr("app.main.settings.asr_backend", "seamless")

    client = TestClient(app)
    with client.websocket_connect("/ws/v1?session_id=test&conversation_id=conv_voice_empty") as ws:
        first = ws.receive_json()
        assert first["type"] == "TASK_STARTED"

        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "voice_empty",
                "payload": {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"},
            }
        )

        started = ws.receive_json()
        assert started["type"] == "TASK_STARTED"
        assert started["request_id"] == "voice_empty"

        dummy_pcm = b"\x00\x00" * 320
        ws.send_json(
            {
                "type": "AUDIO_CHUNK",
                "request_id": "voice_empty",
                "payload": {"data_b64": base64.b64encode(dummy_pcm).decode("utf-8")},
            }
        )
        ws.send_json({"type": "AUDIO_END", "request_id": "voice_empty"})

        types = []
        asr_text = None
        llm_markdown = None
        for _ in range(15):
            m = ws.receive_json()
            msg_type = m.get("type")
            types.append(msg_type)
            payload = m.get("payload") or {}
            if msg_type == "ASR_FINAL":
                asr_text = payload.get("text")
            if msg_type == "LLM_RESULT":
                llm_markdown = payload.get("markdown")
            if msg_type == "TASK_FINISHED":
                break

        assert "ASR_FINAL" in types
        assert asr_text == ""
        assert "LLM_TOKEN" not in types
        assert "LLM_RESULT" in types
        assert "TTS_RESULT" in types
        assert "TASK_FINISHED" in types
        assert llm_markdown == "（未检测到语音内容）"


def test_ws_voice_audio_asr_unavailable_not_persisted_as_user_history(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "test_asr_unavailable.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    monkeypatch.setattr("app.main.settings.enable_asr", True)
    monkeypatch.setattr("app.main.settings.asr_backend", "seamless")
    monkeypatch.setattr("app.main.settings.asr_local_files_only", True)
    monkeypatch.setattr("app.main.try_create_seamless_transcriber", lambda **_: None)

    client = TestClient(app)
    with client.websocket_connect(
        "/ws/v1?session_id=test&conversation_id=conv_voice_asr_unavailable"
    ) as ws:
        first = ws.receive_json()
        assert first["type"] == "TASK_STARTED"

        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "voice_unavailable",
                "payload": {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"},
            }
        )

        started = ws.receive_json()
        assert started["type"] == "TASK_STARTED"
        assert started["request_id"] == "voice_unavailable"

        dummy_pcm = b"\x00\x00" * 320
        ws.send_json(
            {
                "type": "AUDIO_CHUNK",
                "request_id": "voice_unavailable",
                "payload": {"data_b64": base64.b64encode(dummy_pcm).decode("utf-8")},
            }
        )
        ws.send_json({"type": "AUDIO_END", "request_id": "voice_unavailable"})

        asr_final_payload = None
        error_payload = None
        types = []
        for _ in range(15):
            m = ws.receive_json()
            msg_type = m.get("type")
            payload = m.get("payload") or {}
            types.append(msg_type)
            if msg_type == "ASR_FINAL":
                asr_final_payload = payload
            if msg_type == "ERROR":
                error_payload = payload
            if msg_type == "TASK_FINISHED":
                break

        assert types == ["ASR_FINAL", "ERROR", "TASK_FINISHED"]
        assert asr_final_payload is not None
        assert asr_final_payload.get("diagnostic") is True
        assert asr_final_payload.get("error_code") == "ASR_UNAVAILABLE"
        assert asr_final_payload.get("word_count") == 0
        assert error_payload == {
            "code": "ASR_UNAVAILABLE",
            "message": asr_final_payload.get("text"),
        }

    with Session(engine) as session:
        rows = session.exec(
            select(ConversationEvent)
            .where(ConversationEvent.conversation_id == "conv_voice_asr_unavailable")
            .where(ConversationEvent.request_id == "voice_unavailable")
            .order_by(ConversationEvent.seq.asc())
        ).all()

    persisted_types = [row.type for row in rows]
    assert persisted_types == ["TASK_STARTED", "ASR_FINAL", "ERROR", "TASK_FINISHED"]
    assert all(row.type != "USER_MESSAGE" for row in rows)
    asr_row = next(row for row in rows if row.type == "ASR_FINAL")
    assert bool((asr_row.payload or {}).get("diagnostic")) is True
    assert (asr_row.payload or {}).get("error_code") == "ASR_UNAVAILABLE"


def test_ws_voice_audio_asr_unavailable_not_reused_in_text_history(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "test_asr_unavailable_history.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    captured_histories: list[list[dict[str, str]]] = []

    async def fake_stream_chat(*, system_prompt: str, user_text: str, history=None, **kwargs):
        captured_histories.append(list(history or []))
        yield "text-ok"

    monkeypatch.setattr("app.main.stream_chat", fake_stream_chat)
    monkeypatch.setattr("app.main.chat_complete", lambda **kwargs: "text-ok")
    monkeypatch.setattr("app.main.synthesize_tts_wav", lambda text: b"FAKE_WAV_DATA")
    monkeypatch.setattr("app.main.settings.enable_asr", True)
    monkeypatch.setattr("app.main.settings.asr_backend", "seamless")
    monkeypatch.setattr("app.main.settings.asr_local_files_only", True)
    monkeypatch.setattr("app.main.try_create_seamless_transcriber", lambda **_: None)

    client = TestClient(app)
    with client.websocket_connect(
        "/ws/v1?session_id=test&conversation_id=conv_voice_asr_history"
    ) as ws:
        _ = ws.receive_json()

        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "voice_unavailable_history",
                "payload": {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"},
            }
        )
        _ = ws.receive_json()

        dummy_pcm = b"\x00\x00" * 320
        ws.send_json(
            {
                "type": "AUDIO_CHUNK",
                "request_id": "voice_unavailable_history",
                "payload": {"data_b64": base64.b64encode(dummy_pcm).decode("utf-8")},
            }
        )
        ws.send_json({"type": "AUDIO_END", "request_id": "voice_unavailable_history"})

        for _ in range(15):
            m = ws.receive_json()
            if m.get("request_id") == "voice_unavailable_history" and m.get("type") == "TASK_FINISHED":
                break

        ws.send_json(
            {
                "type": "TEXT",
                "request_id": "text_after_unavailable",
                "payload": {"text": "Reply with exactly: text-ok"},
            }
        )

        for _ in range(20):
            m = ws.receive_json()
            if m.get("request_id") == "text_after_unavailable" and m.get("type") == "TASK_FINISHED":
                break

    assert captured_histories, "expected TEXT path to call stream_chat"
    assert captured_histories[-1] == []
