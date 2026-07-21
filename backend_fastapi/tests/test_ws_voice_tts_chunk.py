from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app.db import init_db, override_engine_for_tests
from app.main import app


def test_ws_voice_tts_chunk_order_and_last(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    async def fake_stream_chat(*, system_prompt: str, user_text: str, history=None):
        yield "hi"

    def fake_tts(_text: str, *, sample_rate: int = 16000, channels: int = 1) -> bytes:
        # Force multi-chunk payload: 40KB
        return b"X" * (40 * 1024)

    monkeypatch.setattr("app.main.stream_chat", fake_stream_chat)
    monkeypatch.setattr("app.main.synthesize_tts_wav", lambda text: fake_tts(text))
    monkeypatch.setattr(
        "app.main.try_create_seamless_transcriber",
        lambda **_: (lambda _audio, _cfg: "hello from asr"),
    )
    monkeypatch.setattr("app.main.settings.enable_asr", True)
    monkeypatch.setattr("app.main.settings.asr_backend", "seamless")

    client = TestClient(app)
    with client.websocket_connect("/ws/v1?session_id=test&conversation_id=conv_voice_tts") as ws:
        _ = ws.receive_json()  # server TASK_STARTED

        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "voice1",
                "payload": {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"},
            }
        )
        _ = ws.receive_json()  # TASK_STARTED voice1

        dummy_pcm = b"\x00\x00" * 320
        ws.send_json(
            {
                "type": "AUDIO_CHUNK",
                "request_id": "voice1",
                "payload": {"data_b64": base64.b64encode(dummy_pcm).decode("utf-8")},
            }
        )
        ws.send_json({"type": "AUDIO_END", "request_id": "voice1"})

        seen = []
        for _ in range(80):
            m = ws.receive_json()
            seen.append(m)
            if m.get("type") == "TASK_FINISHED":
                break

        types = [m.get("type") for m in seen]
        assert "LLM_RESULT" in types
        assert "TTS_CHUNK" in types
        assert "TTS_RESULT" in types
        assert "TTS_STREAM_END" in types

        assert types.index("TTS_CHUNK") < types.index("TTS_STREAM_END")
        assert types.index("TTS_STREAM_END") < types.index("TASK_FINISHED")

        chunks = [m for m in seen if m.get("type") == "TTS_CHUNK"]
        assert len(chunks) >= 2
        idxs = []
        for c in chunks:
            idx = (c.get("payload") or {}).get("index")
            assert idx is not None
            idxs.append(int(idx))
        assert idxs == list(range(len(chunks)))

        last = chunks[-1]
        assert bool((last.get("payload") or {}).get("is_last")) is True

        # Data should be valid base64.
        for c in chunks:
            b64 = (c.get("payload") or {}).get("data_b64")
            assert isinstance(b64, str)
            base64.b64decode(b64.encode("utf-8"))


def test_ws_text_tts_starts_after_first_sentence_before_llm_finishes(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "test_live_tts.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    async def fake_stream_chat(**_kwargs):
        yield "First sentence."
        await asyncio.sleep(0.08)
        yield " Second sentence."

    monkeypatch.setattr("app.main.stream_chat", fake_stream_chat)
    monkeypatch.setattr("app.main.synthesize_tts_wav", lambda text: f"wav:{text}".encode())

    client = TestClient(app)
    with client.websocket_connect("/ws/v1?session_id=test&conversation_id=conv_live_tts") as ws:
        _ = ws.receive_json()
        ws.send_json(
            {
                "type": "TEXT",
                "request_id": "text_live_tts",
                "payload": {"text": "hello"},
            }
        )

        seen = []
        for _ in range(40):
            message = ws.receive_json()
            seen.append(message)
            if message.get("type") == "TASK_FINISHED":
                break

    types = [message.get("type") for message in seen]
    first_tts_result = types.index("TTS_RESULT")
    assert types.index("LLM_TOKEN") < first_tts_result < types.index("LLM_RESULT")
    assert types.index("TTS_STREAM_END") < types.index("TASK_FINISHED")

    tts_results = [message for message in seen if message.get("type") == "TTS_RESULT"]
    assert [message["payload"]["text"] for message in tts_results] == [
        "First sentence.",
        "Second sentence.",
    ]
    assert all(message["payload"]["is_final_segment"] is False for message in tts_results)

    stream_end = next(message for message in seen if message.get("type") == "TTS_STREAM_END")
    assert stream_end["payload"]["tts_streaming"] is True
    assert stream_end["payload"]["tts_segment_count"] == 2
