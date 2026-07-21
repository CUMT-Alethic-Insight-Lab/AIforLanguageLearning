#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Activate venv if exists (use ~ to avoid polluted HOME from Windows)
if [ -f ~/.venvs/ptsrc/bin/activate ]; then
  # shellcheck disable=SC1090
  source ~/.venvs/ptsrc/bin/activate
fi
python -m env_check.run_cosyvoice2_trt_ab \
  --cmd "python -m env_check.run_cosyvoice2_zero_shot --text '你好世界' --prompt_wav env_check/zero_shot_prompt.wav --use_flow_cache 1 --use_fp16 0" \
  --trt-env COSY_LOAD_TRT \
  --timeout 300 \
  --env COSY_WARMUP=0 \
  --env COSY_ORT_IOBIND=0 \
  --env COSY_ORT_SPEECH_CPU=1 \
  --env COSY_ORT_NO_TRT=0 \
  --env COSY_DISABLE_CUDNN=1 \
  --env HF_HUB_DISABLE_TELEMETRY=1 \
  --env HF_HUB_OFFLINE=1
