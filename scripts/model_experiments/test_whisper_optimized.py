#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""优化的 Faster-Whisper ASR - 针对 AMD Ryzen 9950X3D CPU 亲和性和多线程"""

import os
import time
from pathlib import Path
from faster_whisper import WhisperModel

# ===== CPU 优化配置 =====
# 设置进程亲和性到 CCD0 (核心 0-15, 即前16个逻辑核心)
# 9950X3D 的 CCD0 有 3D V-Cache, 性能更强
try:
    import psutil
    current_process = psutil.Process()
    # 设置 CPU 亲和性到前 16 个核心 (CCD0)
    # 对于 9950X3D: 核心 0-7 是物理核心, 8-15 是对应的超线程
    ccd0_cores = list(range(16))  # 0-15
    current_process.cpu_affinity(ccd0_cores)
    print(f"✓ CPU affinity set to CCD0 cores: {ccd0_cores}")
except ImportError:
    print("⚠ psutil not installed, cannot set CPU affinity")
    print("  Install with: pip install psutil")
except Exception as e:
    print(f"⚠ Could not set CPU affinity: {e}")

# 设置 OpenMP 和其他多线程库使用更多线程
# CTranslate2 使用 OpenMP 进行并行计算
os.environ["OMP_NUM_THREADS"] = "16"  # 使用 16 个线程
os.environ["MKL_NUM_THREADS"] = "16"  # Intel MKL
os.environ["OPENBLAS_NUM_THREADS"] = "16"  # OpenBLAS
os.environ["VECLIB_MAXIMUM_THREADS"] = "16"  # macOS Accelerate
os.environ["NUMEXPR_NUM_THREADS"] = "16"  # NumExpr

# 设置 CPU 亲和性策略
os.environ["OMP_PROC_BIND"] = "close"  # 线程绑定到相近的核心
os.environ["OMP_PLACES"] = "cores"  # 每个线程绑定到一个核心
os.environ["KMP_AFFINITY"] = "granularity=fine,compact,1,0"  # Intel 线程亲和性

print(f"✓ Thread settings: OMP_NUM_THREADS=16, PROC_BIND=close, PLACES=cores")

def test_whisper_model(model_size: str, audio_file: Path, num_runs: int = 1):
    """测试 Whisper 模型性能"""
    print(f"\n{'='*70}")
    print(f"Testing {model_size.upper()} model")
    print(f"{'='*70}")
    
    device = "cpu"
    compute_type = "int8"  # CPU 上使用 int8 量化
    
    # 加载模型
    print(f"Loading model: {model_size}")
    load_start = time.time()
    
    model = WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type,
        cpu_threads=16,  # 显式设置使用 16 个线程
        num_workers=4,   # 增加工作线程数
        download_root=str(Path.home() / ".cache" / "whisper")
    )
    
    load_time = time.time() - load_start
    print(f"✓ Model loaded in {load_time:.2f}s")
    
    # 预热
    print("Warming up...")
    warmup_start = time.time()
    segments, info = model.transcribe(
        str(audio_file),
        language="en",
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500)
    )
    # 只获取第一个 segment 来预热
    first_segment = next(segments, None)
    warmup_time = time.time() - warmup_start
    
    if first_segment:
        print(f"✓ Warmup complete in {warmup_time:.2f}s")
        print(f"  First token time: {warmup_time:.2f}s")
        print(f"  First text: {first_segment.text[:100]}...")
    
    # 完整转录测试
    results = []
    for run in range(num_runs):
        print(f"\nRun {run + 1}/{num_runs}:")
        
        transcribe_start = time.time()
        first_token_time = None
        
        segments, info = model.transcribe(
            str(audio_file),
            language="en",
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        
        segment_list = []
        for i, segment in enumerate(segments):
            if i == 0 and first_token_time is None:
                first_token_time = time.time() - transcribe_start
            segment_list.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip()
            })
        
        transcribe_time = time.time() - transcribe_start
        
        results.append({
            "load_time": load_time if run == 0 else 0,
            "first_token_time": first_token_time,
            "transcribe_time": transcribe_time,
            "audio_duration": info.duration,
            "rtf": transcribe_time / info.duration,
            "segments": segment_list,
            "language": info.language,
            "language_prob": info.language_probability
        })
        
        print(f"  First token: {first_token_time:.2f}s")
        print(f"  Total time: {transcribe_time:.2f}s")
        print(f"  Audio duration: {info.duration:.2f}s")
        print(f"  RTF: {transcribe_time / info.duration:.3f}x")
        print(f"  Segments: {len(segment_list)}")
    
    return results

def main():
    # 检查 psutil 是否安装
    try:
        import psutil
        process = psutil.Process()
        print(f"\n✓ Current CPU affinity: {process.cpu_affinity()}")
    except ImportError:
        print("\n⚠ Install psutil for CPU affinity control:")
        print("  C:\\Users\\74090\\Miniconda3\\py313\\envs\\asr\\python.exe -m pip install psutil")
    
    audio_file = Path(__file__).parent / "ASRtest.wav"
    output_dir = Path(__file__).parent.parent / "backend" / "temp"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\nAudio file: {audio_file}")
    print(f"Output directory: {output_dir}")
    
    # 测试 small 模型
    small_results = test_whisper_model("small", audio_file, num_runs=1)
    
    # 保存结果
    output_file = output_dir / "whisper_cpu_optimized_results.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("Faster-Whisper CPU Optimization Results\n")
        f.write("="*70 + "\n")
        f.write(f"CPU: AMD Ryzen 9950X3D\n")
        f.write(f"Optimization: CCD0 (3D V-Cache), 16 threads\n")
        f.write(f"Settings: OMP_NUM_THREADS=16, PROC_BIND=close\n\n")
        
        result = small_results[0]
        f.write(f"Model: small (int8)\n")
        f.write(f"Load time: {result['load_time']:.2f}s\n")
        f.write(f"First token time: {result['first_token_time']:.2f}s\n")
        f.write(f"Total transcription time: {result['transcribe_time']:.2f}s\n")
        f.write(f"Audio duration: {result['audio_duration']:.2f}s\n")
        f.write(f"Real-time factor: {result['rtf']:.3f}x\n")
        f.write(f"Language: {result['language']} ({result['language_prob']:.2%})\n")
        f.write(f"Total segments: {len(result['segments'])}\n\n")
        
        f.write("First 5 segments:\n")
        for i, seg in enumerate(result['segments'][:5], 1):
            f.write(f"{i}. [{seg['start']:.2f}s - {seg['end']:.2f}s]\n")
            f.write(f"   {seg['text']}\n\n")
    
    print(f"\n{'='*70}")
    print(f"✓ Results saved to: {output_file}")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
