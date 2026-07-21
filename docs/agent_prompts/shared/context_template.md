# 共享项目上下文模板

> 在每个 agent prompt 顶部引用此上下文，确保所有 agent 对项目有统一理解。

---

## 项目基本信息

- **项目名称**: AI外语学习系统
- **目标架构**: FastAPI (Python) 单栈后端
- **指导原则**: SSD (规范驱动开发) + BMAD (业务模型驱动架构设计)
- **当前策略**: 全量迁移到 `backend_fastapi`，废弃旧 `backend` (Node.js/TypeScript)

---

## 代码库结构

```
./
├── backend/                    # 旧后端 (Node.js/TypeScript) - 待废弃
│   ├── src/
│   │   ├── api/                # Express Routes
│   │   ├── auth/               # JWT认证实现
│   │   ├── controllers/        # 业务控制器
│   │   ├── database/           # SQLite手写SQL
│   │   ├── infra/              # mDNS, ZeroMQ软总线
│   │   ├── managers/           # 业务管理器
│   │   ├── middleware/         # Express中间件
│   │   ├── models/             # 数据模型
│   │   ├── orchestrator/       # 自研编排器
│   │   ├── security/           # 加密服务
│   │   ├── services/           # 业务服务
│   │   ├── shared/             # 共享工具
│   │   ├── softbus/            # ZeroMQ软总线
│   │   └── utils/              # 工具函数
│   ├── tests/                  # 旧测试
│   └── package.json
│
├── backend_fastapi/            # 新后端 (Python/FastAPI) - 目标架构
│   ├── app/
│   │   ├── main.py             # FastAPI入口
│   │   ├── db.py               # SQLModel数据库配置
│   │   ├── settings.py         # Pydantic配置
│   │   ├── models.py           # SQLModel模型
│   │   ├── llm.py              # LLM调用封装
│   │   ├── ocr.py              # OCR服务
│   │   ├── tts.py              # TTS服务
│   │   ├── voice_stream.py     # WebSocket语音对话
│   │   ├── model_router.py     # 模型路由(成员5)
│   │   ├── context_store.py    # 上下文存储(成员5)
│   │   ├── retry_utils.py      # 重试工具
│   │   ├── token_utils.py      # Token工具
│   │   ├── prompts/            # Prompt模板
│   │   ├── routers/            # API路由
│   │   └── compat_legacy.py    # 旧API兼容层
│   ├── tests/                  # 新测试(1,467 LOC)
│   └── pyproject.toml
│
├── NewBasicMoudules/           # 成员交付物
│   ├── database_search_layer_deliverable/  # 成员1: 数据库+ES+Redis
│   ├── delivery_sprint3_4_knowledge_graph/ # 成员3: 知识图谱+推荐
│   ├── part_d_security/                     # 成员4: 安全认证
│   └── team_onboarding/                     # 成员2: 基础设施(目录为空)
│
└── docs/
    ├── Detailed_System_Architecture.md
    ├── development_guide/
    │   └── SSD_BMAD_Architecture_Transformation_Plan.md
    ├── team_performance_analysis.md
    └── agent_prompts/          # 本目录
```

---

## 关键数据

| 指标 | 旧 backend | backend_fastapi |
|------|-----------|-----------------|
| 业务代码 LOC | ~10,266 | ~5,236 |
| 测试代码 LOC | 632 | 1,467 |
| 文件数 | 64 | 25 |

---

## BMAD 目标架构

```
backend_fastapi/app/
├── domain/              # Layer 4: 业务模型层
├── application/         # Layer 3: 应用服务层
├── infrastructure/      # Layer 2: 基础设施层
└── interfaces/          # Layer 1: 接口适配层
```

---

## 当前阶段

- **阶段1**: 死代码清理 / 有效代码迁移
- **阶段2**: 新模块整合
- **阶段3**: 基础设施加固/重写

---

## 约束条件

1. **代码未动，规范和文档先行**
2. 所有迁移必须保留 `compat_legacy.py` 的兼容能力
3. 禁止在旧 `backend` 上开发新功能
4. 每次代码变更必须同步更新文档
5. 所有新代码必须通过 ruff + mypy 检查
