from __future__ import annotations

import io
import threading
import wave

from .settings import settings


def synthesize_wav_silence(
    text: str,
    *,
    sample_rate: int = 16000,
    channels: int = 1,
) -> bytes:
    """Minimal TTS placeholder: returns a WAV of silence.

    This keeps the WS protocol stable (TTS_CHUNK/TTS_RESULT) without requiring
    external TTS runtimes.
    """

    # Duration heuristic: small but non-zero to allow chunking in tests.
    n = len((text or "").strip())
    seconds = 0.25 + min(2.0, n * 0.01)
    frames = max(1, int(sample_rate * seconds))

    # 16-bit PCM silence.
    silence = b"\x00\x00" * frames * channels

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(int(channels))
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(silence)

    return buf.getvalue()


def synthesize_tts_wav(text: str) -> bytes:
    """Synthesize TTS audio as a single WAV bytes blob.

    Backend priority (configurable via AIFL_TTS_BACKEND):
    - kokoro     : lightweight local TTS (82M params, CPU real-time, recommended)
    - edge       : Microsoft Edge online TTS (free, 100+ languages, no GPU)
    - silence    : placeholder (default fallback)

    Automatic fallback: if the preferred backend fails, try the next in chain.
    """

    backend = (settings.tts_backend or "silence").strip().lower()

    # Build fallback chain based on preferred backend.
    # Always end with silence as ultimate fallback.
    chain: list[str] = []
    if backend == "kokoro":
        chain = ["kokoro", "edge", "silence"]
    elif backend == "edge":
        chain = ["edge", "kokoro", "silence"]
    elif backend in ("silence", "none", "stub"):
        chain = ["silence"]
    else:
        chain = [backend, "silence"]

    last_error = ""
    for b in chain:
        try:
            if b == "kokoro":
                return _synthesize_kokoro_wav(text)
            if b == "edge":
                return _synthesize_edge_wav(text)
            if b in ("silence", "none", "stub"):
                return synthesize_wav_silence(text)
        except Exception as e:
            last_error = str(e)
            continue

    # Ultimate fallback: silence with error logged.
    import logging

    logging.getLogger(__name__).warning(f"All TTS backends failed (last: {last_error}). Falling back to silence.")
    return synthesize_wav_silence(text)


# ---------- Kokoro TTS (lightweight, CPU real-time) ----------
_kokoro_lock = threading.Lock()
_kokoro_pipeline = None


def _get_kokoro_pipeline():
    global _kokoro_pipeline
    with _kokoro_lock:
        if _kokoro_pipeline is not None:
            return _kokoro_pipeline

        # Try original kokoro first, fallback to kokoro-onnx
        try:
            from kokoro import KPipeline  # type: ignore
            _kokoro_pipeline = ("original", KPipeline(lang_code=(settings.kokoro_lang_code or "a").strip() or "a"))
            return _kokoro_pipeline
        except ImportError:
            pass

        try:
            import os

            from kokoro_onnx import Kokoro  # type: ignore

            model_dir = os.path.join(os.path.dirname(__file__), "..", "data", "models", "kokoro")
            model_path = os.path.join(model_dir, "onnx", "model.onnx")
            voices_path = os.path.join(model_dir, "voices", "voices.npy")
            if not os.path.exists(model_path) or not os.path.exists(voices_path):
                raise ImportError(f"Kokoro ONNX model not found at {model_dir}")
            _kokoro_pipeline = ("onnx", Kokoro(model_path, voices_path))
            return _kokoro_pipeline
        except ImportError as e:
            raise ImportError(f"kokoro not installed and kokoro-onnx unavailable: {e}")


def _synthesize_kokoro_wav(text: str) -> bytes:
    """Kokoro TTS -> WAV bytes.

    82M params, CPU real-time, high quality English TTS.
    Supports both original kokoro (KPipeline) and kokoro-onnx.
    """

    backend, pipeline = _get_kokoro_pipeline()
    voice = (settings.kokoro_voice or "af_bella").strip() or "af_bella"
    speed = float(settings.kokoro_speed or 1.0)

    import numpy as np  # type: ignore

    if backend == "original":
        # Original kokoro KPipeline API
        audio_chunks: list = []
        sample_rate = 24000
        for _graphemes, _phonemes, audio in pipeline(text or "", voice=voice, speed=speed):
            if audio is not None and len(audio) > 0:
                audio_chunks.append(audio)
        if not audio_chunks:
            raise RuntimeError("Kokoro produced no audio")
        combined = np.concatenate(audio_chunks)
    else:
        # kokoro-onnx API
        audio, sample_rate = pipeline.create(text or "", voice=voice, speed=speed)
        combined = audio.squeeze() if audio.ndim > 1 else audio

    # Convert float32 [-1, 1] to int16 PCM
    pcm = (combined * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm.tobytes())

    return buf.getvalue()


# ---------- Edge TTS (online, free, multilingual) ----------
_edge_lock = threading.Lock()


def _synthesize_edge_wav(text: str) -> bytes:
    """Microsoft Edge online TTS -> WAV bytes.

    Free, no API key, 100+ languages. Requires network.
    Converts MP3 output to WAV for protocol consistency.
    """

    try:
        import edge_tts  # type: ignore
    except ImportError:
        raise ImportError("edge-tts not installed; run: pip install edge-tts")

    voice = (settings.edge_tts_voice or "en-US-AriaNeural").strip() or "en-US-AriaNeural"
    speed = str(settings.edge_tts_speed or "+0%").strip() or "+0%"

    import asyncio

    async def _fetch() -> bytes:
        communicate = edge_tts.Communicate(text or "", voice, rate=speed)
        mp3_buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_buf.write(chunk["data"])
        return mp3_buf.getvalue()

    mp3_bytes = asyncio.run(_fetch())
    if not mp3_bytes:
        raise RuntimeError("Edge TTS returned empty audio")

    # Convert MP3 -> WAV using pydub (lightweight) or fallback to silence if unavailable.
    try:
        from pydub import AudioSegment  # type: ignore

        seg = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
        # Resample to 16kHz mono 16-bit for consistency with current protocol.
        seg = seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        wav_buf = io.BytesIO()
        seg.export(wav_buf, format="wav")
        return wav_buf.getvalue()
    except ImportError:
        # pydub not available: try ffmpeg directly or return MP3 wrapped in WAV header.
        # As a pragmatic fallback, return silence with a warning.
        import logging

        logging.getLogger(__name__).warning("pydub not installed; cannot convert Edge TTS MP3 to WAV. Install: pip install pydub")
        raise RuntimeError("pydub required for Edge TTS MP3->WAV conversion")


