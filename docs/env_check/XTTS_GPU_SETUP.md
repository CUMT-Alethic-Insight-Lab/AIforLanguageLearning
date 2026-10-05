# XTTS GPU Setup & Deployment Notes

## Environment Status
- **GPU**: NVIDIA RTX 5080 (sm_120)
- **CUDA**: 13.0
- **Python**: 3.11.14 (Conda: `torchnb311`)
- **PyTorch**: 2.10.0.dev20251118+cu130 (Nightly)
- **Torchaudio**: 2.10.0a0+ee1a135 (Custom Build)
  - Built from source to match PyTorch nightly.
  - CUDA enabled.
  - Forced Alignment disabled (due to API conflict).
  - Installed in `site-packages`.

## XTTS Streaming Script
- **Script**: `env_check/run_xtts_stream_multilang.py`
- **Features**:
  - Full GPU pipeline (Model load & Inference).
  - Multi-language support (ZH, EN, JA).
  - Streaming output (low latency).
  - Zero-shot cloning (via prompt audio).

## Critical Patches
1. **Torchaudio Load Patch**:
   - PyTorch/Torchaudio 2.10 nightly defaults to `torchcodec` for audio loading, which is not yet available for this environment.
   - The script patches `torchaudio.load` to use `soundfile` instead.
   - **Do not remove this patch** unless `torchcodec` is installed.

2. **Japanese Support**:
   - Installed `cutlet`, `mecab-python3`, `unidic-lite`.

## Performance (RTX 5080)
- **Real-Time Factor (RTF)**: ~0.3 - 0.6 (Faster than real-time)
- **Latency**: First chunk < 1.5s (including model processing).

## Usage
```powershell
$env:XTTS_TEXT_ZH="你好，世界"
$env:XTTS_PROMPT_WAV="path/to/prompt.wav"
$env:XTTS_OUT_DIR="output/dir"
python env_check/run_xtts_stream_multilang.py
```
