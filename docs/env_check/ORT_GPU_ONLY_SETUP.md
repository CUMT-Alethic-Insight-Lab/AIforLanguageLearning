# ORT / GPU-only Setup on WSL2 (Blackwell RTX 5080, CUDA 13)

Last updated: 2025-11-01

This note tracks a stable config for running CosyVoice2 zero-shot/streaming on WSL2 Ubuntu 22.04.5 with an RTX 5080 (SM 12.0), plus known issues and workarounds.

## TL;DR
- 2025-11-02 实测：在 CPU-only 配置下可稳定产出音频；示例 TTFT ≈ 21.5s（WSL2+CPU，供功能验证参考；性能不可比）。
- PyTorch was built from source for SM 12.0 (CUDA 13.0, cuDNN 9.14), but we hit recurrent `CUDA error: misaligned address` during CUDA ops (both plain tensor copies and convolutions), even with `fp32` and cuDNN disabled.
- ONNX Runtime 1.23.2 with CUDA/TensorRT EPs also throws `misaligned address` on Blackwell.
- Practical stable fallback today: keep ORT on CPU for campplus and speech tokenizer; let the main PyTorch model run on CPU as a temporary unblock for functional verification only. Skip any CPU RTF averaging since it’s meaningless in WSL2 (overheads skew >100x).

## Environment knobs that helped (and what they do)

- Disable TensorRT across the board:
  - `COSY_ORT_NO_TRT=1` (custom flag in frontend) — forces CUDA-only when TRT is requested.
  - Don’t set `COSY_ORT_CAMPPLUS_TRT=1` unless you truly want GPU EP (currently broken on Blackwell).
- Disable ORT IOBinding:
  - `COSY_ORT_IOBIND=0` — avoid raw pointer binds that may stress CUDA allocator paths.
- Force ORT CPU on fragile parts:
  - `COSY_ORT_SPEECH_CPU=1` — speech tokenizer ONNX on CPU.
  - Leave `COSY_ORT_CAMPPLUS_TRT` unset (default CPU) so campplus stays on CPU.
- Frontend tensors stay on CPU (patched):
  - We changed `cosyvoice/cli/frontend.py` to keep text tokens, speech tokens, speaker embedding, and prompt features on CPU. The model moves them to GPU if/when safe.
- Swap WeTextProcessing with your own TTF frontend:
  - `COSY_DISABLE_TTSFRD=1` 禁用 ttsfrd 优先级，便于替换前端。
  - `COSY_TEXT_NORMALIZER_MODULE=<your_module>` 指定自定义文本前端模块。
    - 支持两种接口：
      1) 类：`ZhNormalizer`、`EnNormalizer`，各自提供 `normalize(text:str)->str`
      2) 函数：`normalize_zh(text)`、`normalize_en(text)`；或统一 `normalize(text)`
    - 可用 `COSY_TEXT_NORMALIZER_ZH_CLASS`/`COSY_TEXT_NORMALIZER_EN_CLASS` 自定义类名。
- Avoid CPU performance “metrics”:
  - Do not compute average RTF on CPU in WSL2; RTF will be massively inflated by copy/interop layers. Only collect TTFT and end-to-end functional checks.

## Recommended run matrix

1) Functional-only (stable, CPU-heavy):

```powershell
wsl -e bash -lc "\
  source ~/.venvs/ptsrc/bin/activate; cd ./env_check; \
  COSY_FORCE_CPU=1 COSY_ORT_NO_TRT=1 COSY_ORT_CAMPPLUS_TRT=0 COSY_ORT_IOBIND=0 COSY_ORT_SPEECH_CPU=1 COSY_GPU_ONLY=0 \
  COSY_DISABLE_TTSFRD=1 COSY_TEXT_NORMALIZER_MODULE='your_ttf_module' \
  python run_cosyvoice2_zero_shot.py --text '你好，测试功能链路。' --prompt_wav zero_shot_prompt.wav --use_fp16 0 --use_flow_cache 0\
"
```

- Expect slow runtime but should validate model wiring, tokenizer, and file IO. Skip any CPU-RTF reporting.

2) GPU-first (currently broken on Blackwell):

```powershell
# Not recommended right now — causes CUDA misaligned errors
wsl -e bash -lc "\
  source ~/.venvs/ptsrc/bin/activate; cd ./env_check; \
  COSY_ORT_NO_TRT=1 COSY_ORT_CAMPPLUS_TRT=1 COSY_ORT_IOBIND=0 COSY_GPU_ONLY=1 \
  python run_cosyvoice2_zero_shot.py --text 'GPU 路径尝试。' --prompt_wav zero_shot_prompt.wav --use_fp16 1 --use_flow_cache 1\
"
```

- Fails with `CUDA error: misaligned address` either from PyTorch (cudnn convolution / allocator) or ORT CUDA EP data transfer.

## Results (2025-11-02)

- CPU-only 功能验证（启用 `COSY_FORCE_CPU=1`、前端 ORT 全 CPU、自定义 TTF 文本前端模块 `env_check/ttf_dummy_normalizer.py`）：
  - 控制台打印 TTFT（First audio delay）约 21.5s；
  - 生成分段 wav：`env_check/cosy2_zero_shot_*.wav`；
  - 日志显示已启用自定义前端：`[CosyVoice][TN] Using custom normalizers: ttf_dummy_normalizer.ZhNormalizer/EnNormalizer`。
- 尝试启用 GPU（主模型上 CUDA，前端保持 ORT CPU，禁用 TRTexec/IOBind）：
  - 仍在 flow cache 初始化阶段触发 `CUDA error: misaligned address`（Blackwell 栈问题，待上游修复/升级后再试）。

## Known issues

- Torch CUDA path on Blackwell (SM 12.0) shows `CUDA error: misaligned address` under:
  - simple `.to('cuda')` for small tensors (sometimes surfaced later),
  - `cudnn_convolution` callsites,
  - allocator free paths (`CUDACachingAllocator::uncached_delete`).
- ORT CUDA EP also fails with misaligned address on host<->device memcpy.
- Disabling cuDNN (`CUDNN_DISABLED=1`), turning off AMP (`--use_fp16 0`), disabling flow cache, and disabling torch CUDA caching (`PYTORCH_NO_CUDA_MEMORY_CACHING=1`) did not resolve it.

## Next steps (to unlock full GPU)

Ranked by likelihood to fix and effort:

1) Try newer pre-release stacks with Blackwell fixes:
   - PyTorch nightly built against CUDA >=13.1 and cuDNN >=9.2+ with SM 12.0 support.
   - NVIDIA NGC containers (nightly) that advertise RTX 50xx support.
2) Rebuild ONNX Runtime from source with:
   - CUDA 13.x toolkit available in the environment, 
   - CMake flags `-Donnxruntime_CUDA_ARCH=12` (or `120`) and ensure `-DCUDA_VERSION_MAJOR=13` is detected,
   - Optionally TensorRT 10.x if available; otherwise keep TRT off and test CUDA EP only.
3) Rebuild PyTorch with safety switches:
   - `USE_CUDNN=0` (hard disable), `USE_MKLDNN=0` not relevant but keep minimal; 
   - Verify NVCC flags include `-gencode arch=compute_120,code=sm_120` consistently; 
   - Keep flash-attention/mem-efficient attention OFF as before.
4) If you need partial GPU now:
   - Move only the Hifi-GAN/HIFT vocoder to ONNX/ORT CPU or Torch CPU and keep LLM/flow on CPU as well (functional baseline), then progressively swap components back to GPU when the stack is updated.

### About RT Cores vs Tensor Cores

- RT Cores（光追核心）主要用于图形光线追踪，不参与常规深度学习计算。
- 深度学习推理主要受益于 Tensor Cores（张量核心），通过 cuDNN / CUTLASS / TensorRT 等库加速。
- 要“充分利用 5080”，应优先：
  - 使用支持 Blackwell 的 TensorRT（10.x+），并将热点算子/子图编译成 TRT engine；
  - 或使用包含 Blackwell 优化的 PyTorch/cuDNN 组合，启用 AMP/TF32（在质量允许时）与最优卷积算法搜索。

## What to measure (and what to skip)

- Measure TTFT (first-audio delay) and per-chunk latency only when GPU path is fixed.
- Skip average RTF on CPU in WSL2 — it’s dominated by interop and not actionable (values ~100x–800x slower than native).

## TRT A/B 快速对比（GPU 路径稳定后）

当主模型 CUDA 路线与 ORT CUDA EP 稳定后，可用小工具 `env_check/run_cosyvoice2_trt_ab.py` 快速评估开启 TensorRT 的端到端收益。

- 切换方式：默认通过环境变量 `COSY_LOAD_TRT=0/1` 控制；如你的零样本脚本自带 `--load_trt`，也可以直接写入命令。
- 解析指标：从 stdout 中解析 `TTFT: X.XXX s`；并记录总墙钟时间。结果保存为 CSV，便于横向对比。

示例命令（按需替换文本与音频路径）：

```powershell
wsl -e bash -lc "\
  source ~/.venvs/ptsrc/bin/activate; cd .; \
  python -m env_check.run_cosyvoice2_trt_ab \
    --cmd \"python -m env_check.run_cosyvoice2_zero_shot --text '你好世界' --prompt_wav env_check/zero_shot_prompt.wav --use_flow_cache --use_fp16\" \
    --trt-env COSY_LOAD_TRT \
    --csv env_check/trt_ab_results.csv\
"
```

判定建议：
- 高并发/低延迟场景：若 B（TRT=1）TTFT 与 wall time 明显下降（>30%），建议切换到 TRT；
- 离线/演示场景：若收益有限且显存紧张，可继续保持 PyTorch/ORT 后端。

## Change log

- 2025-11-01:
  - Added `COSY_ORT_NO_TRT` guard and allowed CPU fallback in GPU-only path for speech tokenizer.
  - Kept all frontend output tensors on CPU to avoid unnecessary CUDA copies.
  - Documented ORT/Torch CUDA misaligned-address failures on RTX 5080 (CUDA 13.0/cuDNN 9.14).
