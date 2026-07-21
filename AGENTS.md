# AI 外语学习系统 - Agent 指南

> AI驱动的英语学习桌面应用：词汇学习、作文批改、语音对话三大核心模块

## 快速启动

```powershell
# 后端 (FastAPI) - 默认端口 8012，默认数据库 SQLite data/app.db
cd backend_fastapi && .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8012

# 前端 (Vue 3 + Vite + Electron)
cd app/v5 && npm install && npm run dev

# 基础设施 (Redis, ES, Neo4j，可选 - 基础功能不依赖)
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

## 架构分层

```
routers/ & interfaces/ → application/ → domain/ → infrastructure/
         ↓                    ↓            ↓            ↓
       HTTP路由            业务服务      领域模型      基础设施
```

**严格依赖方向**：上层依赖下层，禁止反向依赖。

### 后端目录结构

| 层级 | 目录 | 职责 |
|------|------|------|
| 路由层（旧） | `routers/` | 词汇/作文/语音/学习等业务路由 |
| 路由层（新） | `interfaces/` | admin/auth/analytics/knowledge_graph/realtime_assistant 等新路由 |
| 应用层 | `application/` | 业务逻辑编排、跨领域协调 |
| 领域层 | `domain/` | 核心业务规则、领域模型 |
| 基础设施层 | `infrastructure/` | 数据库、缓存、消息队列、存储 |

> 新功能优先添加到 `interfaces/`，两个路由层都在 `main.py` 中统一注册。

### 前端目录结构

| 目录 | 职责 |
|------|------|
| `src/views/` | 页面组件 (路由映射) |
| `src/components/` | 可复用组件 |
| `src/stores/` | Pinia 状态管理 |
| `src/services/` | API 和 WebSocket 服务 |
| `electron/main/` | Electron 主进程 |

## 核心模块实现

| 模块 | 路由入口 | 应用服务 | 领域逻辑 |
|------|----------|----------|----------|
| **词汇** | `routers/vocab.py` | `application/db_vocabulary.py` | `domain/srs/sm2.py` |
| **作文** | `routers/essays.py` | `application/essay_grading.py` | `domain/essay_*.py` |
| **语音** | `routers/voice.py` | `voice_stream.py` | `domain/realtime_assistant/` |

## 关键技术组件状态

> ⚠️ 重要：以下为当前实现状态，非早期方案。详见 [Detailed_System_Architecture.md](docs/Detailed_System_Architecture.md)

| 组件 | 当前实现 | 位置 | 备注 |
|------|----------|------|------|
| **ASR** | SeamlessM4T | `voice_stream.py` | CPU 推理，默认后端 |
| **TTS** | Kokoro → Edge-TTS → Silence | `tts.py` | 本地优先，在线回退 |
| **OCR** | PaddleOCR | `ocr.py` | 懒加载，CPU 运行 |
| **LLM** | Kimi API + Qwen 本地 | `llm.py` | 竞速机制，先到先用 |
| **间隔复习** | SM-2 简化版 | `domain/srs/sm2.py` | 已落地 |
| **知识图谱** | Neo4j | `domain/knowledge_graph/` | 三层推荐策略已落地 |

### 历史方案说明

文档中若出现 `faster-whisper / XTTS / Surya`，均视为早期历史方案，不代表当前主链路实现。

## 关键配置

| 配置项 | 环境变量 | 默认值 |
|--------|----------|--------|
| 服务端口 | `AIFL_PORT` | 8012 |
| 数据库 | `AIFL_DATABASE_URL` | `sqlite:///./data/app.db` |
| LLM API | `AIFL_LLM_BASE_URL` | http://127.0.0.1:1234/v1 (LM Studio) |
| LLM 模型 | `AIFL_LLM_MODEL` | qwen/qwen3.5-9b |
| ASR开关 | `AIFL_ENABLE_ASR` | false |
| JWT 密钥 | `AIFL_JWT_SECRET` | 需修改 |

**两套配置机制**：
- `app/settings.py`：启动时加载，读取 `.env` + 环境变量（`AIFL_` 前缀，`AliasChoices` 支持短名）
- `app/runtime_config.py`：热更新运行时配置，持久化到 `data/runtime_config.json`，前端设置页写入

## 测试命令

```bash
# 后端单元测试（asyncio_mode="auto"，无需手动加 @pytest.mark.asyncio）
cd backend_fastapi && pytest

# 后端集成测试（需真实服务：LM Studio、ASR、TTS）- 默认跳过
pytest -m integration --run-integration

# 前端/Electron 测试
cd app && npm test

# 代码检查（line-length=100）
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
- **AI**: OpenAI兼容API + SeamlessM4T + Kokoro TTS
- **存储**: PostgreSQL + Elasticsearch + Neo4j + MinIO

## 核心架构设计

### 词汇模块

- **SM-2 间隔复习**：`domain/srs/sm2.py` - 简化版已落地
- **词汇难度分级**：启发式规则自动标注 CEFR (A1-C2)
- **知识图谱推荐**：Neo4j 三层策略 (薄弱点扩展 > 已学扩展 > 兜底)
- **数据源优先级**：本地词库 → ES 模糊搜索 → LLM 生成 → 兜底定义

### 作文模块

- **统一入口**：`POST /v1/essays/grade` (文本或图片)
- **OCR 处理**：PaddleOCR 图片转文本
- **评分维度**：内容(30%) + 结构(25%) + 语言(25%) + 语法(20%)
- **等级映射**：A+/A/B+/B/C/D

### 语音对话模块

- **WebSocket 协议**：`/ws/v1` - ws-v1 事件协议
- **事件流**：`AUDIO_START → AUDIO_CHUNK → ASR_PARTIAL/FINAL → LLM_TOKEN → TTS_CHUNK → TASK_FINISHED`
- **LLM 竞速**：云端 Kimi + 本地 Qwen 并发，先到先用
- **Barge-in 打断**：用户可随时打断，已播报内容持久化，未播报注入上下文

### 教师端模块

- **20维度学情分析**：词汇增长、SM-2保持率、语法收敛等
- **三层 Agent 干预**：底层托底/中层突破/顶层突破
- **班级周报**：DB 聚合 + LLM 总结

## 异步任务队列

| 任务 | 队列 | 说明 |
|------|------|------|
| `generate_daily_vocab_task` | `default_tasks` | 按主题批量生成词汇 |
| `grade_essay_task` | `urgent_tasks` | 作文批改 |
| `generate_all_daily_summaries_task` | `batch_tasks` | 每日学生摘要 |
| `run_tiered_analysis_task` | `batch_tasks` | 分层 Agent 分析 |

**降级保护**：Celery 不可用时自动回退到本地同步执行 (`_DummyCelery`)。

## 参考文档

### 系统架构
- [详细系统架构](docs/Detailed_System_Architecture.md) - 单词/作文/对话/教师端模块详细设计
- [语音对话现状](docs/Voice_Dialogue_Full_Status_20260418.md) - ASR/TTS/LLM 配置详情

### 开发规范
- [代码规范](docs/development_guide/02-coding-standards.md) - Python/TypeScript 命名约定
- [性能标准](docs/development_guide/03-performance-standards.md) - 延迟/吞吐量要求
- [接口定义](docs/development_guide/05-interface-definition.md) - REST API 设计规范
- [技术栈规划](docs/development_guide/07-tech-stack.md) - 技术选型说明

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

## 编码规范速查

### Python 命名

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块/包 | 小写下划线 | `pronunciation_engine` |
| 类 | 大驼峰 | `PhonemeAnalyzer` |
| 函数/方法 | 小写下划线 | `analyze_phonemes()` |
| 常量 | 大写下划线 | `MAX_RETRY_COUNT` |
| 私有成员 | 单下划线前缀 | `_internal_cache` |

### TypeScript/Vue 命名

| 类型 | 规范 | 示例 |
|------|------|------|
| 组件 | 大驼峰多单词 | `AudioRecorder.vue` |
| 组合式函数 | use前缀小驼峰 | `useAudioRecorder()` |
| 类型定义 | 大驼峰Type后缀 | `AssessmentResultType` |

### 代码格式

- **Python**: Black + isort (line-length=100)
- **TypeScript/Vue**: Prettier + ESLint (tabWidth=2, singleQuote)

## 常见问题

### 环境变量配置
配置文件使用 `AIFL_` 前缀避免冲突。优先级：环境变量 > `.env` 文件 > 默认值。

### WebSocket 语音流
语音对话使用 ws-v1 协议。关键事件：
- `ASR_PARTIAL`/`ASR_FINAL`: 语音识别结果
- `LLM_TOKEN`: LLM 流式输出
- `TTS_CHUNK`/`TTS_RESULT`: TTS 音频分片
- `TASK_FINISHED`/`TASK_ABORTED`: 任务结束/打断

### 模型路由
- 场景扩写 → Kimi API
- 对话执行 → Qwen 本地模型 (竞速机制)
- 详见 `.github/agents/module-e-model-routing.agent.md`

### 前端开发要点
- 路由模式：`createWebHashHistory()` 兼容 Electron
- 组件风格：`<script setup lang="ts">` + Composition API
- 状态管理：Pinia 函数式定义 (`defineStore('name', () => {...})`)
- API 封装：`services/` 模块独立封装，复用 `api.ts` 实例
- **后端 URL**：从 `localStorage.app_config` 动态读取（非 .env），默认 `http://localhost:8012`；`api.ts` 中含旧端口（8011/8005/8000→8012）的迁移逻辑，勿删除

---

详见 [团队入职指南](docs/team_onboarding/README.md)。
