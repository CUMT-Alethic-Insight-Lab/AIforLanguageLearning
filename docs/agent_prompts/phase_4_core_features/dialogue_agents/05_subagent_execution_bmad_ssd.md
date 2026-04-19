# Phase4 对话模块 Subagent 执行方案（SSD + BMAD）

## 1. 目标

在不牺牲稳定性的前提下，完成 Phase4 对话核心链路的工程化升级：
1. Cloud Kimi（moonshot-v1-auto）与 Local Qwen3.5-9B 并发竞速，先返回先生效。
2. 去除“固定轮次截断”历史策略，改为全量事件历史组装（后续可加 token 策略）。
3. ASR 文本保持后端可处理与可追踪，但前端默认不直接展示文本内容。
4. USER_MESSAGE / AI_MESSAGE 作为主要对话历史来源。
5. 全流程可回滚、可观测、可测试。

---

## 2. SSD 状态流（必须遵守）

连接完成 -> 音频采集中 -> ASR已提交 -> 双模型竞速中 -> AI已提交 -> TTS输出中 -> 完成/中断

状态一致性约束：
- 每次关键状态跃迁必须产生可追踪事件。
- 历史拼装主源只读 USER_MESSAGE / AI_MESSAGE（兼容桥可读旧事件）。
- 竞速只能有一个 winner；loser 必须显式取消。

---

## 3. BMAD 边界（必须遵守）

1. 应用编排层（main/ws）
- 负责会话流程、事件发送、错误恢复、并发任务取消。
- 不负责模型 SDK 细节。

2. 模型调用层（llm/model routing）
- 负责模型参数、流式读取、超时与异常封装。
- 不负责 WebSocket 协议拼包。

3. 存储层（conversation events/context）
- 负责事件持久化与历史查询。
- 不负责业务决策。

4. 测试层
- 负责竞速、历史、中断、回放、回滚开关验证。
- 不改业务逻辑。

---

## 4. 任务包划分（MVP 第一轮）

### WP-01: Race Runner + 双模型并发接入
- 负责：并发调度 Cloud/Local，先完成者获胜，取消慢任务。
- 关键文件：backend_fastapi/app/main.py, backend_fastapi/app/llm.py
- 验收：
  - 可记录 winner_source=cloud|local
  - loser 协程被取消
  - 无重复 AI_MESSAGE

### WP-02: 全量历史组装与事件主源切换
- 负责：历史读取改为 USER_MESSAGE/AI_MESSAGE 主源，不做固定轮次硬截断。
- 关键文件：backend_fastapi/app/main.py
- 验收：
  - 不再出现 max_messages=10 这种硬编码截断
  - 历史顺序与事件 seq 一致

### WP-03: ASR 静默展示协议
- 负责：后端保留 ASR 可观测性，默认不给前端直出文本。
- 关键文件：backend_fastapi/app/main.py
- 验收：
  - ASR 不直出文本字段（仅状态/元信息）
  - USER_MESSAGE 正常落库

### WP-04: 回归测试与质量门禁
- 负责：补齐异步竞速和历史相关测试。
- 关键文件：backend_fastapi/tests/*
- 验收：
  - 至少覆盖 winner 唯一性、历史全量加载、ASR 静默输出

---

## 5. 可直接执行的 Subagent Prompts

## Prompt-01（实现型，优先执行）

你是后端实现 subagent，负责 WP-01 + WP-02 + WP-03 的最小可交付实现。

任务目标：
1. 在 ws finalize 流程引入双模型并发竞速：
- cloud: moonshot-v1-auto
- local: qwen3.5-9b
- 使用 asyncio.wait(..., return_when=FIRST_COMPLETED)
- winner 结果写入 AI_MESSAGE，loser 取消。

2. 将历史组装从旧的 ASR_FINAL/LLM_RESULT + 固定 max_messages 改为：
- 主读 USER_MESSAGE + AI_MESSAGE
- 全量加载（不做 10 轮硬截断）
- 保持 seq 升序。

3. ASR 处理改为静默协议：
- 允许后端保存 USER_MESSAGE(text, source=asr)
- 对前端 ASR 事件默认不携带原文 text（沉浸模式）

实施要求：
- 修改尽量小、可读性高，不破坏现有 API 兼容。
- 对新增逻辑写简短注释，解释竞速取消与历史主源原因。
- 若需要扩展 llm.stream_chat 参数，保持向后兼容。
- 出错时返回可诊断信息，不泄露敏感 key。

必须产出：
1. 代码改动清单（文件级）
2. 关键差异说明（为何这样改）
3. 自测步骤和结果
4. 未完成项与风险

---

## Prompt-02（测试型）

你是测试 subagent，负责 WP-04。

任务目标：
1. 新增/更新测试覆盖：
- 竞速 winner 唯一，loser 被取消
- 历史读取不做固定轮次硬截断
- USER_MESSAGE / AI_MESSAGE 成为历史主源
- ASR 事件静默输出（不含 text）

实施要求：
- 优先复用现有测试结构，不大改目录。
- 异步测试要控制超时，避免偶发抖动。

必须产出：
1. 用例列表与断言点
2. 运行命令
3. 结果摘要
4. 失败场景与建议

---

## Prompt-03（文档与发布）

你是文档与发布 subagent。

任务目标：
1. 更新对话模块实施文档，反映 race 与事件主源新规范。
2. 给出回滚策略：
- 禁用 race
- 回退旧历史读取策略（仅紧急）
- 数据兼容说明

必须产出：
1. 文档更新点
2. 运维回滚手册（最小步骤）
3. 监控指标建议（winner_source, cancel_count, history_events_count）

---

## 6. 执行顺序建议

1. 先执行 Prompt-01（实现）
2. 再执行 Prompt-02（测试）
3. 最后执行 Prompt-03（文档与发布）

并行限制：
- Prompt-01 期间，Prompt-02 可先搭测试骨架但不要提前固化断言。
- Prompt-03 需在 Prompt-01 稳定后再落盘。
