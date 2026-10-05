#!/usr/bin/env python
"""Minimal microphone streaming ASR using faster-whisper + WebRTC VAD.

Features:
  - Automatic endpointing via WebRTC VAD (configurable silence length).
  - Tri-lingual (zh/en/ja) by auto language detection (can force language).
  - Medium model by default (override with FASTWHISPER_MODEL_SIZE or --model-size).
  - CPU friendly: compute_type=int8 by default.
  - Emits JSON lines per finalized segment and a final summary.

Dependencies (install via pip if missing):
  pip install faster-whisper sounddevice webrtcvad soundfile

Usage examples:
  python run_faster_whisper_mic.py --device cpu --compute-type int8 --model-size medium --language auto
  python run_faster_whisper_mic.py --silence-ms 600 --beam-size 1 --json

Press Ctrl+C to stop. Final transcript printed at end.
"""
import os
import sys
import time
import json
import argparse
from collections import deque
from pathlib import Path

try:
    import sounddevice as sd  # type: ignore
except Exception as e:
    print("[mic-asr] sounddevice not installed.")
    sys.exit(2)
try:
    import webrtcvad  # type: ignore
except Exception as e:
    print("[mic-asr] webrtcvad not installed.")
    sys.exit(3)
try:
    import numpy as np
except Exception as e:
    print("[mic-asr] numpy missing.")
    sys.exit(4)
try:
    from faster_whisper import WhisperModel  # type: ignore
except Exception as e:
    print("[mic-asr] faster-whisper not installed.")
    sys.exit(5)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("Microphone streaming ASR (faster-whisper + WebRTC VAD)")
    p.add_argument("--model-size", default=os.getenv("FASTWHISPER_MODEL_SIZE", "medium"))
    p.add_argument("--model-dir", default=os.getenv("FASTWHISPER_MODEL_DIR"))
    p.add_argument("--device", default=os.getenv("FASTWHISPER_DEVICE", "cpu"), choices=["cpu", "cuda"])
    p.add_argument("--compute-type", default=os.getenv("FASTWHISPER_COMPUTE", "int8"))
    p.add_argument("--beam-size", type=int, default=int(os.getenv("FASTWHISPER_BEAM", "2")))
    p.add_argument("--language", default=os.getenv("FASTWHISPER_LANG", "auto"), help="zh|en|ja|auto")
    p.add_argument("--rate", type=int, default=16000, help="Capture sample rate (Hz)")
    p.add_argument("--frame-ms", type=int, default=30, help="VAD frame size in ms (10/20/30).")
    p.add_argument("--silence-ms", type=int, default=int(os.getenv("MIC_SILENCE_MS", "500")), help="Silence duration to finalize segment.")
    p.add_argument("--max-segment-sec", type=float, default=15.0, help="Force flush segment after this length (s).")
    p.add_argument("--initial-prompt", default=os.getenv("FASTWHISPER_INIT_PROMPT", ""))
    p.add_argument("--json", action="store_true", help="Emit JSON lines per segment + final summary.")
    p.add_argument("--prefix-chars", type=int, default=80, help="Carry last N chars from previous final transcript as prefix.")
    p.add_argument("--no-prefix", action="store_true", help="Disable prefix context.")
    p.add_argument("--input-device", default=os.getenv("FASTWHISPER_INPUT_DEVICE"), help="Input device index or name. Use --list-devices to inspect.")
    p.add_argument("--list-devices", action="store_true", help="List audio devices and exit.")
    p.add_argument("--vumeter", action="store_true", help="Print simple VU meter and VAD state per frame.")
    p.add_argument("--force-flush-sec", type=float, default=6.0, help="Force finalize even without silence after N seconds (s). 0 to disable.")
    p.add_argument("--interactive", action="store_true", help="Interactive wizard: pick device and quick tips.")
    p.add_argument("--no-interactive", dest="interactive", action="store_false")
    p.set_defaults(interactive=True)
    return p


def pcm16_to_bytes(samples: np.ndarray) -> bytes:
    return (samples.clip(-1, 1) * 32767).astype(np.int16).tobytes()


def main() -> int:
    args = build_parser().parse_args()
    if args.list_devices:
        try:
            print("[mic-asr] Available devices:")
            print(sd.query_devices())
        except Exception as e:
            print(f"[mic-asr] Cannot query devices: {e}")
        return 0
    model_ref = args.model_dir if args.model_dir and Path(args.model_dir).exists() else args.model_size
    language = None if args.language == "auto" else args.language

    print(f"[mic-asr] Loading model: {model_ref} (device={args.device}, compute={args.compute_type})")
    model = WhisperModel(model_ref, device=args.device, compute_type=args.compute_type)

    vad = webrtcvad.Vad(3)  # aggressiveness 0-3, 3 = most aggressive
    frame_len = int(args.rate * (args.frame_ms / 1000.0))
    bytes_per_frame = frame_len * 2  # int16
    silence_frames_required = int(args.silence_ms / args.frame_ms)

    audio_buffer = []  # list of np arrays
    frame_times = []
    last_voice_time = None
    segments_text = []
    last_final_text = ""
    start_time_segment = None
    last_force_flush_time = None

    def finalize_segment():
        nonlocal audio_buffer, frame_times, last_voice_time, start_time_segment, last_final_text
        if not audio_buffer:
            return
        pcm = np.concatenate(audio_buffer)
        # avoid flushing extremely tiny chunks (<0.35s)
        if pcm.size < int(args.rate * 0.35):
            return
        # Build prefix
        prefix = None
        if not args.no_prefix and last_final_text:
            prefix = last_final_text[-args.prefix_chars:] if args.prefix_chars > 0 else last_final_text
        # Transcribe single segment
        segs, info = model.transcribe(
            pcm,  # raw audio array
            beam_size=max(1, args.beam_size),
            language=language,
            initial_prompt=(args.initial_prompt or None),
            prefix=prefix,
            temperature=0.0,
            vad_filter=False,
        )
        text = "".join(s.text for s in segs)
        segments_text.append(text)
        last_final_text += text
        if args.json:
            out = {
                "type": "segment",
                "text": text,
                "cumulative_text": last_final_text,
                "language": getattr(info, "language", None),
                "language_prob": getattr(info, "language_probability", None),
            }
            print(json.dumps(out, ensure_ascii=False))
        else:
            print(f"[mic-asr][segment] {text}")
        # Reset buffers
        audio_buffer = []
        frame_times = []
        last_voice_time = None
        start_time_segment = None
        # mark force flush moment
        nonlocal last_force_flush_time
        last_force_flush_time = time.time()

    # Interactive wizard
    if args.interactive:
        print("[mic-asr] === Microphone setup ===")
        try:
            devs = sd.query_devices()
            default_in = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else sd.default.device
            print(f"[mic-asr] Default input device: {default_in}")
            if args.input_device is None:
                print("[mic-asr] Available devices (index : name) → look for your mic:")
                for i, d in enumerate(devs):
                    if d.get('max_input_channels', 0) > 0:
                        print(f"  {i:2d}: {d.get('name','?')} (in={d.get('max_input_channels')}, {d.get('hostapi') if 'hostapi' in d else ''})")
                choice = input("[mic-asr] Enter device index to use (blank = default): ").strip()
                if choice:
                    args.input_device = int(choice) if choice.isdigit() else choice
                else:
                    args.input_device = default_in
        except Exception as e:
            print(f"[mic-asr] Device query failed (will use default): {e}")

    print("[mic-asr] Starting microphone capture. Ctrl+C to stop.")
    if args.input_device:
        print(f"[mic-asr] Using input device: {args.input_device}")
    try:
        # normalize device: if it's a digit-like string, cast to int
        dev = None
        if args.input_device is not None:
            try:
                dev = int(args.input_device) if isinstance(args.input_device, str) else args.input_device
            except Exception:
                dev = args.input_device
        with sd.InputStream(channels=1, samplerate=args.rate, dtype='float32', device=dev, blocksize=frame_len) as stream:
            while True:
                frame = stream.read(frame_len)[0].reshape(-1)
                if start_time_segment is None:
                    start_time_segment = time.time()
                    last_force_flush_time = start_time_segment
                audio_buffer.append(frame)
                frame_times.append(time.time())
                raw_bytes = pcm16_to_bytes(frame)
                is_speech = vad.is_speech(raw_bytes, args.rate)
                if args.vumeter:
                    # simple RMS-based meter
                    rms = float(np.sqrt(np.mean(frame * frame)))
                    bar = "#" * max(1, int(rms * 40))
                    state = "S" if is_speech else "."
                    print(f"[{state}] {bar}")
                now = time.time()
                if is_speech:
                    last_voice_time = now
                # Endpoint conditions:
                #  1) Enough trailing silence after last voice
                #  2) Segment too long (force flush)
                silence_ok = False
                if last_voice_time is not None:
                    # Count frames since last speech
                    trailing_frames = 0
                    for t in reversed(frame_times):
                        if t >= last_voice_time:
                            trailing_frames += 1
                        else:
                            break
                    silence_ok = trailing_frames >= silence_frames_required
                too_long = (now - start_time_segment) >= args.max_segment_sec
                if silence_ok or too_long:
                    finalize_segment()
                    continue
                # Force flush path (no silence for a long time)
                if args.force_flush_sec and last_force_flush_time is not None:
                    if (now - last_force_flush_time) >= args.force_flush_sec:
                        finalize_segment()
    except KeyboardInterrupt:
        print("\n[mic-asr] Stopping...")
    except Exception as e:
        print(f"[mic-asr] Error during capture: {e}")
    # Flush remaining partial
    finalize_segment()
    # Final summary
    final_text = "".join(segments_text)
    if args.json:
        print(json.dumps({"type": "final", "text": final_text}, ensure_ascii=False))
    else:
        print(f"[mic-asr][final] {final_text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
