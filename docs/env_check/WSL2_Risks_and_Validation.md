# WSL2 迁移：风险与验证计划

## 1) 常见风险/坑点

- 驱动/WSL GPU 不通
  - 现象：WSL 内 `nvidia-smi` 报错；CUDA API 调用失败
  - 处理：升级 Windows 驱动至支持 WSL CUDA 的版本（建议 555.85+，更高更好）；重启后在 WSL 再试

- Blackwell（SM 12.x）内核缺失
  - 现象：ORT CUDA 报 `cudaErrorNoKernelImageForDevice`
  - 处理：自编译 ONNX Runtime，`CMAKE_CUDA_ARCHITECTURES=120` 或 `native`

- 动态库不可见（cuDNN/TRT）
  - 现象：`ImportError: lib...so: cannot open shared object file`
  - 处理：确认库在 `ldconfig -p` 可见；或将其父目录加入 `LD_LIBRARY_PATH`

- CMake/GCC 版本不匹配
  - 现象：构建期报 CMake/C++ 特性错误
  - 处理：CMake ≥ 3.24，GCC 建议 11+/12+，`sudo apt-get install cmake build-essential` 并必要时安装更新的 CMake

- TRT 首次构建耗时长
  - 对策：开启 `trt_engine_cache` 与 `trt_timing_cache`，持久化到磁盘

- torchaudio 依赖/编译失败
  - 现象：import/so 加载失败
  - 对策：使用 `soundfile+librosa` 回退（本仓库已集成），或安装与 PyTorch 匹配的 torchaudio 夜版 wheel

## 2) 最小自检命令清单

```bash
# 驱动/WSL GPU
echo '--- nvidia-smi ---'
nvidia-smi || true

# 动态库（cuDNN/TRT）
echo '--- cudnn ---'
ldconfig -p | grep -i cudnn || true

echo '--- tensorrt ---'
ldconfig -p | grep -i nvinfer || true

# Python/GPU
echo '--- torch ---'
python - << 'PY'
import torch
print('torch', torch.__version__, 'cuda', torch.version.cuda)
print('is_cuda', torch.cuda.is_available())
print('device', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')
PY

# ONNX Runtime Provider 与 CUDA IO-binding 小测
echo '--- onnxruntime probe ---'
python env_check/ort_gpu_probe.py || true
```

## 3) 成功标准与回归点

- 成功标准：
  - `nvidia-smi` 可用；PyTorch 能看到 GPU；ORT Probe 显示 CUDA/TRT Provider
  - CosyVoice2-0.5B 零样本推理可以完成；TTFT/RTF 较 CPU 回退有明显改善

- 回归点：
  - 升级驱动/库后重新跑自检命令；若失败，回看上一个通过的组合（记录版本矩阵）
