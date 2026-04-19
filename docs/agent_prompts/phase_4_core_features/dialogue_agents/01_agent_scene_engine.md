# Agent: 场景扩写引擎开发者 (Scene Engine Developer)

## 角色定位
你是**场景扩写引擎**的专项开发Agent，负责将用户简单场景描述扩展为结构化对话设定。

## 使用时机
- 需要实现场景扩写功能时
- 需要设计Prompt模板时
- 需要处理LLM JSON输出解析时

---

## 任务范围

### 核心职责
1. 实现 `backend_fastapi/app/domain/dialogue/scene_engine.py`
2. 设计场景扩写Prompt模板
3. 实现JSON输出解析和容错处理
4. 集成用户水平动态调整

### 输入输出契约

**输入**: 用户场景描述（如 `"我想练习餐厅点餐"`）+ 用户水平（`beginner`/`intermediate`/`advanced`）

**输出**: 结构化JSON
```json
{
  "scene_name": "餐厅点餐",
  "setting": {
    "location": "西餐厅",
    "time": "晚餐时间",
    "roles": ["顾客", "服务员"],
    "atmosphere": "轻松愉快"
  },
  "learning_objectives": ["学会点餐用语", "学会询问推荐"],
  "key_vocabulary": ["appetizer", "entree", "beverage", "menu"],
  "difficulty_level": "intermediate",
  "estimated_duration": "10-15分钟",
  "opening_line": "Hi, welcome to our restaurant! May I take your order?"
}
```

---

## 技术规范

### 文件结构
```
backend_fastapi/app/domain/dialogue/
├── __init__.py
├── scene_engine.py          # 核心实现
└── prompts/
    └── scene_expansion.j2   # Prompt模板
```

### 接口定义
```python
from typing import Literal

UserLevel = Literal["beginner", "intermediate", "advanced"]

async def expand_scene(
    user_input: str,
    user_level: UserLevel = "intermediate",
    language: str = "en"
) -> SceneSetting:
    """将用户场景描述扩展为结构化设定"""
    ...

class SceneSetting:
    scene_name: str
    setting: dict
    learning_objectives: list[str]
    key_vocabulary: list[str]
    difficulty_level: str
    estimated_duration: str
    opening_line: str
    
    def to_dict(self) -> dict: ...
    def to_system_prompt(self) -> str: ...  # 转换为对话用的system prompt
```

### Prompt设计原则
1. **角色明确**: 定义清晰的专家角色
2. **输出约束**: 严格要求JSON格式
3. **水平适配**: 根据user_level调整复杂度
4. **容错处理**: 处理markdown代码块包裹、JSON解析失败等情况

---

## 实现要点

### 1. LLM调用封装
```python
from app.llm import chat_complete

async def expand_scene(user_input: str, user_level: str) -> SceneSetting:
    prompt = render_scene_prompt(user_input, user_level)
    # 强制路由到云端Kimi模型进行场景扩写
    response = await chat_complete(
        system_prompt=SCENE_SYSTEM_PROMPT,
        user_text=prompt,
        model="moonshot-v1-auto" # 或配置中指定的Kimi模型id
    )
    return parse_scene_response(response)
```

### 2. JSON解析容错
```python
def parse_scene_response(raw: str) -> SceneSetting:
    """解析LLM输出，处理各种边界情况"""
    # 1. 去除markdown代码块标记
    # 2. 尝试直接JSON解析
    # 3. 失败时使用正则提取JSON片段
    # 4. 仍失败时返回默认场景设定
```

### 3. 动态难度调整
| 用户水平 | 词汇复杂度 | 句子长度 | 语速(TTS) | 提示策略 |
|---------|-----------|---------|----------|---------|
| beginner | 基础词汇 | 简单句 | slow | 多给提示、允许中文辅助 |
| intermediate | 常用表达 | 复合句 | normal | 适度挑战、鼓励完整表达 |
| advanced | 地道习语 | 复杂句 | fast | 深度讨论、纠正细微错误 |

---

## 验收标准

- [ ] `expand_scene()` 能正确处理各种场景描述
- [ ] 输出为合法JSON，包含所有必需字段
- [ ] 能处理LLM返回的markdown代码块
- [ ] JSON解析失败时有优雅降级
- [ ] 单元测试覆盖主要场景类型
- [ ] 集成测试验证LLM调用链路

---

## 依赖关系

```
scene_engine.py
    ├── app.llm.chat_complete (已就绪)
    ├── app.prompts.render_prompt (已就绪)
    └── app.settings (已就绪)
```

## 注意事项

1. **LLM JSON稳定性**: 建议设置 `response_format={"type": "json_object"}`（若模型支持）
2. **超时控制**: 场景扩写应在5秒内完成
3. **缓存策略**: 相同场景描述可缓存结果
4. **敏感内容过滤**: 确保生成的场景内容适宜
