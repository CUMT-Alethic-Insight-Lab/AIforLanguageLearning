import sys
import os
import json
import struct
import collections
import queue
import time
import numpy as np
import webrtcvad
from faster_whisper import WhisperModel

# Configuration
SAMPLE_RATE = 16000
FRAME_DURATION_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
VAD_MODE = 3  # 0-3, 3 is most aggressive
SILENCE_THRESHOLD_MS = 500  # ms of silence to trigger transcription
MIN_SPEECH_MS = 200 # Minimum speech duration to consider

def main():
    # Initialize VAD
    vad = webrtcvad.Vad(VAD_MODE)

    # Initialize Whisper
    model_size = os.environ.get("ASR_MODEL_SIZE", "medium")
    device = os.environ.get("ASR_DEVICE", "cuda")
    compute_type = os.environ.get("ASR_COMPUTE_TYPE", "float16")
    
    sys.stderr.write(f"[ASR] Loading Whisper {model_size} on {device} ({compute_type})...\n")
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as e:
        sys.stderr.write(f"[ASR] Failed to load on {device}: {e}\n")
        if device == "cuda":
            sys.stderr.write("[ASR] Falling back to CPU (int8)...\n")
            device = "cpu"
            compute_type = "int8"
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
        else:
            raise e

    sys.stderr.write(f"[ASR] Model loaded on {device}. Ready for audio (16kHz s16le) via stdin.\n")

    # Buffers
    raw_buffer = b""
    speech_buffer = []
    silence_frames = 0
    is_speaking = False
    
    # Frame size in bytes (16-bit = 2 bytes per sample)
    FRAME_BYTES = FRAME_SIZE * 2
    
    # Thresholds in frames
    SILENCE_FRAMES_THRESH = int(SILENCE_THRESHOLD_MS / FRAME_DURATION_MS)
    
    # Standard Input Stream
    stdin_stream = sys.stdin.buffer

    while True:
        chunk = stdin_stream.read(FRAME_BYTES)
        if not chunk:
            break
            
        if len(chunk) < FRAME_BYTES:
            continue

        # VAD Check
        try:
            is_speech = vad.is_speech(chunk, SAMPLE_RATE)
        except Exception:
            is_speech = False

        if is_speech:
            if not is_speaking:
                is_speaking = True
                # Send event: Speech Started
                print(json.dumps({"type": "vad_start"}))
                sys.stdout.flush()
            
            speech_buffer.append(chunk)
            silence_frames = 0
        else:
            if is_speaking:
                speech_buffer.append(chunk)
                silence_frames += 1
                
                if silence_frames >= SILENCE_FRAMES_THRESH:
                    # End of speech detected
                    is_speaking = False
                    print(json.dumps({"type": "vad_end"}))
                    sys.stdout.flush()
                    
                    # Transcribe
                    full_audio = b"".join(speech_buffer)
                    # Remove trailing silence frames
                    full_audio = full_audio[:-(silence_frames * FRAME_BYTES)]
                    
                    if len(full_audio) > (MIN_SPEECH_MS * SAMPLE_RATE * 2 / 1000):
                        transcribe(model, full_audio)
                    
                    speech_buffer = []
                    silence_frames = 0

def transcribe(model, audio_bytes):
    # Convert raw bytes to float32 numpy array
    audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
    audio_float32 = audio_int16.astype(np.float32) / 32768.0
    
    segments, info = model.transcribe(audio_float32, beam_size=5, language=None) # Auto detect language
    
    text = ""
    lang = info.language
    
    for segment in segments:
        text += segment.text
    
    text = text.strip()
    if text:
        output = {
            "type": "transcription",
            "text": text,
            "language": lang,
            "prob": info.language_probability
        }
        print(json.dumps(output))
        sys.stdout.flush()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
