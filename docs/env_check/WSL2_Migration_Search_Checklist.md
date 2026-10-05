# WSL2 迁移可执行搜索清单（关键词/版本点/验证要点/权威来源）

> 目的：在无法直接联网时，给联网代理一个明确的搜索任务单；当可联网时，也可自助核对关键兼容点。

## A. GPU/驱动/WSL 支持
- 关键词：`WSL2 NVIDIA driver CUDA support`, `WSL GPU nvidia-smi not found`, `WSL2 CUDA 12.9 driver requirement`
- 验证要点：Windows 驱动版本是否满足 CUDA 12.x（≥525）、12.9/RTX（≥555.85/570/575/580）；WSL 内 `nvidia-smi` 可用
- 来源：
  - NVIDIA 官方驱动下载与 WSL 文档
  - CUDA Toolkit Release Notes（Driver Compatibility 表）

## B. CUDA/cuDNN（Linux/WSL）
- 关键词：`cuDNN 9 CUDA 12 install Ubuntu 22.04`, `nvidia-cudnn-cu12 pip linux`, `ldconfig cudnn`
- 验证要点：cuDNN 9.x 与 CUDA 12.x 对齐；动态库路径是否在 `ldconfig -p` 中可见
- 来源：
  - NVIDIA cuDNN 安装指南/发行说明
  - Linux 发行版的包/路径说明

## C. TensorRT / TensorRT-RTX
- 关键词：`ONNX Runtime TensorRT Execution Provider requirements`, `TensorRT-RTX EP requirements CUDA 12.9 driver`, `TensorRT 10.9 Blackwell support`
- 验证要点：TRT 10.9+ 与 ORT 1.22+/main；TRT-RTX 1.1 需 CUDA 12.9 与高版本驱动；已知 Blackwell 限制
- 来源：
  - ONNX Runtime TRT/TRT-RTX EP 文档
  - NVIDIA TensorRT Release Notes

## D. ONNX Runtime 编译
- 关键词：`onnxruntime build.sh --use_cuda --use_tensorrt CMAKE_CUDA_ARCHITECTURES=120`, `onnxruntime CUDAExecutionProvider requirements`
- 验证要点：CMake ≥ 3.24；`CMAKE_CUDA_ARCHITECTURES=120`（Blackwell）；可选开启 `--use_tensorrt` 或 `--use_nv_tensorrt_rtx`
- 来源：
  - ONNX Runtime Build with EPs 官方文档
  - CUDA EP 官方要求页面

## E. PyTorch（Blackwell/SM 12.0）
- 关键词：`PyTorch nightly CUDA 12.4 wheel`, `torch Blackwell SM 120 support`, `WSL2 pytorch cuda`
- 验证要点：安装 nightly 或自编译以确保 SM 12.x 支持；`torch.cuda.get_device_name(0)` 正常
- 来源：
  - PyTorch 官方安装页/夜版索引
  - 相关 github issues/讨论（确认 SM 12.0/12.2 情况）

## F. torchaudio / FFmpeg / SoX
- 关键词：`torchaudio CUDA 12 wheels linux`, `ffmpeg install ubuntu 22`, `sox libsox-dev ubuntu`
- 验证要点：torchaudio 与 PyTorch 版本匹配；WSL apt 能装 ffmpeg/sox；遇到 torchaudio 问题可用 soundfile+librosa 回退
- 来源：
  - torchaudio 官方安装说明
  - Ubuntu 包仓库

## G. CosyVoice2-0.5B 模型
- 关键词：`modelscope CosyVoice2-0.5B`, `iic/CosyVoice2-0.5B download`, `CosyVoice-ttsfrd`
- 验证要点：仅下载 0.5B 与 ttsfrd（可选）；如网络受限用 git LFS/镜像
- 来源：
  - ModelScope 页面
  - CosyVoice 官方 README

## H. 性能与验证
- 关键词：`onnxruntime io binding cuda example`, `TensorRT timing cache engine cache`, `CUDA TF32 on/off performance`
- 验证要点：IOBinding 减少 Host↔GPU；TRT 引擎缓存与 timing cache 缩短二次初始化；TF32/FP16 切换对性能与精度的影响
- 来源：
  - ONNX Runtime CUDA EP 文档（IOBinding、配置项）
  - ONNX Runtime TensorRT EP 文档（缓存与配置）
