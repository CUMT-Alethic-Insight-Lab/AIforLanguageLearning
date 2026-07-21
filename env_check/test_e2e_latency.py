import os
import sys
import time
import torch
import numpy as np
import soundfile as sf
from pathlib import Path
import difflib

# Add env_check to path to import run_xtts_stream_multilang
sys.path.append(str(Path(__file__).parent))

# Import XTTS wrapper (this also applies the torchaudio patch)
try:
    from run_xtts_stream_multilang import XTTSStreamingTTS
except ImportError:
    # If running from root, adjust path
    sys.path.append(str(Path("env_check").absolute()))
    from run_xtts_stream_multilang import XTTSStreamingTTS

from faster_whisper import WhisperModel

def calculate_cer(reference, hypothesis):
    """Calculate Character Error Rate"""
    ref = list(reference)
    hyp = list(hypothesis)
    matcher = difflib.SequenceMatcher(None, ref, hyp)
    return 1.0 - matcher.ratio()

def run_test(xtts, asr, text, lang, prompt_wav):
    print(f"\n[TEST] Testing Language: {lang}")
    print(f"[TEST] Input Text: {text}")
    
    # 1. XTTS Generation (Sentence Streaming)
    print("[TEST] Starting XTTS...")
    start_time = time.time()
    
    # We use the internal split_sentences to simulate what happens inside
    sentences = xtts.split_sentences(text, lang)
    first_sentence = sentences[0]
    
    # Generate first sentence audio
    # We use tts_to_file as in the original script, but to a temp file
    temp_wav = Path("temp_e2e.wav")
    
    tts_start = time.time()
    xtts.tts.tts_to_file(
        text=first_sentence,
        speaker_wav=prompt_wav,
        language=lang,
        file_path=str(temp_wav),
        temperature=0.7,
        length_penalty=1.0,
        repetition_penalty=2.0,
        top_k=50,
        top_p=0.8,
    )
    tts_end = time.time()
    tts_latency = tts_end - tts_start
    print(f"[TEST] XTTS First Sentence Latency: {tts_latency:.4f}s")
    
    # 2. ASR Recognition
    print("[TEST] Starting ASR...")
    asr_start = time.time()
    segments, info = asr.transcribe(str(temp_wav), beam_size=5, language=lang if lang != 'auto' else None)
    
    recognized_text = ""
    for segment in segments:
        recognized_text += segment.text
    
    asr_end = time.time()
    asr_latency = asr_end - asr_start
    print(f"[TEST] ASR Latency: {asr_latency:.4f}s")
    
    total_e2e = (asr_end - start_time)
    print(f"[TEST] Total E2E Latency (First Sentence): {total_e2e:.4f}s")
    print(f"[TEST] Recognized Text: {recognized_text}")
    
    # 3. Accuracy
    cer = calculate_cer(first_sentence, recognized_text.strip())
    print(f"[TEST] Accuracy (1-CER): {1.0-cer:.2%}")
    
    # Cleanup
    if temp_wav.exists():
        temp_wav.unlink()

def main():
    # Configuration
    default_prompt_wav = str(
        Path(__file__).resolve().parent.parent / "testresources" / "TTSpromptAudio.wav"
    )
    prompt_wav = os.environ.get("XTTS_PROMPT_WAV", default_prompt_wav)
    if not os.path.exists(prompt_wav):
        print(f"Error: Prompt wav not found at {prompt_wav}")
        return

    print("================================================================")
    print("Initializing Models (Warmup Phase)")
    print("================================================================")
    
    # Initialize XTTS
    xtts = XTTSStreamingTTS()
    
    # Initialize Whisper
    # User requested smaller model (large is unnecessary)
    model_size = "medium" 
    print(f"[ASR] Loading Faster Whisper ({model_size})...")
    asr = WhisperModel(model_size, device="cuda", compute_type="float16")
    print("[ASR] Loaded.")
    
    # Warmup
    print("\n[WARMUP] Running warmup cycle...")
    try:
        run_test(xtts, asr, "Warmup test.", "en", prompt_wav)
    except Exception as e:
        print(f"[WARMUP] Error: {e}")
    
    print("\n================================================================")
    print("Starting E2E Latency & Accuracy Tests")
    print("================================================================")
    
    # Test Cases
    tests = [
        ("zh", "你好，这是一个端到端延迟测试。我们将测试从文本生成语音，再识别回文本的速度。"),
        ("en", "This is an end-to-end latency test. We are measuring the time from text to speech and back to text."),
        ("ja", "これはエンドツーエンドの遅延テストです。テキストから音声、そしてテキストに戻る時間を測定します。")
    ]
    
    for lang, text in tests:
        try:
            run_test(xtts, asr, text, lang, prompt_wav)
        except Exception as e:
            print(f"[TEST] Failed for {lang}: {e}")

if __name__ == "__main__":
    main()
