from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app.db import init_db, override_engine_for_tests
from app.main import app


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
