#!/usr/bin/env python3
"""
Full-GPU attempt driver for CosyVoice2 (Plan C)

What it does:
- Runs a sequence of increasingly conservative GPU profiles to maximize GPU coverage first.
- Each attempt sets environment knobs (TRT/ORT CUDA/cuDNN/FP16/cache-shape) and runs the zero-shot streaming script.
- Enforces a per-attempt timeout and captures TTFT from stdout.
- Produces a compact CSV summary and keeps tail logs for failures.

Fallback rule:
- If all "aggressive" profiles fail after N attempts, user can switch to Plan B (A/B on current stable settings) easily.

Usage examples:
  python -m env_check.run_full_gpu_attempt \
    --text "你好世界" \
    --prompt_wav env_check/zero_shot_prompt.wav \
    --timeout 180 \
    --profiles full,no_cudnn,trt_only,ort_only

Probe-only (no TTS run, just environment probes):
  python -m env_check.run_full_gpu_attempt --probe-only

Notes:
- This driver shells out to env_check/run_cosyvoice2_zero_shot.py to keep the tested path identical to normal usage.
- Environment toggles used:
    COSY_FORCE_CPU=0                # never force CPU
    COSY_ORT_SPEECH_CPU=0/1         # speech tokenizer device (0=GPU if ORT CUDA works)
    COSY_DISABLE_CUDNN=0/1          # cuDNN on/off
    COSY_LOAD_TRT=0/1               # TensorRT on/off
    COSY_TRT_SKIP_CACHE_SHAPES=0/1  # temporary guard to avoid invalid tensor name spam
    COSY_WARMUP=1                   # do one small warmup by default
    COSY_TOKEN_HOP=8                # lower TTFT
- Adjust profiles below as needed.
"""
from __future__ import annotations
import argparse
import os
import shlex
import subprocess
import sys
import time
import re
from typing import Dict, List, Optional, Tuple
from importlib.util import find_spec

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
ZERO_SHOT = os.path.join(HERE, "run_cosyvoice2_zero_shot.py")
TTFT_RE = re.compile(r"TTFT\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*s", re.IGNORECASE)


def run_once(label: str, cmd: List[str], env: Dict[str, str], timeout_s: Optional[float]) -> Tuple[int, float, Optional[float], str]:
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    lines: List[str] = []
    ttft: Optional[float] = None
    try:
        assert proc.stdout is not None
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            sys.stdout.write(f"[{label}] "+line)
            lines.append(line.rstrip())
            m = TTFT_RE.search(line)
            if m:
                try:
                    ttft = float(m.group(1))
                except Exception:
                    pass
            if timeout_s is not None and (time.perf_counter()-t0) > timeout_s:
                try:
                    proc.terminate()
                except Exception:
                    pass
                break
    finally:
        try:
            rc = proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            rc = -9
    wall = time.perf_counter()-t0
    tail = "\n".join(lines[-32:])
    return rc, wall, ttft, tail


def build_zero_shot_cmd(text: str, prompt_wav: str, speed: float, use_fp16: int, use_flow_cache: int) -> List[str]:
    base = [sys.executable, ZERO_SHOT,
            "--text", text,
            "--prompt_wav", prompt_wav,
            "--speed", str(speed),
            "--use_fp16", str(use_fp16),
            "--use_flow_cache", str(use_flow_cache)]
    return base


def probe_env() -> None:
    """Run quick probes (torch env + ORT providers). Safe if deps are installed; otherwise prints import errors."""
    print("\n== Torch env probe ==")
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "check_torch_env.py")], check=False)
    except Exception as e:
        print("[probe] torch env failed:", e)
    print("\n== ORT GPU providers probe ==")
    try:
        env = os.environ.copy()
        env.setdefault("ORT_TRY_CUDA", "1")
        subprocess.run([sys.executable, os.path.join(HERE, "ort_gpu_probe.py")], check=False, env=env)
    except Exception as e:
        print("[probe] ort probe failed:", e)


def profile_env(profile: str) -> Dict[str, str]:
    """Return environment overrides for a named profile."""
    common = {
        "COSY_FORCE_CPU": "0",
        "COSY_WARMUP": os.getenv("COSY_WARMUP", "1"),
        "COSY_TOKEN_HOP": os.getenv("COSY_TOKEN_HOP", "8"),
    }
    if profile == "full":
        # Most aggressive: TRT + ORT CUDA + cuDNN, keep cache-shape skip ON for now to avoid name spam
        return {
            **common,
            "COSY_ORT_SPEECH_CPU": "0",
            "COSY_DISABLE_CUDNN": "0",
            "COSY_LOAD_TRT": "1",
            # Rebuild TRT engine to match installed TensorRT when plan is incompatible
            "COSY_REBUILD_TRT": os.getenv("COSY_REBUILD_TRT", "1"),
            "COSY_TRT_SKIP_CACHE_SHAPES": os.getenv("COSY_TRT_SKIP_CACHE_SHAPES", "1"),
        }
    if profile == "no_cudnn":
        # Aggressive but disable cuDNN (observed unstable on new arch), keep TRT and ORT CUDA
        return {
            **common,
            "COSY_ORT_SPEECH_CPU": "0",
            "COSY_DISABLE_CUDNN": "1",
            "COSY_LOAD_TRT": "1",
            "COSY_REBUILD_TRT": os.getenv("COSY_REBUILD_TRT", "1"),
            "COSY_TRT_SKIP_CACHE_SHAPES": os.getenv("COSY_TRT_SKIP_CACHE_SHAPES", "1"),
        }
    if profile == "trt_only":
        # Isolate TRT path, keep ORT front-end on CPU to avoid ORT CUDA issues
        return {
            **common,
            "COSY_ORT_SPEECH_CPU": "1",
            # Force Torch to CPU to avoid unsupported CUDA kernels on sm_120 while still allowing TRT
            "COSY_TORCH_FORCE_CPU": os.getenv("COSY_TORCH_FORCE_CPU", "1"),
            "COSY_DISABLE_CUDNN": os.getenv("COSY_DISABLE_CUDNN", "1"),
            "COSY_LOAD_TRT": "1",
            "COSY_REBUILD_TRT": os.getenv("COSY_REBUILD_TRT", "1"),
            "COSY_TRT_SKIP_CACHE_SHAPES": os.getenv("COSY_TRT_SKIP_CACHE_SHAPES", "1"),
        }
    if profile == "ort_only":
        # No TRT, test ORT CUDA front-end and PyTorch CUDA for the rest
        return {
            **common,
            "COSY_ORT_SPEECH_CPU": "0",
            # Force Torch to CPU to avoid unsupported CUDA kernels on sm_120 while keeping ORT CUDA
            "COSY_TORCH_FORCE_CPU": os.getenv("COSY_TORCH_FORCE_CPU", "1"),
            "COSY_DISABLE_CUDNN": os.getenv("COSY_DISABLE_CUDNN", "1"),
            "COSY_LOAD_TRT": "0",
            "COSY_TRT_SKIP_CACHE_SHAPES": os.getenv("COSY_TRT_SKIP_CACHE_SHAPES", "1"),
        }
    # default: conservative baseline (should already work)
    return {
        **common,
        "COSY_ORT_SPEECH_CPU": os.getenv("COSY_ORT_SPEECH_CPU", "1"),
        "COSY_DISABLE_CUDNN": os.getenv("COSY_DISABLE_CUDNN", "1"),
        "COSY_LOAD_TRT": os.getenv("COSY_LOAD_TRT", "1"),
        "COSY_TRT_SKIP_CACHE_SHAPES": os.getenv("COSY_TRT_SKIP_CACHE_SHAPES", "1"),
    }


def main():
    ap = argparse.ArgumentParser(description="Full-GPU attempt runner (Plan C)")
    ap.add_argument("--text", default="收到好友从远方寄来的生日礼物，那份意外的惊喜与深深的祝福让我心中充满了甜蜜的快乐，笑容如花儿般绽放。")
    ap.add_argument("--prompt_wav", default=os.path.join(HERE, "zero_shot_prompt.wav"))
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--use_fp16", type=int, default=1)
    ap.add_argument("--use_flow_cache", type=int, default=1)
    ap.add_argument("--profiles", default="full,no_cudnn,trt_only,ort_only", help="Comma-separated profiles to try in order")
    ap.add_argument("--csv", default=os.path.join(ROOT, "trt_ab_results.csv"))
    ap.add_argument("--probe-only", action="store_true", help="Only run environment probes; skip TTS")
    args = ap.parse_args()

    if args.probe_only:
        probe_env()
        return

    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]

    rows: List[str] = ["label,returncode,wall_time_s,ttft_s"]
    last_tail = {}

    for p in profiles:
        print(f"\n=== Attempt: {p} ===")
        env = os.environ.copy()
        env.update(profile_env(p))
        # ensure CUDA is visible unless user overrode
        env.setdefault("CUDA_VISIBLE_DEVICES", os.getenv("CUDA_VISIBLE_DEVICES", "0"))
        # Fast-skip TRT profiles if TensorRT is not installed
        wants_trt = env.get("COSY_LOAD_TRT", "0") in ("1", "true", "True")
        if wants_trt and find_spec("tensorrt") is None:
            print(f"[{p}] TensorRT (tensorrt) not installed; skipping this profile.")
            rows.append(f"{p},-2,0.000,")
            last_tail[p] = "TensorRT not installed; skipped."
            continue
        # Disable fp16 automatically when Torch is forced to CPU to avoid dtype mismatches
        use_fp16 = args.use_fp16
        if env.get("COSY_TORCH_FORCE_CPU", "0") in ("1", "true", "True"):
            use_fp16 = 0
        cmd = build_zero_shot_cmd(args.text, args.prompt_wav, args.speed, use_fp16, args.use_flow_cache)
        rc, wall, ttft, tail = run_once(p, cmd, env, timeout_s=args.timeout)
        rows.append(f"{p},{rc},{wall:.3f},{'' if ttft is None else f'{ttft:.3f}'}")
        last_tail[p] = tail
        # early exit on success
        if rc == 0 and ttft is not None:
            print("\n[success] early stop on profile:", p)
            break

    # write CSV
    os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
    with open(args.csv, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    print("CSV saved to:", args.csv)

    # print tails for failed profiles
    for p in profiles:
        tail = last_tail.get(p)
        if tail and any(r.startswith(p+",") and r.split(",")[1] != "0" for r in rows[1:]):
            print(f"\n[{p}] tail:\n" + tail)

    # exit code: use the last run's code
    try:
        last_rc = int(rows[-1].split(",")[1]) if len(rows) > 1 else 0
    except Exception:
        last_rc = 0
    sys.exit(last_rc)


if __name__ == "__main__":
    main()
