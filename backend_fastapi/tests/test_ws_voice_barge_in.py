from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app.db import init_db, override_engine_for_tests
from app.main import app


def test_ws_voice_barge_in_aborts_previous(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    # Force the first request to have a long-running LLM stream so we can barge-in deterministically.
    async def fake_stream_chat(*, system_prompt: str, user_text: str, history=None):
        yield "token1"
        await asyncio.sleep(5)
        yield "token2"

    monkeypatch.setattr("app.main.stream_chat", fake_stream_chat)
    monkeypatch.setattr(
        "app.main.try_create_seamless_transcriber",
        lambda **_: (lambda _audio, _cfg: "hello from asr"),
    )
    monkeypatch.setattr("app.main.settings.enable_asr", True)
    monkeypatch.setattr("app.main.settings.asr_backend", "seamless")

    client = TestClient(app)
    with client.websocket_connect("/ws/v1?session_id=test&conversation_id=conv_voice_barge") as ws:
        _ = ws.receive_json()  # server TASK_STARTED

        dummy_pcm = b"\x00\x00" * 320  # 20ms silence at 16kHz mono s16le
        b64 = base64.b64encode(dummy_pcm).decode("utf-8")

        # Voice 1
        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "voice1",
                "payload": {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"},
            }
        )
        m = ws.receive_json()
        assert m["type"] == "TASK_STARTED" and m["request_id"] == "voice1"

        ws.send_json({"type": "AUDIO_CHUNK", "request_id": "voice1", "payload": {"data_b64": b64}})
        ws.send_json({"type": "AUDIO_END", "request_id": "voice1"})

        # Barge-in: start a new utterance while voice1 is still finalizing.
        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "voice2",
                "payload": {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le", "asr_only": True},
            }
        )

        ws.send_json({"type": "AUDIO_CHUNK", "request_id": "voice2", "payload": {"data_b64": b64}})
        ws.send_json({"type": "AUDIO_END", "request_id": "voice2"})

        seen = []
        for _ in range(60):
            msg = ws.receive_json()
            seen.append(msg)
            if msg.get("type") == "TASK_FINISHED" and msg.get("request_id") == "voice2":
                break

        # voice1 should be aborted and finished (ok=False)
        aborted = [m for m in seen if m.get("type") == "TASK_ABORTED" and m.get("request_id") == "voice1"]
        assert aborted, f"expected TASK_ABORTED for voice1; got types={[m.get('type') for m in seen]}"

        finished1 = [
            m
            for m in seen
            if m.get("type") == "TASK_FINISHED" and m.get("request_id") == "voice1"
        ]
        assert finished1, f"expected TASK_FINISHED for voice1; got types={[m.get('type') for m in seen]}"
        assert (finished1[-1].get("payload") or {}).get("ok") is False

        # After abort, voice1 must not emit a final LLM_RESULT.
        llm_result_1 = [m for m in seen if m.get("type") == "LLM_RESULT" and m.get("request_id") == "voice1"]
        assert not llm_result_1

        tts_chunks_1 = [m for m in seen if m.get("type") == "TTS_CHUNK" and m.get("request_id") == "voice1"]
        assert not tts_chunks_1

        # voice2 should complete normally as asr_only.
        finished2 = [
            m
            for m in seen
            if m.get("type") == "TASK_FINISHED" and m.get("request_id") == "voice2"
        ]
        assert finished2, f"expected TASK_FINISHED for voice2; got types={[m.get('type') for m in seen]}"
        assert (finished2[-1].get("payload") or {}).get("ok") is True
        assert (finished2[-1].get("payload") or {}).get("asr_only") is True
