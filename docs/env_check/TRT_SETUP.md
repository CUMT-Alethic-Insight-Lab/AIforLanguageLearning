# TensorRT / Blackwell (RTX 5080, SM 12.0) 准备与启用

本说明用于在 WSL2 Ubuntu 22.04 与 Windows 11 上准备可用于 CosyVoice2 的 TensorRT 路线，并与 PyTorch/ORT 协同工作。请结合 `BLACKWELL_BUILD_ROUTES.md` 的分阶段策略使用。

> 提示：当前重点是 Tensor Cores 加速，RT Cores 不用于通用 AI 计算。

## 1. 版本与兼容性建议
- GPU/驱动：RTX 5080（Blackwell，SM 12.0），NVIDIA 驱动版本需满足 CUDA 13.x 要求。
- CUDA Toolkit：13.1 或更新的小版本（与驱动匹配）。
- cuDNN：9.2+（与 CUDA 小版本配套）。
- TensorRT：与上述 CUDA/驱动匹配且在发行说明中明确支持 RTX 50xx/SM 12.0 的最新版本。
- Python：3.10/3.11。

## 2. 安装 TensorRT（两种主流方式）

1) 使用 NVIDIA 提供的本地安装包（.tar/.deb）
- 到 NVIDIA Developer 下载与你平台/版本匹配的 TensorRT 包（Linux x86_64）。
- 解压/安装后，确保以下路径加入环境：
  - `LD_LIBRARY_PATH` 包含 TensorRT 的 lib 目录。
  - `PATH` 包含相关可执行工具（如 trtexec）。
- Python 轮子：使用 pip 安装与该版本匹配的 `tensorrt`/`tensorrt_libs`/`nvinfer` 等包。

2) 使用 NGC 容器（推荐做法用于验证）
- 拉取与 Blackwell 支持声明一致的 TensorRT 或 Triton-TRTLLM 镜像。
- 在容器内进行引擎构建与测试（更少的宿主依赖问题）。

> 注意：WSL2 中建议优先使用容器方案进行引擎构建和 A/B 实验；落地后再迁移到宿主环境。

### Windows 宿主（本仓现状）

仓库已包含 `TensorRT-10.13.3.9/`（版本号以目录为准）。要在 Windows 上启用 CosyVoice2 内部 TensorRT：

1) 运行时库（ORT TRT EP 以及后续内部 TRT 引擎加载）：
  - `env_check/run_iobind_windows.ps1` 在 `-TryTRT` 时已将 TensorRT/CUDA 的 `lib/bin` 目录追加到 `PATH`。
  - 如需手动：确保将 `TensorRT-*/lib` 或 `TensorRT-*/lib/windows-x86_64` 加入 `PATH`，并确保 `CUDA_PATH/bin` 在 `PATH` 里。

2) 安装 Python TensorRT（用于 CosyVoice2 内部 `tensorrt` 包）：
  - 建议使用与目录中相同版本的本地 wheel：在 `TensorRT-*/python` 下找到对应 Python 版本的 `.whl`，在目标 Conda 环境中执行 `pip install <wheel>`。
  - 如有官方 PyPI 包（如 `nvidia-tensorrt`），请确保版本与本地 `TensorRT-*` 目录匹配，避免 `DLL load failed`。

  示例（PowerShell，Python 3.11 环境）：

  ```powershell
  conda run -p C:\Users\74090\Miniconda3\envs\torchnb311 python -V
  conda run -p C:\Users\74090\Miniconda3\envs\torchnb311 python -m pip install -U `
    ".\TensorRT-10.13.3.9\python\tensorrt-10.13.3.9-cp311-none-win_amd64.whl"
  ```

  验证导入（可选）：

  ```powershell
  conda run -p C:\Users\74090\Miniconda3\envs\torchnb311 python -c `
    "import tensorrt as trt; print('TRT version:', trt.__version__)"
  ```

3) 启用 CosyVoice2 内部 TRT（flow decoder estimator）：
  - 运行脚本参数：`env_check/run_iobind_windows.ps1 -LoadTrtEstimator`（脚本会设置 `COSY_CV2_TRT=1`）
  - 首次构建或更换 shape 配置，可设置 `COSY_REBUILD_TRT=1` 以强制重新生成 plan（文件名形如 `flow.decoder.estimator.fp32.mygpu.plan`）。
  - 精度建议：先用 FP32（稳定性优先），稳定后再尝试 FP16。

  结合推荐参数的完整示例：

  ```powershell
  $env:COSY_FP16='0'                 # 内部 TRT 引擎 FP32
  $env:COSY_AMP_DTYPE='bf16'         # PyTorch AMP 用 bf16
  $env:COSY_REBUILD_TRT='1'          # 首次/重建
  & .\env_check\run_iobind_windows.ps1 `
    -CondaEnvPath 'C:\Users\74090\Miniconda3\envs\torchnb311' `
    -Langs 'zh' -TryTRT -TrtFp16:$false -TokenHop 32 -LoadTrtEstimator
  ```

4) 失败排查：
  - `ModuleNotFoundError: tensorrt`：未安装 Python 包，请按上文第 2 步安装。
  - `DLL load failed`：TensorRT 运行时库未在 `PATH`；或 Python 包与本地 TRT 版本不匹配。
  - 构建慢/不稳定：先用 FP32；必要时固定更窄的动态 shape profile（`cosyvoice.cli.model.get_trt_kwargs` 已提供合理范围）。

## 3. 与 ONNX Runtime 协同
- 初期禁用 ORT TensorRT EP（保持 CUDA EP），待主模型 CUDA 路线稳定后再评估 TRT 子图化。
- 若启用 ORT TensorRT EP，建议先固定输入形状与算子集合，避免动态 shape/插件带来的不确定性。
- 源码构建 ORT 建议：
  - 启用 CUDA：`--use_cuda`，并指定 `--cuda_home`、`--cudnn_home`。
  - 设置架构：`--cuda_compute_capabilities=12.0`。

## 4. CosyVoice2 端启用方式
- 若项目侧提供 `load_trt=True`/`--load_trt`，直接在加载/命令行开启。
- 若项目以环境变量切换，统一使用 `COSY_LOAD_TRT=1` 代表开启（可配合 `env_check/run_cosyvoice2_trt_ab.py` 做 A/B）。
- 精度建议：先上 FP16（或 BF16），若显存吃紧并追求吞吐，再做 INT8（准备 200–500 条本业务语料做校准集）。

## 5. 验证与度量
- 单条用例：记录 TTFT、总墙钟时长（可由 A/B 脚本自动解析输出 CSV）。
- 并发用例：使用多个并发请求测试吞吐提升；可基于 Triton（HTTP/gRPC）压测。
- 质量：对比 MOS 或客观分数（若有），确认 INT8/混合精度对音质影响可接受（通常 <0.05）。

## 6. 常见问题
- Blackwell 初期：若 trtexec/引擎构建报错，请首先确认当前 TensorRT 版本在发行说明中明确支持 RTX 50xx/SM 12.0，必要时更新到更高版本或使用 NGC 夜版镜像。
- 混合精度溢出：尝试禁用特定层的 FP16/INT8 或切回 FP16/BF16；对注意力/归一化类算子尤其关注。
- 引擎体积/显存：多引擎或多音色时，注意总显存消耗；按需拆分子图或启用按需加载。

## 7. 生产部署提示
- 直接使用 Triton + TensorRT-LLM（若有）镜像：
  - docker-compose 一键启动，提供 HTTP/gRPC 服务与并发调度；
  - 在服务层做音色注册缓存（参考音频预计算），进一步降低首包延迟。
- 监控：记录 TTFT、每 chunk 延迟、失败率、显存占用与 GPU 利用率，作为回滚与调参依据。
