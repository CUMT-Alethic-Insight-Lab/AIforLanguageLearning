from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app.db import init_db, override_engine_for_tests
from app.main import app


def _setup_test_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()


def test_ws_voice_seamless_interface_wiring(tmp_path: Path, monkeypatch) -> None:
    _setup_test_db(tmp_path)

    calls = {
        "seamless_factory": 0,
        "transcribe": 0,
    }

    def fake_seamless_factory(*, model_name: str = "small", device: str = "cpu", compute_type: str = "int8"):
        calls["seamless_factory"] += 1

        def _transcriber(_audio: bytes, _cfg):
            calls["transcribe"] += 1
            return "hello from seamless"

        return _transcriber

    monkeypatch.setattr("app.main.try_create_seamless_transcriber", fake_seamless_factory)

    monkeypatch.setattr("app.main.settings.enable_asr", True)
    monkeypatch.setattr("app.main.settings.asr_backend", "seamless")

    client = TestClient(app)
    with client.websocket_connect("/ws/v1?session_id=test&conversation_id=conv_backend_seamless") as ws:
        _ = ws.receive_json()  # server TASK_STARTED

        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "voice_seamless_1",
                "payload": {
                    "sample_rate": 16000,
                    "channels": 1,
                    "encoding": "pcm_s16le",
                    "asr_only": True,
                },
            }
        )
        _ = ws.receive_json()  # request TASK_STARTED

        dummy_pcm = b"\x00\x00" * 320
        ws.send_json(
            {
                "type": "AUDIO_CHUNK",
                "request_id": "voice_seamless_1",
                "payload": {"data_b64": base64.b64encode(dummy_pcm).decode("utf-8")},
            }
        )
        ws.send_json({"type": "AUDIO_END", "request_id": "voice_seamless_1"})

        seen = []
        for _ in range(30):
            msg = ws.receive_json()
            seen.append(msg)
            if msg.get("type") == "TASK_FINISHED" and msg.get("request_id") == "voice_seamless_1":
                break

        asr_final = [
            m for m in seen if m.get("type") == "ASR_FINAL" and m.get("request_id") == "voice_seamless_1"
        ]
        assert asr_final

        payload = asr_final[-1].get("payload") or {}
        assert payload.get("text") == "hello from seamless"

        assert calls["seamless_factory"] >= 1
        assert calls["transcribe"] >= 1
        assert not any(m.get("type") == "LLM_RESULT" for m in seen)
        assert not any(m.get("type") == "TTS_RESULT" for m in seen)


def test_ws_voice_kokoro_interface_wiring(tmp_path: Path, monkeypatch) -> None:
    _setup_test_db(tmp_path)

    calls = {
        "kokoro": 0,
        "seamless_factory": 0,
    }

    def fake_seamless_factory(*, model_name: str = "small", device: str = "cpu", compute_type: str = "int8"):
        calls["seamless_factory"] += 1

        def _transcriber(_audio: bytes, _cfg):
            return "hello from asr"

        return _transcriber

    async def fake_stream_chat(*, system_prompt: str, user_text: str, history=None):
        yield "assistant reply"

    expected_wav = b"RIFFTEST-WAV-BYTES"

    def fake_kokoro(_text: str) -> bytes:
        calls["kokoro"] += 1
        return expected_wav

    monkeypatch.setattr("app.main.try_create_seamless_transcriber", fake_seamless_factory)
    monkeypatch.setattr("app.main.stream_chat", fake_stream_chat)
    monkeypatch.setattr("app.tts._synthesize_kokoro_wav", fake_kokoro)

    monkeypatch.setattr("app.main.settings.enable_asr", True)
    monkeypatch.setattr("app.main.settings.asr_backend", "seamless")
    monkeypatch.setattr("app.main.settings.tts_backend", "kokoro")

    client = TestClient(app)
    with client.websocket_connect("/ws/v1?session_id=test&conversation_id=conv_backend_kokoro") as ws:
        _ = ws.receive_json()  # server TASK_STARTED

        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "voice_kokoro_1",
                "payload": {
                    "sample_rate": 16000,
                    "channels": 1,
                    "encoding": "pcm_s16le",
                },
            }
        )
        _ = ws.receive_json()  # request TASK_STARTED

        dummy_pcm = b"\x00\x00" * 320
        ws.send_json(
            {
                "type": "AUDIO_CHUNK",
                "request_id": "voice_kokoro_1",
                "payload": {"data_b64": base64.b64encode(dummy_pcm).decode("utf-8")},
            }
        )
        ws.send_json({"type": "AUDIO_END", "request_id": "voice_kokoro_1"})

        seen = []
        for _ in range(50):
            msg = ws.receive_json()
            seen.append(msg)
            if msg.get("type") == "TASK_FINISHED" and msg.get("request_id") == "voice_kokoro_1":
                break

        assert any(m.get("type") == "ASR_FINAL" for m in seen)
        assert any(m.get("type") == "LLM_RESULT" for m in seen)

        tts_result = [
            m for m in seen if m.get("type") == "TTS_RESULT" and m.get("request_id") == "voice_kokoro_1"
        ]
        assert tts_result

        audio_b64 = (tts_result[-1].get("payload") or {}).get("audio_base64")
        assert isinstance(audio_b64, str)
        assert base64.b64decode(audio_b64.encode("utf-8")) == expected_wav

        assert calls["seamless_factory"] >= 1
        assert calls["kokoro"] >= 1
