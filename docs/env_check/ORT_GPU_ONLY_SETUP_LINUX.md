# ONNX Runtime GPU-only（Linux，支持 Blackwell/SM 12.0）构建与运行指北

本指南帮助你在 Linux 上为 CosyVoice 前端实现“尽量全部在 GPU 内运行”的最小改动方案，并在需要时升级到自编译 ONNX Runtime（含 CUDA 与 TensorRT/TensorRT-RTX EP，且支持 SM 12.0）。

适用读者：
- 目标机器为 Linux（推荐 Ubuntu 22.04+）
- GPU 为 NVIDIA RTX 50/Blackwell（SM 12.0/12.2）
- 希望 Cosy 前端 campplus/speech tokenizer 全部用 CUDA/TRT 执行，减少 CPU/PCIe 往返

## 1. 版本矩阵与先决条件

- 驱动：建议 ≥ 555.85（CUDA 12.5+），若使用 CUDA 12.9 或 TensorRT-RTX，请按官方要求对应更高版本
- CUDA：12.x（建议 12.9 以兼容 TRT-RTX 与最新内核）
- cuDNN：9.x（与 ORT CUDA 12.x 对齐）
- TensorRT：
  - 经典 TRT EP：10.9+（与 ORT 1.22+/main 兼容）
  - TensorRT-RTX EP：需要 CUDA 12.9 与 TRT-RTX 1.1（main/1.23 文档）
- CMake：≥ 3.24（支持 CMAKE_CUDA_ARCHITECTURES=native）
- Python：3.10–3.12（与 onnxruntime 对齐）

参考：
- ONNX Runtime CUDA EP 文档与编译参数（CMAKE_CUDA_ARCHITECTURES=120 或 native）
- ONNX Runtime TensorRT/TensorRT-RTX EP 文档
- CUDA/驱动版本兼容（CUDA 12.x 需驱动 ≥ 525；CUDA 13.x 需驱动 ≥ 580）

## 2. 快速自检：GPU Provider 能否用

在本仓库运行环境探针脚本（见本目录 `ort_gpu_probe.py`），它会：
- 打印 ORT 可用 Provider 列表
- 尝试创建 CUDA/TRT/TensorRT-RTX EP 的 Session（若安装了）
- 如可用，做一次极小 onnx 模型的 IOBinding 运行（GPU→GPU）

若 CUDA/TRT Provider 不可用或执行失败，继续第 3 节自编译 ORT。

## 3. 自编译 ONNX Runtime（含 CUDA / TensorRT）

推荐使用 ORT 官方脚本：
- 仅 CUDA EP：
  - `./build.sh --use_cuda --cuda_home /usr/local/cuda --cudnn_home /usr/lib/x86_64-linux-gnu --cmake_extra_defines 'CMAKE_CUDA_ARCHITECTURES=120' --config Release --parallel --build_wheel`
- CUDA + TensorRT（内置 parser）：
  - `./build.sh --use_cuda --use_tensorrt --tensorrt_home /usr/lib/x86_64-linux-gnu --cuda_home /usr/local/cuda --cudnn_home /usr/lib/x86_64-linux-gnu --cmake_extra_defines 'CMAKE_CUDA_ARCHITECTURES=120' --config Release --parallel --build_wheel`
- CUDA + TensorRT（OSS parser，可选）：
  - `./build.sh ... --use_tensorrt_oss_parser --skip_submodule_sync`

注意：
- `CMAKE_CUDA_ARCHITECTURES=120` 直指 Blackwell；也可用 `native` 自动匹配
- 若内存有限，可加 `--parallel 4 --nvcc_threads 1` 降低并行度
- 生成的 wheel 在 `build/Linux/Release/dist/` 下，用 `pip install` 安装

### 3.1 TensorRT-RTX（可选，高优先尝鲜）

如需 TensorRT-RTX EP：
- 需要 CUDA 12.9 与 TensorRT-RTX 1.1（驱动 555.85+，推荐 570/575/580 系列）
- 参考 ORT 文档：
  - `./build.sh --config Release --use_nv_tensorrt_rtx --tensorrt_rtx_home "/opt/nvidia/tensorrt-rtx" --cuda_home "/usr/local/cuda" --build_shared_lib --skip_tests --build --update`
- 安装生成的 python wheel 后即可在 Python 里注册 `TensorRTRTXExecutionProvider`

## 4. 运行 Cosy 前端的环境变量与建议

本仓库已支持以下开关（Windows 版等价，Linux 同用）：

- `COSY_GPU_ONLY=1` 强制只注册 GPU Provider（TRT/CUDA），没有则报错（便于尽早暴露问题）
- `COSY_ORT_IOBIND=1` 开启 ONNX IOBinding，最大化减少 Host↔GPU 拷贝
- `COSY_ORT_TRT=1` 在语音 tokenizer 优先注册 TensorRT（若无则回落到 CUDA）
- `COSY_ORT_SPEECH_CPU=1` 强制语音 tokenizer 用 CPU EP（诊断用）
- `COSY_FRONTEND_CPU=1` 整个前端只在 CPU 上跑（兜底诊断）

新增（本次补充）：针对 TRT/CUDA Provider 选项（只要设置就生效，未设置不影响默认行为）：
- TRT：
  - `COSY_ORT_TRT_FP16=1` 开启 FP16
  - `COSY_ORT_TRT_CACHE=1` 开启引擎缓存，`COSY_ORT_TRT_CACHE_PATH=/path/to/cache`
  - `COSY_ORT_TRT_TIMING_CACHE=1` 与 `COSY_ORT_TRT_TIMING_CACHE_PATH=/path/to/tcache`
- CUDA：
  - `COSY_ORT_CUDA_TF32=0|1` 控制 TF32（默认 1）
  - `COSY_ORT_CUDA_MAX_WORKSPACE=0|1` 是否允许 cuDNN 使用最大工作区（Conv-heavy 有帮助）

## 5. 常见问题（Linux）

- 找不到 CUDA/cuDNN/TensorRT 动态库
  - 确保 PyTorch 已导入或使用 `onnxruntime.preload_dlls()`（仅 Windows 需关注 DLL；Linux 主要依赖系统路径/ldconfig）
- CUDA EP 报错 `cudaErrorNoKernelImageForDevice`（SM 不匹配）
  - 自编译 ORT，指定 `CMAKE_CUDA_ARCHITECTURES=120` 或 `native`
- TRT 启动慢/首次构建时间长
  - 开启引擎缓存与 timing cache，并持久化到磁盘；下次会显著加速
- Blackwell 上 FP16/FP8 的已知限制
  - 参考 TensorRT Release Notes，必要时切 BF16/FP32 试验对照

## 6. 验证步骤（建议顺序）

1) 运行 `env_check/ort_gpu_probe.py`，确保 CUDA/TRT/TensorRT-RTX 至少有其一能创建 Session 并成功一次推理
2) 设置 `COSY_GPU_ONLY=1`，再跑探针；若失败则按第 3 节重建 ORT
3) 在 Cosy 前端运行：
   - `COSY_GPU_ONLY=1` 与 `COSY_ORT_IOBIND=1` 同时打开
   - 若要 TensorRT：再加 `COSY_ORT_TRT=1` 与缓存相关变量
4) 采集 TTFT/RTF 与漂移，评估 GPU-only 路径收益

祝顺利。如果你需要一键 Dockerfile 或 CI 构建脚本，可在有结论后补充。
