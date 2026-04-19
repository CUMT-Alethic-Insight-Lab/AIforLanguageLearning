# AI 外语学习系统 - Agent 指南

> AI驱动的英语学习桌面应用：词汇学习、作文批改、语音对话三大核心模块

## 快速启动

```powershell
# 后端 (FastAPI)
cd backend_fastapi && .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8012

# 前端 (Vue 3 + Vite + Electron)
cd app/v5 && npm install && npm run dev

# 基础设施 (PostgreSQL, Redis, ES, Neo4j)
docker-compose -f backend_fastapi/docker-compose.dev.yml up -d

# 一键启动脚本
./scripts/start.ps1                    # 检查环境并启动前后端
./scripts/start_infra_native.ps1       # 启动本地基础设施
```

## 项目结构

| 目录 | 说明 |
|------|------|
| `backend_fastapi/app/` | FastAPI 后端主代码 |
| `app/v5/` | Vue 3 + Vite 前端 |
| `docs/` | 架构设计、开发规范、团队入职文档 |
| `.github/agents/` | 领域专家 Agent 定义 |

## 关键配置

| 配置项 | 环境变量 | 默认值 |
|--------|----------|--------|
| 服务端口 | `AIFL_PORT` | 8012 |
| 数据库 | `AIFL_DATABASE_URL` | SQLite |
| LLM API | `AIFL_LLM_BASE_URL` | http://127.0.0.1:1234/v1 |
| ASR开关 | `AIFL_ENABLE_ASR` | false |

## 测试命令

```bash
# 后端单元测试
cd backend_fastapi && pytest

# 后端集成测试 (需真实服务: LM Studio, ASR, TTS)
pytest -m integration --run-integration

# 前端/Electron 测试
cd app && npm test

# 代码检查
cd backend_fastapi && ruff check app/
```

## 构建与分发

```bash
# 前端构建
cd app/v5 && npm run build

# Electron 桌面应用打包
cd app/v5 && npm run dist    # 输出至 release/
```

## 技术栈

- **后端**: FastAPI + SQLModel + Alembic + Celery + Redis
- **前端**: Vue 3 + Vite + Pinia + Tailwind + Electron
- **AI**: OpenAI兼容API + faster-whisper + Kokoro TTS
- **存储**: PostgreSQL + Elasticsearch + Neo4j + MinIO

## 架构分层

```
routers/ → application/ → domain/ → infrastructure/
   ↓           ↓            ↓            ↓
 HTTP路由    业务服务      领域模型      基础设施
```

## 核心模块

| 模块 | 路由 | 功能 |
|------|------|------|
| 词汇 | `/api/vocab` | 词汇查询、SM-2间隔复习 |
| 作文 | `/api/essays` | LLM作文批改评分 |
| 语音 | `/api/voice`, `/ws/voice` | 实时语音对话 (WebSocket) |

## 参考文档

### 系统架构
- [系统架构设计](docs/Detailed_System_Architecture.md) - 单词/作文/对话模块详细设计
- [语音对话现状](docs/Voice_Dialogue_Full_Status_20260418.md) - ASR/TTS/LLM配置

### 开发规范
- [代码规范](docs/development_guide/02-coding-standards.md) - Python/TypeScript命名约定
- [性能标准](docs/development_guide/03-performance-standards.md) - 延迟/吞吐量要求
- [接口定义](docs/development_guide/05-interface-definition.md) - REST API设计规范

### 模块交接
- [对话模块](docs/agent_prompts/phase_4_core_features/handoff_dialogue_module.md)
- [作文模块](docs/agent_prompts/phase_4_core_features/handoff_essay_module.md)
- [词汇模块](docs/agent_prompts/phase_4_core_features/handoff_vocabulary_module.md)

### Agent协作
- [Agent Prompt模板](docs/development_guide/08-agent-prompts.md)
- [Agent Swarm架构](docs/development_guide/14-agent-swarm.md)

## 领域专家 Agent

项目定义了多个领域专家 Agent，位于 `.github/agents/`：

| Agent | 用途 |
|-------|------|
| `01-project-purpose` | 项目愿景、BMAD方法论 |
| `02-coding-standards` | 编码规范 |
| `05-interface-definition` | API设计 |
| `module-e-model-routing` | LLM模型路由 |

调用方式：告诉 Copilot 使用特定 agent，如"使用 module-e-model-routing agent 咨询模型路由问题"。

## 常见问题

### 环境变量配置
配置文件使用 `AIFL_` 前缀避免冲突。优先级：环境变量 > `.env` 文件 > 默认值。

### WebSocket 语音流
语音对话使用自定义协议：`ASR_PARTIAL`/`ASR_FINAL`/`LLM_TOKEN`/`TTS_CHUNK`。详见 [Voice_Dialogue_Full_Status](docs/Voice_Dialogue_Full_Status_20260418.md)。

### 模型路由
对话场景扩写 → Kimi API；对话执行 → Qwen本地模型。详见 `.github/agents/module-e-model-routing.agent.md`。

---

详见 [团队入职指南](docs/team_onboarding/README.md)。
