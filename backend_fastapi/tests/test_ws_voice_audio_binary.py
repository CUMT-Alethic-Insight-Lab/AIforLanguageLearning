from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app.db import init_db, override_engine_for_tests
from app.main import app


def test_ws_voice_audio_binary_chunk_min_flow(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    # 避免测试期间发起真实 LLM / TTS 请求
    async def fake_stream_chat(*, system_prompt: str, user_text: str, history=None, **kwargs):
        for token in ["Hello", " ", "world", "."]:
            yield token

    monkeypatch.setattr("app.main.stream_chat", fake_stream_chat)
    monkeypatch.setattr(
        "app.main.chat_complete",
        lambda **kwargs: "Hello world.",
    )
    monkeypatch.setattr(
        "app.main.synthesize_tts_wav",
        lambda text: b"FAKE_WAV_DATA",
    )
    monkeypatch.setattr(
        "app.main.try_create_seamless_transcriber",
        lambda **_: (lambda _audio, _cfg: "hello from asr"),
    )
    monkeypatch.setattr("app.main.settings.enable_asr", True)
    monkeypatch.setattr("app.main.settings.asr_backend", "seamless")

    client = TestClient(app)
    with client.websocket_connect("/ws/v1?session_id=test&conversation_id=conv_voice_bin") as ws:
        _ = ws.receive_json()  # server TASK_STARTED

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

        # Send header then a binary frame
        ws.send_json({"type": "AUDIO_CHUNK_BIN", "request_id": "voice1", "payload": {}})
        dummy_pcm = b"\x00\x00" * 320  # 20ms silence at 16kHz mono s16le
        ws.send_bytes(dummy_pcm)

        ws.send_json({"type": "AUDIO_END", "request_id": "voice1"})

        types = []
        for _ in range(25):
            m = ws.receive_json()
            types.append(m.get("type"))
            if m.get("type") == "TASK_FINISHED":
                break

        assert "ASR_FINAL" in types
        assert "LLM_RESULT" in types
        assert "TTS_CHUNK" in types
        assert "TTS_RESULT" in types
        assert "TASK_FINISHED" in types
