import os
import sys
from pathlib import Path

AUDIO = os.getenv("FASTWHISPER_AUDIO", str(Path(__file__).with_name("zero_shot_prompt.wav")))
MODEL_DIR = os.getenv("FASTWHISPER_MODEL_DIR")  # e.g., local path to faster-whisper model directory
MODEL_SIZE = os.getenv("FASTWHISPER_MODEL_SIZE", "small")  # 'tiny'|'base'|'small'|'medium'|'large-v3' etc.

try:
    from faster_whisper import WhisperModel  # type: ignore
except Exception:
    print("[faster_whisper_probe] faster-whisper not installed.")
    print("Hint: conda run -p <env> python -m pip install faster-whisper")
    print("For offline use, set FASTWHISPER_MODEL_DIR to a local model path.")
    sys.exit(2)


def main():
    wav = Path(AUDIO)
    if not wav.exists():
        print(f"[faster_whisper_probe] Audio not found: {wav}")
        return 1

    if MODEL_DIR and Path(MODEL_DIR).exists():
        model_ref = MODEL_DIR
        print(f"[faster_whisper_probe] Using local model dir: {MODEL_DIR}")
    else:
        model_ref = MODEL_SIZE
        print(f"[faster_whisper_probe] Using model size: {MODEL_SIZE} (may download if not cached)")

    try:
        model = WhisperModel(model_ref, device="cuda" if os.getenv("CUDA_VISIBLE_DEVICES", None) != "-1" else "cpu")
        segments, info = model.transcribe(str(wav), vad_filter=True)
        print(f"[faster_whisper_probe] Detected language: {info.language}, prob={info.language_probability:.2f}")
        text = "".join(s.text for s in segments)
        print(f"[faster_whisper_probe] Transcription: {text}")
        return 0
    except Exception as e:
        print(f"[faster_whisper_probe] Transcribe failed: {e}")
        return 3

if __name__ == "__main__":
    sys.exit(main())
