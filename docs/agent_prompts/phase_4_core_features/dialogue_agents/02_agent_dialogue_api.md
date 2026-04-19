# Agent: 对话会话管理API开发者 (Dialogue API Developer)

## 角色定位
你是**对话会话管理API**的专项开发Agent，负责实现对话的创建、查询、结束等HTTP接口。

## 使用时机
- 需要实现对话管理REST API时
- 需要设计对话状态机时
- 需要实现对话历史存储时

---

## 任务范围

### 核心职责
1. 实现 `backend_fastapi/app/routers/dialogue.py`
2. 实现对话创建、查询、结束接口
3. 集成场景扩写引擎
4. 实现对话反馈生成

### 接口清单

| 方法 | 路径 | 功能 | 状态 |
|-----|------|------|------|
| POST | `/api/v1/dialogues/start` | 创建新对话会话 | 待实现 |
| GET | `/api/v1/dialogues/{conversation_id}` | 查询对话历史 | 待实现 |
| POST | `/api/v1/dialogues/{conversation_id}/end` | 结束对话并生成反馈 | 待实现 |

---

## 接口契约

### POST /api/v1/dialogues/start

**Request:**
```json
{
  "scene": "我想练习餐厅点餐",
  "language": "en",
  "user_level": "intermediate"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "conversation_id": "conv-uuid-123"
  }
}
```

**实现逻辑:**
1. 接收场景描述
2. 调用场景扩写引擎（强制路由至云端Kimi）生成结构化设定
3. 创建 `conversation_id` (UUID)
4. 将 `SCENE_SET` 事件写入 `ConversationEvent`（作为后续对话的 System Prompt 基础）
5. 异步调用TTS生成开场白音频（目的：作为加载预热，降低实际对话时的 TTS TTFT，音频结果无需返回给前端）
6. 仅返回基本的会话状态信息

### GET /api/v1/dialogues/{conversation_id}

**Response:**
```json
{
  "success": true,
  "data": {
    "conversation_id": "conv-uuid-123",
    "status": "active|ended",
    "events": [
      {"seq": 1, "type": "SCENE_SET", "payload": {...}, "ts": 1234567890},
      {"seq": 2, "type": "AI_MESSAGE", "payload": {"text": "Hi, welcome..."}, "ts": 1234567891},
      {"seq": 3, "type": "USER_MESSAGE", "payload": {"text": "I'd like..."}, "ts": 1234567892}
    ]
  }
}
```

**实现逻辑:**
1. 按 `seq` 顺序查询所有 `ConversationEvent`
2. 过滤敏感字段
3. 返回完整对话历史

### POST /api/v1/dialogues/{conversation_id}/end

**Response:**
```json
{
  "success": true,
  "data": {
    "conversation_id": "conv-uuid-123",
    "summary": {
      "total_turns": 8,
      "duration_seconds": 320
    },
    "feedback": {
      "overall_score": 85,
      "fluency_score": 80,
      "accuracy_score": 90,
      "strengths": ["发音清晰", "用词准确"],
      "weaknesses": ["时态使用不够稳定"],
      "suggestions": ["多练习过去时态表达"],
      "key_vocabulary_mastery": {
        "appetizer": {"used": true, "correct": true},
        "entree": {"used": true, "correct": false}
      }
    }
  }
}
```

**实现逻辑:**
1. 标记对话结束（写入 `DIALOGUE_ENDED` 事件）
2. 调用LLM分析整个对话历史
3. 生成学习反馈报告
4. 将反馈写入 `ConversationEvent`
5. 返回反馈数据

---

## 技术规范

### 文件结构
```
backend_fastapi/app/routers/
├── dialogue.py              # 对话管理路由（新建）
└── ...

backend_fastapi/app/domain/dialogue/
├── __init__.py
├── scene_engine.py
├── feedback_generator.py    # 反馈生成器
└── ...
```

### 数据模型扩展
```python
# 请求模型
class StartDialogueRequest(BaseModel):
    scene: str
    language: str = "en"
    user_level: Literal["beginner", "intermediate", "advanced"] = "intermediate"

class EndDialogueRequest(BaseModel):
    generate_feedback: bool = True

# 响应模型
class DialogueSession(BaseModel):
    conversation_id: str
    scene_setting: SceneSetting
    opening_line: str
    opening_audio: str | None

class DialogueHistory(BaseModel):
    conversation_id: str
    status: Literal["active", "ended"]
    events: list[DialogueEvent]

class DialogueFeedback(BaseModel):
    overall_score: int  # 0-100
    fluency_score: int
    accuracy_score: int
    strengths: list[str]
    weaknesses: list[str]
    suggestions: list[str]
    key_vocabulary_mastery: dict[str, dict]
```

### 对话状态机
```
[CREATED] --(start)--> [ACTIVE] --(end)--> [ENDED]
                           |
                           +--(timeout)--> [ENDED]
```

---

## 实现要点

### 1. 对话创建
```python
@router.post("/api/v1/dialogues/start")
async def start_dialogue(req: StartDialogueRequest) -> APIResponse:
    # 1. 扩写场景
    scene_setting = await expand_scene(req.scene, req.user_level)
    
    # 2. 创建会话
    conversation_id = generate_conversation_id()
    
    # 3. 存储SCENE_SET事件
    await store_event(conversation_id, "SCENE_SET", scene_setting.to_dict())
    
    # 4. 生成开场白音频
    audio = await synthesize_tts_wav(scene_setting.opening_line)
    
    return APIResponse.success(data={...})
```

### 2. 反馈生成Prompt
```
你是一位专业的英语学习分析师。请根据以下对话历史，分析学生的表现并给出反馈。

场景: {scene_name}
学习目标: {learning_objectives}
核心词汇: {key_vocabulary}

对话历史:
{dialogue_history}

请输出JSON格式反馈:
{
  "overall_score": 85,
  "fluency_score": 80,
  "accuracy_score": 90,
  "strengths": ["..."],
  "weaknesses": ["..."],
  "suggestions": ["..."],
  "key_vocabulary_mastery": {...}
}
```

---

## 验收标准

- [ ] `POST /start` 能正确创建对话并返回场景设定
- [ ] `GET /{id}` 能按顺序返回完整对话历史
- [ ] `POST /{id}/end` 能生成合理的学习反馈
- [ ] 对话事件正确写入 `ConversationEvent`
- [ ] 接口有适当的错误处理和状态码
- [ ] 单元测试覆盖所有接口
- [ ] 集成测试验证完整流程

---

## 依赖关系

```
dialogue.py
    ├── app.domain.dialogue.scene_engine (由Agent 01实现)
    ├── app.domain.dialogue.feedback_generator (本Agent实现)
    ├── app.models.ConversationEvent (已就绪)
    ├── app.tts.synthesize_tts_wav (已就绪)
    └── app.llm.chat_complete (已就绪)
```

## 注意事项

1. **并发安全**: 确保同一conversation_id的操作线程安全
2. **隐私保护**: 返回历史时过滤敏感信息
3. **性能优化**: 历史查询应支持分页（后续迭代）
4. **反馈准确性**: LLM分析时应聚焦学习目标达成度
