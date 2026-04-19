from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor


def main() -> int:
    wav = Path(__file__).resolve().parents[2] / "testresources" / "ASRtest.wav"
    print("wav:", wav)
    print("exists:", wav.exists())

    model_id = "facebook/hf-seamless-m4t-medium"

    start = time.time()
    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForSpeechSeq2Seq.from_pretrained(
        model_id,
        dtype=torch.float32,
    )
    model.eval()
    print("model loaded in", round(time.time() - start, 2), "s")

    # 加载音频
    try:
        import soundfile as sf
        audio, sr = sf.read(str(wav), dtype="float32")
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        if sr != 16000:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
    except Exception as e:
        print(f"Error loading audio: {e}")
        return 1

    start = time.time()
    inputs = processor(audios=audio, sampling_rate=16000, return_tensors="pt")
    with torch.no_grad():
        output_tokens = model.generate(
            **inputs,
            tgt_lang="eng",
            generate_speech=False,
        )
    text = processor.decode(output_tokens[0].tolist(), skip_special_tokens=True)

    print("transcribe in", round(time.time() - start, 2), "s")
    print("TEXT:")
    print(text.strip())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
