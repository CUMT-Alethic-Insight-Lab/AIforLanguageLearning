#!/usr/bin/env python
import os
import sys
import json
import argparse
from pathlib import Path
from typing import Optional, Dict, Any


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Faster-Whisper CLI (tri-lingual ready, VAD endpoint, CPU-friendly)"
    )
    p.add_argument("--audio", required=False, default=None,
                   help="Path to input audio file (wav/ogg/mp3...). Default: env_check/zero_shot_prompt.wav")
    p.add_argument("--model-size", default=os.getenv("FASTWHISPER_MODEL_SIZE", "medium"),
                   help="Model size if not using --model-dir (e.g., tiny/base/small/medium/large-v3)")
    p.add_argument("--model-dir", default=os.getenv("FASTWHISPER_MODEL_DIR"),
                   help="Local model directory (overrides --model-size if provided)")
    p.add_argument("--device", default=os.getenv("FASTWHISPER_DEVICE", "cpu"), choices=["cpu", "cuda"],
                   help="Device to run on")
    p.add_argument("--compute-type", default=os.getenv("FASTWHISPER_COMPUTE", "int8"),
                   help="CTranslate2 compute type (e.g., int8, int8_float16, float16, float32)")
    p.add_argument("--beam-size", type=int, default=int(os.getenv("FASTWHISPER_BEAM", "2")),
                   help="Beam size (1 for lowest latency, 2 for slightly more robustness)")
    p.add_argument("--language", default=os.getenv("FASTWHISPER_LANG", "auto"),
                   help="Language code (zh/en/ja) or 'auto' for auto-detect")
    p.add_argument("--vad-min-silence-ms", type=int, default=int(os.getenv("FASTWHISPER_VAD_MIN", "400")),
                   help="VAD minimum silence duration (ms) to trigger endpoint")
    p.add_argument("--vad-pad-ms", type=int, default=int(os.getenv("FASTWHISPER_VAD_PAD", "160")),
                   help="VAD speech pad (ms) to avoid cutting phones at edges")
    p.add_argument("--initial-prompt", default=os.getenv("FASTWHISPER_INIT_PROMPT", ""),
                   help="Initial prompt (domain terms, context). Optional.")
    p.add_argument("--prefix-file", default=os.getenv("FASTWHISPER_PREFIX_FILE"),
                   help="Optional file containing last segment tail as prefix for context continuation")
    p.add_argument("--max-prefix-chars", type=int, default=int(os.getenv("FASTWHISPER_MAX_PREFIX", "80")),
                   help="When using --prefix-file, limit prefix length to last N chars")
    p.add_argument("--vad", dest="vad", action="store_true", help="Enable VAD-based endpointing (default)")
    p.add_argument("--no-vad", dest="vad", action="store_false", help="Disable VAD-based endpointing")
    p.set_defaults(vad=True)
    p.add_argument("--no-speech-threshold", type=float, default=None,
                   help="no_speech_threshold when VAD is disabled (e.g., 0.6). If None, use model default.")
    p.add_argument("--json", action="store_true", help="Output JSON with segments and metadata")
    p.add_argument("--timestamps", action="store_true", help="Include per-segment timestamps in JSON output")
    return p


def load_prefix(prefix_file: Optional[str], max_chars: int) -> Optional[str]:
    if not prefix_file:
        return None
    try:
        txt = Path(prefix_file).read_text(encoding="utf-8").strip()
        if max_chars > 0 and len(txt) > max_chars:
            return txt[-max_chars:]
        return txt
    except Exception:
        return None


def main() -> int:
    args = build_parser().parse_args()

    # Resolve audio path
    if args.audio is None:
        # default to env_check/zero_shot_prompt.wav (neighbor of this script)
        args.audio = str(Path(__file__).with_name("zero_shot_prompt.wav"))
    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"[faster-whisper-cli] Audio not found: {audio_path}")
        return 2

    # Import here to offer clearer error message if missing
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as e:
        print("[faster-whisper-cli] faster-whisper not installed.")
        print("Hint: pip install faster-whisper")
        return 3

    # Model reference
    model_ref = args.model_dir if args.model_dir and Path(args.model_dir).exists() else args.model_size

    # Device & compute type
    device = args.device
    compute_type = args.compute_type

    # Language handling
    language = None if args.language == "auto" else args.language

    # VAD parameters
    vad_params: Dict[str, Any] = {
        "min_silence_duration_ms": args.vad_min_silence_ms,
        "speech_pad_ms": args.vad_pad_ms,
    }

    # Context prefix
    prefix = load_prefix(args.prefix_file, args.max_prefix_chars)

    # Build model
    print(f"[faster-whisper-cli] Loading model: {model_ref} (device={device}, compute={compute_type})")
    model = WhisperModel(model_ref, device=device, compute_type=compute_type)

    # Transcribe
    segments, info = model.transcribe(
        str(audio_path),
        vad_filter=bool(args.vad),
        vad_parameters=vad_params if args.vad else None,
        beam_size=max(1, args.beam_size),
        initial_prompt=(args.initial_prompt or None),
        prefix=prefix,
        language=language,
        temperature=0.0,
        no_speech_threshold=(None if args.vad else args.no_speech_threshold),
    )

    # Aggregate outputs
    det_lang = getattr(info, "language", None)
    det_prob = getattr(info, "language_probability", None)

    if args.json:
        out = {
            "language": det_lang,
            "language_prob": det_prob,
            "model": model_ref,
            "device": device,
            "compute_type": compute_type,
            "beam_size": args.beam_size,
            "vad": vad_params,
            "text": "",
        }
        texts = []
        seg_list = []
        for s in segments:
            texts.append(s.text)
            if args.timestamps:
                seg_list.append({
                    "start": getattr(s, "start", None),
                    "end": getattr(s, "end", None),
                    "text": s.text,
                })
        out["text"] = "".join(texts)
        if args.timestamps:
            out["segments"] = seg_list
        print(json.dumps(out, ensure_ascii=False))
    else:
        text = "".join(s.text for s in segments)
        print(f"[faster-whisper-cli] Detected language: {det_lang} (p={det_prob:.2f})" if det_lang is not None else "[faster-whisper-cli] Language: N/A")
        print(text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
