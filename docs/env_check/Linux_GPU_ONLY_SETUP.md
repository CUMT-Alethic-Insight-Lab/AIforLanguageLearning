# CosyVoice2（WSL2/Ubuntu）GPU-only 迁移与验证指南

目标：在 WSL2（Ubuntu 22.04+）中，仅使用 CosyVoice2-0.5B，完成端到端 GPU-only（尽量在 GPU 内执行）的部署与验证，并最少化 CPU/PCIe 往返。

本指南默认你已在 Windows 安装支持 WSL 的 NVIDIA 驱动（支持 WSL CUDA），WSL 里可以执行 `nvidia-smi`。

## 0. 环境要求与快速检查

- Windows：NVIDIA 驱动支持 WSL（建议 555.85+，更新至 GeForce 570/575/580 系列更稳）
- WSL2：Ubuntu 22.04 LTS（推荐）
- GPU：NVIDIA RTX 50/Blackwell（SM 12.0/12.2）
- Python：3.10（与 Cosy repo 要求匹配）

在 WSL 里先确认：

```bash
nvidia-smi
uname -a
cat /etc/os-release
```

如 `nvidia-smi` 不通，先修 Windows 侧驱动与 WSL GPU 支持，参考 NVIDIA/微软官方文档。

## 1. Linux/WSL2 依赖与版本要点（与 Windows 差异）

- CUDA：12.x（建议 12.9+）；WSL2 可选择安装 toolkit（用于编译 ORT），也可仅依赖 PyTorch/ORT 的打包运行库
- cuDNN：9.x（与 ORT CUDA 12.x 对齐）；WSL 中常见路径：`/usr/lib/x86_64-linux-gnu` 或 `site-packages/nvidia/*`
- TensorRT：
  - 经典 TensorRT EP：10.9+（与 ORT 1.22+/main 兼容）
  - TensorRT-RTX EP：需 CUDA 12.9 与 TRT-RTX 1.1（前沿特性，驱动/版本更高）
- ONNX Runtime：建议自编译，开启 `--use_cuda`（可选 `--use_tensorrt`/`--use_nv_tensorrt_rtx`），并指定 `CMAKE_CUDA_ARCHITECTURES=120`（Blackwell）
- PyTorch：为确保 Blackwell/SM 12.0 支持，建议 nightly/cu12.4+（或自行编译）。示例见下。
- torchaudio：需与 PyTorch CUDA 版本匹配；若装配困难，本仓库已提供 `soundfile+librosa` 回退路径
- FFmpeg/SoX：音频处理常用，WSL 安装更方便（`apt`）

与 Windows 的差异：
- Linux 主要通过 `LD_LIBRARY_PATH`/`ldconfig` 解析动态库；无 DLL 预加载概念
- WSL2 的 GPU 依赖由 Windows 驱动提供，WSL 端无需安装驱动包，但 toolkit/headers 如需编译仍需安装

## 2. 创建 Conda 环境与基础依赖

```bash
# Miniconda 安装略，进入 WSL 后：
conda create -n cosyvoice python=3.10 -y
conda activate cosyvoice

# WeTextProcessing 的 pynini（跨平台建议用 conda 安装）
conda install -y -c conda-forge pynini==2.1.5

# 基础音频工具（WSL 下更易安装）
sudo apt-get update
sudo apt-get install -y sox libsox-dev ffmpeg
```

## 3. 安装 PyTorch（Blackwell 友好）

优先选择官方 nightly（CUDA ≥ 12.4），或可用你已验证的自编译包：

```bash
# 示例：pytorch nightly（请按官网当日说明调整）
pip install --pre torch --index-url https://download.pytorch.org/whl/nightly/cu124
pip install --pre torchaudio --index-url https://download.pytorch.org/whl/nightly/cu124

# 验证 GPU 可用性
python - << 'PY'
import torch
print('torch:', torch.__version__, 'cuda:', torch.version.cuda)
print('device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda')
PY
```

如 Blackwell 上 nightly 不可用，可暂走你已有的自编译 torch 方案。

## 4. 克隆 CosyVoice（仅用 CosyVoice2-0.5B）

```bash
git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git
cd CosyVoice
# 若子模块超时，重复执行：
# git submodule update --init --recursive

# 安装 python 依赖（可用镜像视网络而定）
pip install -r requirements.txt
```

仅下载 CosyVoice2-0.5B 与（可选）ttsfrd 资源：

```bash
# 方式A：modelscope SDK（需可联网）
python - << 'PY'
from modelscope import snapshot_download
snapshot_download('iic/CosyVoice2-0.5B', local_dir='iic/CosyVoice2-0.5B')
snapshot_download('iic/CosyVoice-ttsfrd', local_dir='pretrained_models/CosyVoice-ttsfrd')
PY

# 方式B：git LFS（如可访问 modelscope）
mkdir -p pretrained_models
git clone https://www.modelscope.cn/iic/CosyVoice2-0.5B.git pretrained_models/CosyVoice2-0.5B
git clone https://www.modelscope.cn/iic/CosyVoice-ttsfrd.git pretrained_models/CosyVoice-ttsfrd

# 可选：解压并安装 ttsfrd（非必须，无则回退 WeTextProcessing）
cd pretrained_models/CosyVoice-ttsfrd/
unzip resource.zip -d . || true
pip install ttsfrd_dependency-0.1-py3-none-any.whl || true
pip install ttsfrd-0.4.2-cp310-cp310-linux_x86_64.whl || true
cd -
```

## 5. 构建 ONNX Runtime（GPU-only 前端，推荐）

若仅使用 PyTorch 路径也可运行，但为了前端 tokenizers 在 GPU 内执行并减少 PCIe 往返，建议自编译 ORT：

```bash
# 获取 ORT 源码
git clone https://github.com/microsoft/onnxruntime.git
cd onnxruntime

# 仅 CUDA EP（Blackwell：arch=120，或用 native）
./build.sh --config Release --parallel \
  --use_cuda --cuda_home /usr/local/cuda --cudnn_home /usr/lib/x86_64-linux-gnu \
  --cmake_extra_defines 'CMAKE_CUDA_ARCHITECTURES=120' --build_wheel

# CUDA + TensorRT（可选）
# ./build.sh --config Release --parallel \
#   --use_cuda --use_tensorrt --tensorrt_home /usr/lib/x86_64-linux-gnu \
#   --cuda_home /usr/local/cuda --cudnn_home /usr/lib/x86_64-linux-gnu \
#   --cmake_extra_defines 'CMAKE_CUDA_ARCHITECTURES=120' --build_wheel

# 安装 wheel（路径以实际构建输出为准）
pip install build/Linux/Release/dist/onnxruntime_gpu*.whl
```

验证 ORT Provider（在你的工程根目录运行）：

```bash
python env_check/ort_gpu_probe.py
```

## 6. 运行时环境变量（GPU-only 路径）

- 强制仅用 GPU Provider：
  - `COSY_GPU_ONLY=1`
- 启用 IOBinding：
  - `COSY_ORT_IOBIND=1`
- 优先 TensorRT（若已构建）：
  - `COSY_ORT_TRT=1`
  - 引擎缓存：`COSY_ORT_TRT_CACHE=1` `COSY_ORT_TRT_CACHE_PATH=./trt_engines`
  - timing cache：`COSY_ORT_TRT_TIMING_CACHE=1` `COSY_ORT_TRT_TIMING_CACHE_PATH=./trt_timing`
- CUDA 可选项：
  - `COSY_ORT_CUDA_TF32=0|1`（默认 ORT 行为，设 0 可禁用 TF32）
  - `COSY_ORT_CUDA_MAX_WORKSPACE=1`（Conv-heavy 常有性能收益）

## 7. 最小运行示例（仅 CosyVoice2-0.5B）

```python
import sys
sys.path.append('third_party/Matcha-TTS')
from cosyvoice.cli.cosyvoice import CosyVoice2
from cosyvoice.utils.file_utils import load_wav
import torchaudio

cosyvoice = CosyVoice2('iic/CosyVoice2-0.5B', load_jit=False, load_trt=False, fp16=False)

prompt_speech_16k = load_wav('zero_shot_prompt.wav', 16000)
for i, j in enumerate(cosyvoice.inference_zero_shot(
    '收到好友从远方寄来的生日礼物，那份意外的惊喜与深深的祝福让我心中充满了甜蜜的快乐，笑容如花儿般绽放。',
    '希望你以后能够做的比我还好呦。',
    prompt_speech_16k,
    stream=False
)):
    torchaudio.save(f'zero_shot_{i}.wav', j['tts_speech'], cosyvoice.sample_rate)
```

若 `torchaudio` 装配不顺，本仓库已在加载音频处加入 `soundfile+librosa` 回退，仍可继续。

## 8. 常见坑与排查

- `nvidia-smi` 在 WSL 内不可用：
  - 升级 Windows 驱动并启用 WSL GPU，重启后重试
- ORT CUDA 错误 `cudaErrorNoKernelImageForDevice`：
  - 说明预编译包不含 SM 12.x 内核；请自编译 ORT，指定 `CMAKE_CUDA_ARCHITECTURES=120`
- 找不到 cuDNN/TensorRT 库：
  - 确认动态库在 `ldconfig -p` 可见或添加到 `LD_LIBRARY_PATH`
- CMake/GCC 版本不匹配：
  - CMake ≥ 3.24；GCC 建议 11+/12+
- TRT 首次构建慢：
  - 启用引擎缓存与 timing cache，并持久化到磁盘

## 9. 验证清单（WSL2）

```bash
# 驱动/WSL GPU
nvidia-smi

# Python/GPU
python - << 'PY'
import torch
print(torch.__version__, torch.version.cuda)
print('cuda?', torch.cuda.is_available())
print('dev:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')
PY

# ORT Provider 与 CUDA IO-binding 小测
python env_check/ort_gpu_probe.py

# CosyVoice2 最小推理（见第7节）
```
