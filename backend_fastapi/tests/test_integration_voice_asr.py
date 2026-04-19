from __future__ import annotations

import base64
import os
import threading
import time
from pathlib import Path

import pytest

sf = pytest.importorskip("soundfile")
pytest.importorskip("librosa")
from fastapi.testclient import TestClient


def _load_app_with_current_env():
    """Load FastAPI app after env vars are set.

    Important: other tests may have imported app already in this pytest process;
    for integration we want env-driven settings (ENABLE_ASR, backend, model) to apply.
    """

    import importlib

    import app.main as main_mod
    import app.settings as settings_mod

    importlib.reload(settings_mod)
    importlib.reload(main_mod)
    return main_mod.app


def _integration_enabled() -> bool:
    return os.getenv("AIFL_RUN_INTEGRATION", "").strip() in {"1", "true", "True"}


def _expected_contains() -> str:
    return os.getenv("AIFL_ASR_EXPECT_CONTAINS", "").strip()


def _load_asr_test_pcm_16k() -> bytes:
    wav_path = Path(__file__).resolve().parents[2] / "testresources" / "ASRtest.wav"
    if not wav_path.exists():
        raise FileNotFoundError(str(wav_path))

    audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)

    # 转单声道
    if hasattr(audio, "ndim") and getattr(audio, "ndim") == 2:
        audio = audio.mean(axis=1)

    # 重采样到 16k
    if int(sr) != 16000:
        import librosa

        audio = librosa.resample(audio, orig_sr=int(sr), target_sr=16000)

    # float32 [-1,1] -> int16 PCM
    import numpy as np

    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767.0).astype(np.int16).tobytes()
    return pcm


@pytest.mark.integration
@pytest.mark.timeout(600)
def test_integration_voice_asr_produces_real_text(capfd) -> None:
    if not _integration_enabled():
        pytest.skip("integration tests disabled (set AIFL_RUN_INTEGRATION=1)")

    # 该测试要求：按生产方式启用 ASR（ENABLE_ASR=true），并配置 asr_backend/asr_model
    # 如果未启用，将只得到占位文案，视为不可用。

    # 默认开启（允许外部环境覆盖）
    os.environ.setdefault("AIFL_ENABLE_ASR", "1")
    os.environ.setdefault("AIFL_ASR_BACKEND", "seamless")
    os.environ.setdefault("AIFL_VOICE_EMIT_ASR_TEXT", "1")

    app = _load_app_with_current_env()

    pcm = _load_asr_test_pcm_16k()

    # 为了在 CI/本地回归时可控，这里默认只按“真实时间”推送前 N 秒的音频。
    # 你可以设置 AIFL_ASR_STREAM_SECONDS<=0 来推送完整音频。
    stream_seconds_raw = os.getenv("AIFL_ASR_STREAM_SECONDS", "30").strip()
    try:
        stream_seconds = float(stream_seconds_raw)
    except ValueError:
        stream_seconds = 30.0

    bytes_per_second = 16000 * 2  # 16kHz * int16
    if stream_seconds > 0:
        pcm = pcm[: int(stream_seconds * bytes_per_second)]

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/v1?session_id=integration&conversation_id=conv_voice_int"
        ) as ws:
            _ = ws.receive_json()  # initial TASK_STARTED

            ws.send_json(
                {
                    "type": "AUDIO_START",
                    "request_id": "voice_int_1",
                    "payload": {
                        "sample_rate": 16000,
                        "channels": 1,
                        "encoding": "pcm_s16le",
                        "language": "en",
                        "asr_only": True,
                    },
                }
            )
            _ = ws.receive_json()  # TASK_STARTED for voice

            # 后台接收线程：实时收集 ASR_PARTIAL/ASR_FINAL，避免 send 侧 backpressure。
            received: list[dict] = []
            stop_evt = threading.Event()

            def _recv_loop() -> None:
                while not stop_evt.is_set():
                    try:
                        msg = ws.receive_json()
                    except Exception:
                        break
                    received.append(msg)
                    if msg.get("type") == "TASK_FINISHED":
                        break

            t = threading.Thread(target=_recv_loop, name="ws-recv", daemon=True)
            t.start()

            # 0.2s/chunk: 16kHz * 0.2s = 3200 samples; int16 => 6400 bytes
            chunk_size = 6400
            chunk_interval_s = 0.2
            for i in range(0, len(pcm), chunk_size):
                chunk = pcm[i : i + chunk_size]
                ws.send_json(
                    {
                        "type": "AUDIO_CHUNK",
                        "request_id": "voice_int_1",
                        "payload": {"data_b64": base64.b64encode(chunk).decode("utf-8")},
                    }
                )
                time.sleep(chunk_interval_s)

            ws.send_json({"type": "AUDIO_END", "request_id": "voice_int_1"})

            t.join(timeout=120)
            stop_evt.set()

            # 断言：必须拿到实时 partial + 最终 final
            asr_partials = [m for m in received if m.get("type") == "ASR_PARTIAL"]
            asr_finals = [m for m in received if m.get("type") == "ASR_FINAL"]
            assert asr_finals, f"no ASR_FINAL received; got types={[m.get('type') for m in received]}"
            assert not any(m.get("type") == "LLM_RESULT" for m in received)
            assert not any(m.get("type") == "TTS_RESULT" for m in received)
            asr_final = asr_finals[-1]
            text = (asr_final.get("payload") or {}).get("text")
            assert isinstance(text, str)

            if not asr_partials:
                # 在真实时间流速下，应当能看到至少一次 partial（除非音频极短/静音）。
                pytest.fail(f"expected ASR_PARTIAL during streaming; got types={[m.get('type') for m in received]}")

            # 必须不是占位文案（否则说明生产 ASR 未启用或不可用）
            assert "未启用" not in text

            # 预期：后端输出不应包含 legacy ASR 后端的噪声信息。
            out, err = capfd.readouterr()
            combined = (out + "\n" + err).lower()
            assert "ctranslate2" not in combined
            assert "faster_whisper" not in combined

            expected = _expected_contains()
            if expected:
                assert expected.lower() in text.lower()
            else:
                # 说明：仓库内未提供 ASRtest.wav 的“金标文本”，只能做弱验证。
                # 若你要我亲自确认语义正确性，请设置 AIFL_ASR_EXPECT_CONTAINS 或提供对照文本文件。
                assert len(text.strip()) >= 8


@pytest.mark.integration
@pytest.mark.timeout(600)
def test_integration_voice_asr_vad_auto_end_asr_only(capfd) -> None:
    if not _integration_enabled():
        pytest.skip("integration tests disabled (set AIFL_RUN_INTEGRATION=1)")

    os.environ.setdefault("AIFL_ENABLE_ASR", "1")
    os.environ.setdefault("AIFL_ASR_BACKEND", "seamless")
    os.environ.setdefault("AIFL_VOICE_EMIT_ASR_TEXT", "1")

    app = _load_app_with_current_env()
    pcm = _load_asr_test_pcm_16k()

    # 只推送前 6 秒语音，然后追加 1.2 秒静音，让 VAD 能够自动收句。
    bytes_per_second = 16000 * 2
    pcm = pcm[: int(6.0 * bytes_per_second)]
    silence = b"\x00\x00" * int(16000 * 1.2)
    pcm = pcm + silence

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/v1?session_id=integration&conversation_id=conv_voice_vad"
        ) as ws:
            _ = ws.receive_json()  # initial TASK_STARTED

            ws.send_json(
                {
                    "type": "AUDIO_START",
                    "request_id": "voice_vad_1",
                    "payload": {
                        "sample_rate": 16000,
                        "channels": 1,
                        "encoding": "pcm_s16le",
                        "language": "en",
                        "asr_only": True,
                        "vad_enabled": True,
                        "vad_silence_ms": 800,
                    },
                }
            )
            _ = ws.receive_json()  # TASK_STARTED for voice

            received: list[dict] = []
            stop_evt = threading.Event()

            def _recv_loop() -> None:
                while not stop_evt.is_set():
                    try:
                        msg = ws.receive_json()
                    except Exception:
                        break
                    received.append(msg)
                    if msg.get("type") == "TASK_FINISHED":
                        break

            t = threading.Thread(target=_recv_loop, name="ws-recv-vad", daemon=True)
            t.start()

            chunk_size = 6400
            chunk_interval_s = 0.2
            for i in range(0, len(pcm), chunk_size):
                chunk = pcm[i : i + chunk_size]
                ws.send_json(
                    {
                        "type": "AUDIO_CHUNK",
                        "request_id": "voice_vad_1",
                        "payload": {"data_b64": base64.b64encode(chunk).decode("utf-8")},
                    }
                )
                time.sleep(chunk_interval_s)

            # 注意：不发送 AUDIO_END，依赖 VAD 自动收句。

            t.join(timeout=120)
            stop_evt.set()

            asr_finals = [m for m in received if m.get("type") == "ASR_FINAL"]
            assert asr_finals, f"no ASR_FINAL received; got types={[m.get('type') for m in received]}"
            assert any(m.get("type") == "TASK_FINISHED" for m in received)
            assert not any(m.get("type") == "LLM_RESULT" for m in received)
            assert not any(m.get("type") == "TTS_RESULT" for m in received)

            text = ((asr_finals[-1].get("payload") or {}).get("text"))
            assert isinstance(text, str)
            assert "未启用" not in text
            assert len(text.strip()) >= 1
            assert any(ch.isalpha() for ch in text)

            reason = ((asr_finals[-1].get("payload") or {}).get("reason"))
            assert reason == "vad"

            out, err = capfd.readouterr()
            combined = (out + "\n" + err).lower()
            assert "ctranslate2" not in combined
            assert "faster_whisper" not in combined
