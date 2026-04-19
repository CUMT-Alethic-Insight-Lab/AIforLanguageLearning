# 成员E：模型路由和上下文管理 - 技术栈要求

## 角色定位
负责构建多模型统一路由和对话上下文管理中枢。

---

## 技术栈深度要求

| 技术 | 深度要求 | 具体掌握内容 |
|------|----------|--------------|
| **LLM API调用** | ⭐⭐⭐⭐⭐ 精通 | OpenAI兼容接口、流式输出、重试机制、Token计算 |
| **vLLM / Ollama** | ⭐⭐⭐⭐ 熟练 | 本地模型部署、并发控制、量化加载、API兼容 |
| **Prompt Engineering** | ⭐⭐⭐⭐⭐ 精通 | System Prompt设计、Few-shot、Chain-of-Thought |
| **上下文管理** | ⭐⭐⭐⭐ 熟练 | 滑动窗口、摘要压缩、Token限制处理 |
| **Python + httpx** | ⭐⭐⭐⭐ 熟练 | 异步HTTP、连接池、超时控制、断路器 |

---

## 必须深入理解的概念

### 1. System Prompt与User Prompt的分工
- System Prompt设定AI角色和行为边界
- User Prompt提供具体任务输入
- 两者的优先级和覆盖关系

### 2. Token限制下的上下文压缩策略
- Token计数方法(tiktoken)
- 滑动窗口保留最近N轮
- 摘要压缩历史对话
- 关键信息提取保留

### 3. 流式输出的SSE(Server-Sent Events)机制
- HTTP长连接保持
- Chunked Transfer Encoding
- 前端EventSource接收
- 取消请求的处理

---

## 核心技能检查清单

### LLM API
- [ ] 能调用OpenAI兼容的API接口
- [ ] 掌握流式输出的实现方式
- [ ] 能实现指数退避重试机制
- [ ] 能准确计算Token数量
- [ ] 理解不同模型的能力差异

### 本地模型部署
- [ ] 能使用vLLM部署大模型
- [ ] 能使用Ollama管理本地模型
- [ ] 掌握模型量化(GPTQ/AWQ)的基本概念
- [ ] 能配置并发请求限制

### Prompt工程
- [ ] 能编写高质量的System Prompt
- [ ] 掌握Few-shot示例设计
- [ ] 理解Chain-of-Thought prompting
- [ ] 能设计输出格式(JSON/结构化)

### 上下文管理
- [ ] 能实现对话历史的存储和恢复
- [ ] 掌握Token超限的处理策略
- [ ] 能进行对话摘要生成
- [ ] 理解多会话管理方案

---

## Copilot引导关键词

```
"实现Kimi API调用带重试和超时控制"
"设计场景扩写Prompt模板输出JSON格式"
"实现对话上下文滑动窗口管理"
"使用vLLM部署Qwen3.5-9B本地模型"
"实现流式输出的SSE接口"
```

---

## 推荐学习资源

| 资源类型 | 名称 | 优先级 |
|----------|------|--------|
| 官方文档 | OpenAI API文档 | ⭐⭐⭐⭐⭐ |
| GitHub | vLLM官方文档 | ⭐⭐⭐⭐⭐ |
| 在线课程 | Prompt Engineering Guide | ⭐⭐⭐⭐⭐ |
| 官方文档 | tiktoken Tokenizer | ⭐⭐⭐⭐ |

---

## 验收标准

- [ ] 模型路由准确率100%(无错配)
- [ ] 上下文恢复成功率>99%
- [ ] Token成本控制达标(本地模型占比>80%)
- [ ] API调用失败率<1%
