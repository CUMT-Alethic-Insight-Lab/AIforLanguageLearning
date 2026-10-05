#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 Faster-Whisper ASR (CPU优化版本)"""

import time
from pathlib import Path
from faster_whisper import WhisperModel

def main():
    # 配置
    audio_file = Path(__file__).parent / "ASRtest.wav"
    output_dir = Path(__file__).parent.parent / "backend" / "temp"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 模型配置: small 或 medium, 使用 CPU + int8 量化
    model_size = "small"  # 可选: tiny, base, small, medium, large-v2, large-v3
    device = "cpu"
    compute_type = "int8"  # CPU 上使用 int8 量化以提升速度
    
    print(f"Loading Faster-Whisper model: {model_size}")
    print(f"Device: {device}, Compute type: {compute_type}")
    
    start_time = time.time()
    
    # 加载模型
    model = WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type,
        download_root=str(Path.home() / ".cache" / "whisper")
    )
    
    load_time = time.time() - start_time
    print(f"✓ Model loaded in {load_time:.2f}s")
    
    # 转录
    print(f"\nTranscribing: {audio_file}")
    transcribe_start = time.time()
    
    segments, info = model.transcribe(
        str(audio_file),
        language="en",  # 或 None 自动检测
        beam_size=5,
        vad_filter=True,  # 使用 VAD 过滤静音
        vad_parameters=dict(min_silence_duration_ms=500)
    )
    
    # 收集结果
    results = []
    for segment in segments:
        results.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text.strip()
        })
        print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
    
    transcribe_time = time.time() - transcribe_start
    total_time = time.time() - start_time
    
    # 保存结果
    output_file = output_dir / f"faster_whisper_{model_size}_result.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"Faster-Whisper Transcription Results\n")
        f.write(f"Model: {model_size}\n")
        f.write(f"Device: {device}, Compute type: {compute_type}\n")
        f.write(f"Language: {info.language} (probability: {info.language_probability:.2f})\n")
        f.write(f"Duration: {info.duration:.2f}s\n")
        f.write(f"Load time: {load_time:.2f}s\n")
        f.write(f"Transcription time: {transcribe_time:.2f}s\n")
        f.write(f"Real-time factor: {transcribe_time / info.duration:.2f}x\n")
        f.write(f"\n{'='*60}\n\n")
        
        for i, seg in enumerate(results, 1):
            f.write(f"{i}. [{seg['start']:.2f}s -> {seg['end']:.2f}s]\n")
            f.write(f"   {seg['text']}\n\n")
    
    print(f"\n{'='*60}")
    print(f"✓ Transcription completed!")
    print(f"  Detected language: {info.language} ({info.language_probability:.2%})")
    print(f"  Audio duration: {info.duration:.2f}s")
    print(f"  Load time: {load_time:.2f}s")
    print(f"  Transcription time: {transcribe_time:.2f}s")
    print(f"  Real-time factor: {transcribe_time / info.duration:.2f}x")
    print(f"  Total segments: {len(results)}")
    print(f"  Output saved to: {output_file}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
