#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对比 Faster-Whisper 不同模型的性能和准确度"""

import time
from pathlib import Path
from faster_whisper import WhisperModel

def test_model(model_size, audio_file, device="cpu", compute_type="int8"):
    """测试单个模型"""
    print(f"\n{'='*70}")
    print(f"Testing model: {model_size}")
    print(f"{'='*70}")
    
    # 1. 加载模型
    print(f"Loading model...")
    load_start = time.time()
    model = WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type,
        download_root=str(Path.home() / ".cache" / "whisper")
    )
    load_time = time.time() - load_start
    print(f"✓ Model loaded in {load_time:.2f}s")
    
    # 2. 预热测试 - 首字输出时间 (Time To First Token - TTFT)
    print(f"\nWarmup test (measuring Time To First Token)...")
    warmup_start = time.time()
    
    segments_iter, info = model.transcribe(
        str(audio_file),
        language="en",
        beam_size=5,
        vad_filter=True
    )
    
    # 获取第一个 segment
    first_segment = None
    first_token_time = None
    for segment in segments_iter:
        first_segment = segment
        first_token_time = time.time() - warmup_start
        print(f"✓ First token output time (TTFT): {first_token_time:.3f}s")
        print(f"  First segment: [{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text.strip()}")
        break  # 只获取第一个 segment
    
    # 3. 完整转录测试 (重新加载以获得完整结果)
    print(f"\nFull transcription test...")
    transcribe_start = time.time()
    
    segments, info = model.transcribe(
        str(audio_file),
        language="en",
        beam_size=5,
        vad_filter=True
    )
    
    # 收集所有结果
    results = []
    for segment in segments:
        results.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text.strip()
        })
    
    transcribe_time = time.time() - transcribe_start
    
    # 4. 统计信息
    total_text = " ".join([r["text"] for r in results])
    word_count = len(total_text.split())
    char_count = len(total_text)
    
    print(f"\n{'='*70}")
    print(f"Summary for {model_size}:")
    print(f"{'='*70}")
    print(f"  Model load time:       {load_time:.2f}s")
    print(f"  First token time (TTFT): {first_token_time:.3f}s")
    print(f"  Full transcription:    {transcribe_time:.2f}s")
    print(f"  Audio duration:        {info.duration:.2f}s")
    print(f"  Real-time factor:      {transcribe_time / info.duration:.3f}x")
    print(f"  Language detected:     {info.language} ({info.language_probability:.2%})")
    print(f"  Total segments:        {len(results)}")
    print(f"  Total words:           {word_count}")
    print(f"  Total characters:      {char_count}")
    print(f"{'='*70}")
    
    # 前5个 segments 用于准确度对比
    print(f"\nFirst 5 segments (for accuracy comparison):")
    for i, seg in enumerate(results[:5], 1):
        print(f"{i}. [{seg['start']:.2f}s -> {seg['end']:.2f}s]")
        print(f"   {seg['text']}")
    
    return {
        "model": model_size,
        "load_time": load_time,
        "ttft": first_token_time,
        "transcribe_time": transcribe_time,
        "audio_duration": info.duration,
        "rtf": transcribe_time / info.duration,
        "language": info.language,
        "language_prob": info.language_probability,
        "segments_count": len(results),
        "word_count": word_count,
        "char_count": char_count,
        "first_5_segments": results[:5],
        "full_text": total_text[:500]  # 前500字符
    }

def main():
    audio_file = Path(__file__).parent / "ASRtest.wav"
    
    print("Faster-Whisper Model Comparison")
    print("="*70)
    print(f"Audio file: {audio_file}")
    print(f"Device: CPU")
    print(f"Compute type: int8")
    
    # 测试两个模型
    models = ["small", "turbo"]
    results = {}
    
    for model_size in models:
        try:
            results[model_size] = test_model(model_size, audio_file)
        except Exception as e:
            print(f"\n✗ Error testing {model_size}: {e}")
            import traceback
            traceback.print_exc()
    
    # 对比结果
    if len(results) == 2:
        print(f"\n\n{'='*70}")
        print("COMPARISON SUMMARY")
        print(f"{'='*70}")
        
        small = results["small"]
        turbo = results["turbo"]
        
        print(f"\nMetric                    Small         Turbo         Winner")
        print(f"{'-'*70}")
        print(f"Load time:                {small['load_time']:.2f}s        {turbo['load_time']:.2f}s        {'Small' if small['load_time'] < turbo['load_time'] else 'Turbo'}")
        print(f"First token time (TTFT):  {small['ttft']:.3f}s      {turbo['ttft']:.3f}s      {'Small' if small['ttft'] < turbo['ttft'] else 'Turbo'}")
        print(f"Full transcription:       {small['transcribe_time']:.2f}s       {turbo['transcribe_time']:.2f}s       {'Small' if small['transcribe_time'] < turbo['transcribe_time'] else 'Turbo'}")
        print(f"Real-time factor:         {small['rtf']:.3f}x      {turbo['rtf']:.3f}x      {'Small' if small['rtf'] < turbo['rtf'] else 'Turbo'}")
        print(f"Segments count:           {small['segments_count']}         {turbo['segments_count']}         {'Equal' if small['segments_count'] == turbo['segments_count'] else 'Different'}")
        print(f"Word count:               {small['word_count']}        {turbo['word_count']}        {'Equal' if small['word_count'] == turbo['word_count'] else 'Different'}")
        
        print(f"\n{'='*70}")
        print("Accuracy Comparison (First 5 segments):")
        print(f"{'='*70}")
        
        for i in range(min(5, len(small['first_5_segments']), len(turbo['first_5_segments']))):
            print(f"\nSegment {i+1}:")
            print(f"  Small: {small['first_5_segments'][i]['text']}")
            print(f"  Turbo: {turbo['first_5_segments'][i]['text']}")
            if small['first_5_segments'][i]['text'] == turbo['first_5_segments'][i]['text']:
                print(f"  ✓ Identical")
            else:
                print(f"  ✗ Different")

if __name__ == "__main__":
    main()
