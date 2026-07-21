from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app.db import init_db, override_engine_for_tests
from app.main import app


def test_ws_voice_audio_binary_replay_after_disconnect(tmp_path: Path, monkeypatch) -> None:
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

    # 先产生一段二进制语音事件流（会落库）
    with client.websocket_connect("/ws/v1?session_id=test&conversation_id=conv_voice_bin_replay") as ws:
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

        ws.send_json({"type": "AUDIO_CHUNK_BIN", "request_id": "voice1", "payload": {}})
        dummy_pcm = b"\x00\x00" * 320  # 20ms silence at 16kHz mono s16le
        ws.send_bytes(dummy_pcm)

        ws.send_json({"type": "AUDIO_END", "request_id": "voice1"})

        last = msg
        for _ in range(40):
            last = ws.receive_json()
            if last.get("type") == "TASK_FINISHED" and last.get("request_id") == "voice1":
                break

        assert last.get("type") == "TASK_FINISHED"
        max_seq = int(last["seq"])

    # 重连并请求回放：last_seq=0 应回放到最新（至少包含 voice1 的关键事件）
    with client.websocket_connect(
        "/ws/v1?session_id=test&conversation_id=conv_voice_bin_replay&last_seq=0"
    ) as ws:
        replayed = []
        for _ in range(80):
            m = ws.receive_json()
            replayed.append(m)
            if int(m.get("seq", 0)) >= max_seq:
                break

        # 只聚焦 voice1 的关键事件（ws 级别 TASK_STARTED 也会被回放）
        voice1_types = [m.get("type") for m in replayed if m.get("request_id") == "voice1"]
        assert "TASK_STARTED" in voice1_types
        assert "ASR_FINAL" in voice1_types
        assert "LLM_RESULT" in voice1_types
        assert "TTS_CHUNK" in voice1_types
        assert "TTS_RESULT" in voice1_types
        assert "TASK_FINISHED" in voice1_types


def test_ws_voice_barge_in_aborts_previous_with_binary_frames(tmp_path: Path, monkeypatch) -> None:
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
    with client.websocket_connect("/ws/v1?session_id=test&conversation_id=conv_voice_bin_barge") as ws:
        _ = ws.receive_json()  # server TASK_STARTED

        dummy_pcm = b"\x00\x00" * 320  # 20ms silence at 16kHz mono s16le

        # Voice 1 (binary frames)
        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "voice1",
                "payload": {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"},
            }
        )
        m = ws.receive_json()
        assert m["type"] == "TASK_STARTED" and m["request_id"] == "voice1"

        ws.send_json({"type": "AUDIO_CHUNK_BIN", "request_id": "voice1", "payload": {}})
        ws.send_bytes(dummy_pcm)
        ws.send_json({"type": "AUDIO_END", "request_id": "voice1"})

        # Barge-in: start a new utterance while voice1 is still finalizing.
        ws.send_json(
            {
                "type": "AUDIO_START",
                "request_id": "voice2",
                "payload": {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le", "asr_only": True},
            }
        )

        ws.send_json({"type": "AUDIO_CHUNK_BIN", "request_id": "voice2", "payload": {}})
        ws.send_bytes(dummy_pcm)
        ws.send_json({"type": "AUDIO_END", "request_id": "voice2"})

        seen = []
        for _ in range(80):
            msg = ws.receive_json()
            seen.append(msg)
            if msg.get("type") == "TASK_FINISHED" and msg.get("request_id") == "voice2":
                break

        # voice1 should be aborted and finished (ok=False)
        aborted = [m for m in seen if m.get("type") == "TASK_ABORTED" and m.get("request_id") == "voice1"]
        assert aborted, f"expected TASK_ABORTED for voice1; got types={[m.get('type') for m in seen]}"

        finished1 = [m for m in seen if m.get("type") == "TASK_FINISHED" and m.get("request_id") == "voice1"]
        assert finished1, f"expected TASK_FINISHED for voice1; got types={[m.get('type') for m in seen]}"
        assert (finished1[-1].get("payload") or {}).get("ok") is False

        # After abort, voice1 must not emit a final LLM_RESULT nor TTS_CHUNK.
        llm_result_1 = [m for m in seen if m.get("type") == "LLM_RESULT" and m.get("request_id") == "voice1"]
        assert not llm_result_1

        tts_chunks_1 = [m for m in seen if m.get("type") == "TTS_CHUNK" and m.get("request_id") == "voice1"]
        assert not tts_chunks_1

        # voice2 should complete normally as asr_only.
        finished2 = [m for m in seen if m.get("type") == "TASK_FINISHED" and m.get("request_id") == "voice2"]
        assert finished2, f"expected TASK_FINISHED for voice2; got types={[m.get('type') for m in seen]}"
        assert (finished2[-1].get("payload") or {}).get("ok") is True
        assert (finished2[-1].get("payload") or {}).get("asr_only") is True
