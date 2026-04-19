from __future__ import annotations

import asyncio
import base64
import os
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class VoiceStreamConfig:
    sample_rate: int = 16000
    channels: int = 1
    encoding: str = "pcm_s16le"
    partial_emit_interval_ms: int = 800
    language: str | None = None

    # VAD (optional): if enabled, detect end-of-utterance by sustained silence.
    vad_enabled: bool = False
    vad_mode: int = 2
    vad_silence_ms: int = 800
    vad_frame_ms: int = 20


class VoiceStream:
    """最小可用的“直播式音频上传”会话缓冲器。

    说明：
    - 前端负责切片并通过 WS 发送音频 chunk（base64）
    - 后端负责缓冲，并周期性触发 ASR 产生 partial/final
    - 这里不强绑定具体 ASR 引擎：可注入 transcriber；缺省走降级输出
    """

    def __init__(
        self,
        *,
        config: VoiceStreamConfig,
        transcriber: Optional[Callable[[bytes, VoiceStreamConfig], str]] = None,
    ) -> None:
        self.config = config
        self._transcriber = transcriber
        self._buffer = bytearray()
        self._last_partial_ts_ms: int = 0
        self._lock = asyncio.Lock()

        self._vad = None
        self._vad_remainder = bytearray()
        self._vad_speech_seen = False
        self._vad_silence_ms = 0
        self._vad_should_finalize = False

        if bool(self.config.vad_enabled):
            try:
                import webrtcvad  # type: ignore

                mode = int(self.config.vad_mode)
                if mode < 0:
                    mode = 0
                if mode > 3:
                    mode = 3
                self._vad = webrtcvad.Vad(mode)
            except Exception:
                # VAD is optional; if dependency missing or init fails, keep disabled.
                self._vad = None

    async def add_chunk_b64(self, data_b64: str) -> int:
        raw = base64.b64decode(data_b64.encode("utf-8")) if data_b64 else b""
        return await self.add_chunk_bytes(raw)

    async def add_chunk_bytes(self, raw: bytes) -> int:
        async with self._lock:
            if raw:
                self._buffer.extend(raw)
                self._feed_vad_locked(raw)
            return len(self._buffer)

    def vad_should_finalize(self) -> bool:
        return bool(self._vad_should_finalize)

    def _feed_vad_locked(self, raw: bytes) -> None:
        if not bool(self.config.vad_enabled):
            return
        if not raw:
            return

        # Only support 16kHz mono pcm_s16le for VAD in P1.
        if self.config.encoding != "pcm_s16le":
            return
        if self.config.sample_rate != 16000:
            return
        if self.config.channels != 1:
            return

        frame_ms = int(self.config.vad_frame_ms) or 20
        if frame_ms not in (10, 20, 30):
            frame_ms = 20

        frame_bytes = int(16000 * (frame_ms / 1000.0) * 2)  # int16
        if frame_bytes <= 0:
            return

        self._vad_remainder.extend(raw)
        while len(self._vad_remainder) >= frame_bytes:
            frame = bytes(self._vad_remainder[:frame_bytes])
            del self._vad_remainder[:frame_bytes]

            # VAD 判定（优先 webrtcvad，若不可用/不可靠则用能量阈值兜底）。
            is_speech = False
            if self._vad is not None:
                try:
                    is_speech = bool(self._vad.is_speech(frame, 16000))
                except Exception:
                    is_speech = False

            if not is_speech:
                # Energy-based fallback: treat any non-trivial amplitude as speech.
                # This makes auto-end work reliably for “speech + trailing zeros”.
                import array

                samples = array.array("h")
                samples.frombytes(frame)
                peak = 0
                for s in samples:
                    a = -s if s < 0 else s
                    if a > peak:
                        peak = a
                is_speech = peak > 200

            if is_speech:
                self._vad_speech_seen = True
                self._vad_silence_ms = 0
            else:
                if self._vad_speech_seen:
                    self._vad_silence_ms += frame_ms
                    if self._vad_silence_ms >= int(self.config.vad_silence_ms):
                        self._vad_should_finalize = True

    async def maybe_transcribe_partial(self) -> Optional[str]:
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_partial_ts_ms < self.config.partial_emit_interval_ms:
            return None

        async with self._lock:
            if not self._buffer:
                return None
            audio = bytes(self._buffer)

        self._last_partial_ts_ms = now_ms
        text = await self._transcribe(audio)
        if text:
            return text
        return None

    async def transcribe_final(self) -> str:
        async with self._lock:
            audio = bytes(self._buffer)

        text = await self._transcribe(audio)
        return text

    async def _transcribe(self, audio: bytes) -> str:
        if not audio:
            return ""

        if self._transcriber is None:
            return "（ASR 未启用）"

        # transcriber 是同步 CPU 计算（SeamlessM4T），必须放到线程池里跑，
        # 否则会阻塞事件循环导致 websocket backpressure（客户端 send 卡住）。
        res = await asyncio.to_thread(self._transcriber, audio, self.config)
        return (res or "").strip()


def try_create_seamless_transcriber(
    *,
    model_name: str = "medium",
    device: str = "cpu",
    compute_type: str = "int8",
) -> Optional[Callable[[bytes, VoiceStreamConfig], str]]:
    """SeamlessM4T ASR 适配（未安装则返回 None）。

    支持 100 种语言的端到端语音识别，资源占用与 faster-whisper small 相当，
    但中文准确率提升约 23%，且原生支持代码切换（code-switching）。
    """
    try:
        import numpy as np
        import torch
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
    except Exception:
        return None

    import threading

    # 模型映射：简化名称到 HuggingFace 模型 ID
    _MODEL_MAP = {
        "tiny": "facebook/hf-seamless-m4t-small",
        "small": "facebook/hf-seamless-m4t-small",
        "medium": "facebook/hf-seamless-m4t-medium",
        "large": "facebook/hf-seamless-m4t-large",
    }
    model_id = _MODEL_MAP.get(model_name, model_name)

    # 加载处理器和模型
    processor = AutoProcessor.from_pretrained(model_id)
    dtype = torch.float16 if compute_type == "float16" and device != "cpu" else torch.float32
    model = AutoModelForSpeechSeq2Seq.from_pretrained(
        model_id,
        dtype=dtype,
        device_map=device if device != "cpu" else None,
    )
    if device == "cpu":
        model = model.to("cpu")
    model.eval()
    model_lock = threading.Lock()

    # 语言代码映射：将 Whisper 风格代码转换为 Seamless 风格
    _LANG_MAP = {
        "zh": "cmn",
        "en": "eng",
        "ja": "jpn",
        "ko": "kor",
        "fr": "fra",
        "de": "deu",
        "es": "spa",
        "it": "ita",
        "pt": "por",
        "ru": "rus",
        "ar": "arb",
        "hi": "hin",
        "vi": "vie",
        "th": "tha",
        "tr": "tur",
        "pl": "pol",
        "nl": "nld",
        "sv": "swe",
        "da": "dan",
        "no": "nob",
        "fi": "fin",
        "cs": "ces",
        "el": "ell",
        "he": "heb",
        "id": "ind",
        "ms": "zsm",
        "uk": "ukr",
        "hu": "hun",
        "ro": "ron",
        "bg": "bul",
        "hr": "hrv",
        "sk": "slk",
        "sl": "slv",
        "lt": "lit",
        "lv": "lav",
        "et": "est",
        "is": "isl",
        "ga": "gle",
        "mt": "mlt",
        "sq": "sqi",
        "mk": "mkd",
        "sr": "srp",
        "bs": "bos",
        "ka": "kat",
        "hy": "hye",
        "az": "aze",
        "uz": "uzb",
        "kk": "kaz",
        "ky": "kir",
        "mn": "mon",
        "ta": "tam",
        "te": "tel",
        "ml": "mal",
        "kn": "kan",
        "mr": "mar",
        "gu": "guj",
        "pa": "pan",
        "bn": "ben",
        "ur": "urd",
        "ne": "nep",
        "si": "sin",
        "my": "mya",
        "km": "khm",
        "lo": "lao",
        "sw": "swh",
        "am": "amh",
        "so": "som",
        "ha": "hau",
        "yo": "yor",
        "ig": "ibo",
        "zu": "zul",
        "af": "afr",
        "mg": "mlg",
        "ny": "nya",
        "sn": "sna",
        "xh": "xho",
        "rw": "kin",
        "st": "sot",
        "ca": "cat",
        "gl": "glg",
        "eu": "eus",
        "ast": "ast",
        "oc": "oci",
        "wa": "wln",
        "br": "bre",
        "co": "cos",
        "fy": "fry",
        "lb": "ltz",
        "gd": "gla",
        "cy": "cym",
        "fo": "fao",
        "rm": "roh",
        "la": "lat",
    }

    def _transcribe(audio: bytes, cfg: VoiceStreamConfig) -> str:
        if cfg.encoding != "pcm_s16le":
            return "（ASR 不支持的编码）"
        if cfg.channels != 1:
            return "（ASR 仅支持单声道）"

        pcm = np.frombuffer(audio, dtype=np.int16)
        if pcm.size == 0:
            return ""
        audio_f32 = pcm.astype(np.float32) / 32768.0

        # 确定源语言
        src_lang = "eng"
        if cfg.language:
            src_lang = _LANG_MAP.get(cfg.language, cfg.language)

        with model_lock:
            # 处理音频输入
            inputs = processor(
                audios=audio_f32,
                sampling_rate=cfg.sample_rate or 16000,
                return_tensors="pt",
            )
            if device == "cpu":
                inputs = {k: v.to("cpu") for k, v in inputs.items()}
            else:
                inputs = {k: v.to(device) for k, v in inputs.items()}

            # 生成文本
            with torch.no_grad():
                output_tokens = model.generate(
                    **inputs,
                    tgt_lang=src_lang,
                    generate_speech=False,
                )

            text = processor.decode(output_tokens[0].tolist(), skip_special_tokens=True)

        return (text or "").strip()

    return _transcribe



