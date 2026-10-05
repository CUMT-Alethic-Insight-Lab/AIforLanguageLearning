# Blackwell (SM 12.0, RTX 5080) 编译与运行路线

本文档给出在 WSL2 Ubuntu 22.04 上让 CosyVoice2 在 RTX 5080 全流程跑在 GPU 上的可行编译路线与验证步骤，并明确：不尝试使用 RT Cores 加速 AI 计算，统一走 Tensor Cores 路线。

## 结论先行：RT Core 不用于通用 AI
- RT Cores 是专用的 BVH 遍历与光线/三角形相交固定功能单元，仅通过 DXR/Vulkan Ray Tracing/OptiX 等光追 API 暴露。
- AI 计算（矩阵乘加）由 Tensor Cores/SM 完成。DLSS/Neural Shaders 中的“AI”也运行在 Tensor Cores 上。
- 因此，本项目放弃“用 RT Core 加速 AI”的尝试，专注于 Tensor Cores+CUDA/cuDNN/TensorRT。

参考：NVIDIA 技术白皮书与博客《NVIDIA Turing Architecture In‑Depth》明确 RT Cores 职责为 BVH 遍历与交点测试；Tensor Cores 专用于深度学习矩阵运算。

---

## 路线 A：纯 PyTorch CUDA 路线（首选，改动最小）
适合先稳定 PyTorch 主干模型在 GPU 路径运行，再逐步打开前端/子图。

- 工具链建议（Blackwell 兼容）：
  - CUDA Toolkit ≥ 13.1（建议使用发行版随驱动匹配的 13.x 最新小版本）
  - cuDNN ≥ 9.2（9.14 亦可，但建议与 CUDA 小版本配套）
  - Python 3.10/3.11
  - NVCC 架构：sm_120
- PyTorch 从源码构建要点：
  - 环境变量：
    - TORCH_CUDA_ARCH_LIST="12.0"
    - USE_CUDA=1, USE_CUDNN=1
    - MAX_JOBS 根据 CPU 线程数设置
  - 关闭与 Blackwell 不兼容的老旧/自定义注意力核，先用官方 SDPA/Memory‑Efficient Attention（必要时再引入 flash-attn 新版本验证）。
- 运行策略：
  - 保持 Cosy 前端（分词/特征/ONNX 子图）先在 CPU；仅将主模型（flow/vocoder/backbone）迁移到 CUDA。
  - 默认精度：BF16 或 FP16（二选一），开启 TF32（对卷积/矩阵乘有益）。

### 最小验证
- torch.cuda.is_available() 为 True；设备能力为 (12, 0)。
- 简单前向：随机张量在 CUDA 上完成一次注意力/卷积；确保无 "misaligned address" 等运行时错误。

---

## 路线 B：ONNX Runtime CUDA EP（关闭 TRT 起步）
在 A 路线稳定后，可将 CosyVoice2 中 ONNX 子图切回 ORT 的 CUDA EP。

- 版本建议：ONNX Runtime ≥ 1.20（更高亦可；需自行源码构建以包含 sm_120 支持）
- 构建要点：
  - 启用 CUDA EP，禁用 TensorRT EP（初期）：
    - --use_cuda --cuda_home=/usr/local/cuda --cudnn_home=/usr/local/cudnn
    - --cuda_compute_capabilities=12.0
  - 先禁用 IOBinding，确认稳定后再逐步开启。
- 最小验证：加载一个小 ONNX（Conv/MatMul）在 CUDA EP 推理，核对 providers 中包含 "CUDAExecutionProvider"，且输出正确。

---

## 路线 C：TensorRT（可选优化，待稳定后引入）
针对瓶颈子图（如部分卷积堆栈/MLP）尝试 TRT 引擎，观察端到端收益。

- 版本建议：使用与当前 CUDA 13.x/驱动匹配、且明确支持 Blackwell/SM 12.0 的最新 TRT 版本（请以发行注记为准）。
- 起步策略：
  - 仅挑选计算密集、算子友好的子图导出到 TRT；其余仍走 PyTorch/ORT。
  - 动态形状与插件算子谨慎开启，优先固定输入尺寸得到稳定引擎。

---

## 渐进式启用 GPU 的步骤
1) 阶段 1（PyTorch 主模型 on CUDA）
- 仍保留前端/ORT 在 CPU；仅把大模型移到 CUDA，精度用 BF16/FP16。
- 如出现 "misaligned address"：
  - 导出 CUDA_LAUNCH_BLOCKING=1 以收敛报错栈；
  - 关闭可疑自定义 kernel/flash‑attn，退回官方 SDPA；
  - 尝试切换 BF16/FP16/TF32；确认 cuDNN 已启用。

2) 阶段 2（ORT CUDA EP）
- 将 ONNX 子图的 provider 从 CPU 切到 CUDA；仍禁用 IOBinding。
- 验证稳定后再开启 IOBinding 与 pinned memory。

3) 阶段 3（可选 TRT）
- 子图级别导出/构建 TRT 引擎；对比端到端 TTFT/RTF/音频漂移。

---

## 性能与精度建议
- 首选 BF16（Blackwell 张量核对 BF16 支持完善），如受限再用 FP16，并启用 TF32（适配 GEMM/conv）。
- 统一张量驻留策略，减少 CPU↔GPU 迁移；分块流式写 wav，避免阻塞主计算。
- 仅在稳定后启用 IOBinding/流水线并行，以避免排查复杂度激增。

---

## 故障排查清单（RTX 5080）
- 驱动/Toolkit/Runtime 版本匹配：驱动 ≥ 对应 CUDA 13.x 要求；cuDNN 与 CUDA 小版本一致。
- 架构目标正确：编译时包含 sm_120；检查二进制 PTX/SASS 中含 120 架构。
- 关闭不兼容 kernel：优先使用官方 SDPA；第三方注意力库需确认已标注支持 Blackwell。
- 若 ORT CUDA EP 不稳定：回退到 CPU EP 验证正确性，再最小化子图迁移。

---

## 里程碑验收
- M1：CPU-only 流式零样本（已完成）。
- M2：主模型 PyTorch CUDA 通路稳定，无运行时错误，生成流式 wav。
- M3：ORT 子图切到 CUDA EP 并稳定，IOBinding 可开启。
- M4（可选）：关键子图 TRT 化有端到端收益。

---

## 附：验证脚本建议
- 继续使用 `env_check/run_cosyvoice2_zero_shot.py`：
  - 提供 `--use_fp16/--use_bf16/--use_flow_cache` 与设备开关；
  - 通过环境变量控制 ORT provider、TRT/IOBinding/前端设备驻留，便于 AB 对比与回退。